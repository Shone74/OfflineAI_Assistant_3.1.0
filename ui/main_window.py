"""Main application window — ties together the chat, sidebar, and status bar."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Q_ARG, QMetaObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ai.models.model_loader import ModelType
from ai.models.model_manager import ModelManager, _is_test_mode
from core.assistant import Assistant
from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logger import get_logger
from core.paths import DATA_DIR
from core.security_layer import SecurityLayer
from plugins import PluginManager
from ui.agents_page import AgentsPage
from ui.assistant_hub import AssistantHub
from ui.automation_dashboard import AutomationDashboard
from ui.capabilities_page import CapabilitiesPage
from ui.chat_widget import ChatWidget
from ui.conversation_sidebar import ConversationSidebar
from ui.knowledge_dashboard import KnowledgeDashboard
from ui.memory_page import MemoryPage
from ui.models_page import ModelsPage
from ui.projects_page import ProjectsPage
from ui.router import Router
from ui.settings import SettingsDialog
from ui.system_status import SystemStatusWidget
from ui.system_tray import SystemTrayManager
from ui.task_editor_dialog import TaskEditorDialog
from ui.theme_manager import ThemeManager
from ui.tools_page import ToolsPage
from ui.voice_page import VoicePage
from ui.workflow_builder import WorkflowBuilder
from voice import VoiceManager

logger = get_logger("ui.main_window")


def _noop_publish(event_type: str, data: dict[str, Any] | None = None) -> None:
    """No-op callable used as ``publish_fn`` inside GenerationWorker.

    The worker runs on a QThread and must not publish EventBus events
    (subscribers call Qt widget methods on the publishing thread).
    GUI-thread signal slots handle publication instead.
    """


class GenerationWorker(QThread):
    """Background QThread that runs Assistant.process_message.

    Emits Qt signals only — GUI-thread slots connected via QueuedConnection
    receive them and publish EventBus events from the main thread.
    """

    token_emitted = Signal(str)
    generation_finished = Signal(str)
    generation_cancelled = Signal()
    generation_failed = Signal(str)

    def __init__(
        self,
        assistant: Assistant,
        text: str,
        cancel_event: threading.Event,
        images: list | None = None,
    ) -> None:
        super().__init__()
        self._assistant = assistant
        self._text = text
        self._cancel_event = cancel_event
        self._images = images

    def run(self) -> None:
        try:
            response = self._assistant.process_message(
                self._text,
                cancel_event=self._cancel_event,
                token_callback=self._on_token,
                pulse_callback=lambda: None,
                publish_fn=_noop_publish,
                images=self._images,
            )
        except Exception as exc:
            self.generation_failed.emit(str(exc))
            return
        if self._cancel_event.is_set():
            self.generation_cancelled.emit()
        else:
            self.generation_finished.emit(response)

    def _on_token(self, token: str) -> None:
        self.token_emitted.emit(token)


class AgentRunWorker(QThread):
    """Background QThread that runs Assistant.run_agent_plan.

    Emits Qt signals only — GUI-thread slots connected via QueuedConnection
    receive them and publish EventBus events from the main thread.  Agent
    lifecycle events generated inside ``run_agent_plan`` / ``BaseAgent`` are
    marshalled to the GUI thread through the ``agent_event`` signal.
    """

    finished = Signal(str, str)
    agent_event = Signal(str, dict)

    def __init__(
        self,
        assistant: Assistant,
        goal: str,
        project_id: str | None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        super().__init__()
        self._assistant = assistant
        self._goal = goal
        self._project_id = project_id
        self._cancel_event = cancel_event

    def run(self) -> None:
        try:
            result = self._assistant.run_agent_plan(
                self._goal,
                project_id=self._project_id,
                cancel_event=self._cancel_event,
                publish_fn=self._emit_event,
            )
            self.finished.emit(result, "")
        except Exception as exc:
            logger.exception("Agent run failed in worker thread")
            import traceback
            tb = traceback.format_exc()
            self.finished.emit("", f"{exc}\n{tb}")

    def _emit_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Thread-safe bridge: emit a Qt signal that is delivered to GUI-thread
        subscribers via QueuedConnection.  A shallow copy of *data* is passed
        so the dict cannot be mutated after emission."""
        self.agent_event.emit(event_type, dict(data) if data else {})


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        theme: ThemeManager,
        assistant: Assistant,
        security: SecurityLayer | None = None,
        voice: VoiceManager | None = None,
        plugin_manager: PluginManager | None = None,
        automation_manager: Any = None,
        automation_dispatcher: Any = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._event_bus = event_bus
        self._theme = theme
        self._assistant = assistant
        self._security = security
        self._voice = voice
        self._plugin_manager = plugin_manager
        self._automation_manager = automation_manager
        self._automation_dispatcher = automation_dispatcher
        self._current_response = ""
        self._response_displayed = False
        self._tokens_streamed = False
        self._generation_active = False
        self._cancel_event: threading.Event | None = None
        self._generation_worker: GenerationWorker | None = None
        self._generation_cancel_event: threading.Event | None = None
        self._agent_worker: AgentRunWorker | None = None
        self._agent_cancel_event: threading.Event | None = None
        self._agent_active = False
        self._permission_result: QMessageBox.StandardButton | None = None
        self._event_sub_ids: list[tuple[str, str]] = []

        self.setWindowTitle(config.get("app.name", "Offline AI Assistant"))
        self.resize(
            config.get("ui.window_width", 1000),
            config.get("ui.window_height", 700),
        )

        self._build_ui()
        self._wire_events()

        if self._security is not None:
            self._security.set_approval_callback(self._request_permission)

        # Run Now completion (async dispatcher path): refresh the automation
        # dashboard and surface the outcome on the status bar.  The signal is
        # emitted on the GUI thread by the dispatcher after finalization.
        if self._automation_dispatcher is not None:
            self._automation_dispatcher.task_finalized.connect(
                self._on_run_now_finalized
            )

        self._install_shortcuts()
        self._apply_accessibility()
        self._apply_polish()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        self._stack = QStackedWidget()
        self._router = Router(self._stack)

        self._chat_page = QWidget()
        chat_layout = QHBoxLayout(self._chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        self._conversation_sidebar = ConversationSidebar()
        self._conversation_sidebar.conversation_selected.connect(self._on_conversation_selected)
        self._conversation_sidebar.new_conversation.connect(self._on_new_chat_requested)
        self._conversation_sidebar.delete_conversation.connect(self._on_delete_conversation)
        self._conversation_sidebar.rename_conversation.connect(self._on_rename_conversation)
        self._conversation_sidebar.pin_conversation.connect(self._on_pin_conversation)
        chat_layout.addWidget(self._conversation_sidebar)

        self._chat_container = QWidget()
        self._chat_container_layout = QVBoxLayout(self._chat_container)
        self._chat_container_layout.setContentsMargins(0, 0, 0, 0)

        self._chat = ChatWidget()
        self._chat_container_layout.addWidget(self._chat)

        chat_layout.addWidget(self._chat_container, stretch=1)

        self._router.register("chat", self._chat_page)

        self._assistant_hub = AssistantHub(
            self._assistant, navigator=self._navigate_and_refresh
        )
        self._router.register("home", self._assistant_hub)

        self._automation_dashboard = AutomationDashboard()
        self._automation_dashboard.run_requested.connect(self._on_run_workflow)
        self._automation_dashboard.task_editor_requested.connect(self._on_task_editor)
        self._automation_dashboard.task_deleted.connect(self._on_delete_scheduled_task)
        self._automation_dashboard.task_run_requested.connect(self._on_run_scheduled_task)
        self._automation_dashboard.task_enabled_changed.connect(self._on_task_enabled_changed)
        self._router.register("automation", self._automation_dashboard)

        self._workflow_builder = WorkflowBuilder(automation_manager=self._automation_manager)
        self._router.register("workflow", self._workflow_builder)

        self._knowledge_dashboard = KnowledgeDashboard()
        self._knowledge_dashboard.index_requested.connect(self._on_knowledge_index)
        self._knowledge_dashboard.rebuild_requested.connect(self._on_knowledge_rebuild)
        self._knowledge_dashboard.export_requested.connect(self._on_knowledge_export)
        self._knowledge_dashboard.search_requested.connect(self._on_knowledge_search)
        self._knowledge_dashboard.delete_requested.connect(self._on_knowledge_delete)
        self._knowledge_dashboard.index_file_requested.connect(self._on_knowledge_index_file)
        self._router.register("knowledge", self._knowledge_dashboard)

        self._models_page = ModelsPage(
            model_manager=getattr(self._assistant, "model_manager", None),
            assistant=self._assistant,
            event_bus=self._event_bus,
        )
        self._router.register("models", self._models_page)

        self._memory_page = MemoryPage(config=self._config, assistant=self._assistant)
        self._router.register("memory", self._memory_page)

        self._capabilities_page = CapabilitiesPage(self._assistant)
        self._router.register("capabilities", self._capabilities_page)

        self._projects_page = ProjectsPage(self._assistant)
        self._router.register("projects", self._projects_page)

        self._agents_page = AgentsPage(assistant=self._assistant)
        self._router.register("agents", self._agents_page)

        self._tools_page = ToolsPage(
            assistant=self._assistant,
            event_bus=self._event_bus,
        )
        self._router.register("tools", self._tools_page)

        self._voice_page = VoicePage(
            config=self._config,
            event_bus=self._event_bus,
            voice_manager=self._voice,
        )
        if self._voice is not None:
            self._voice_page.get_voice_settings()._update_status()
        self._router.register("voice", self._voice_page)

        central_widget = QWidget()
        central_layout = QHBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)

        self._sidebar = self._build_sidebar()
        central_layout.addWidget(self._sidebar)

        central_layout.addWidget(self._stack)
        central_layout.setStretch(1, 1)

        self.setCentralWidget(central_widget)

        self._status = SystemStatusWidget(model_name=self._assistant.model_name)
        self.setStatusBar(self._status)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(False)
        self._model_combo.setMinimumWidth(120)
        self._populate_model_combo()
        self._model_combo.setAccessibleName("Active model selector")
        self._status.addPermanentWidget(self._model_combo)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)

        self._chat.send_requested.connect(self._on_send)
        self._chat.send_with_images_requested.connect(self._on_send_with_images)
        self._chat.new_chat_requested.connect(self._on_new_chat_requested)
        self._chat.search_requested.connect(self._on_search_memory_requested)
        self._chat.stop_generation.connect(self._on_stop_generation)
        self._chat.message_deleted.connect(self._on_message_deleted)
        self._sidebar.currentItemChanged.connect(self._on_sidebar_item_changed)
        if self._voice is not None:
            self._chat.voice_requested.connect(self._on_voice_input)
            self._chat.play_requested.connect(self._on_play_recording)
            self._event_sub_ids.append(("VOICE_INPUT_START", self._event_bus.subscribe("VOICE_INPUT_START", self._on_voice_lifecycle)))
            self._event_sub_ids.append(("VOICE_INPUT_END", self._event_bus.subscribe("VOICE_INPUT_END", self._on_voice_lifecycle)))
            self._event_sub_ids.append(("VOICE_TRANSCRIPT", self._event_bus.subscribe("VOICE_TRANSCRIPT", self._on_voice_transcript)))
            self._event_sub_ids.append(("VOICE_ERROR", self._event_bus.subscribe("VOICE_ERROR", self._on_voice_error)))
            self._event_sub_ids.append(("VOICE_PLAY_START", self._event_bus.subscribe("VOICE_PLAY_START", self._on_voice_play_start)))
            self._event_sub_ids.append(("VOICE_PLAY_DONE", self._event_bus.subscribe("VOICE_PLAY_DONE", self._on_voice_play_done)))
            self._event_sub_ids.append(("WAKE_WORD_DETECTED", self._event_bus.subscribe("WAKE_WORD_DETECTED", self._on_voice_lifecycle)))

        self._projects_page.project_opened.connect(self._on_project_opened)
        self._projects_page.project_created.connect(self._on_project_created)
        self._projects_page.project_updated.connect(self._on_project_updated)
        self._projects_page.project_deleted.connect(self._on_project_deleted)
        self._projects_page.assign_agent_requested.connect(self._on_assign_agent)
        self._projects_page.run_agent_requested.connect(self._on_run_agent)

        self._tray = SystemTrayManager(self)
        self._tray.quit_requested.connect(self._on_tray_quit)
        self._tray.show()
        self._event_sub_ids.append(("AI_RESPONSE_RECEIVED", self._event_bus.subscribe("AI_RESPONSE_RECEIVED", self._on_ai_response)))
        self._event_sub_ids.append(("GENERATION_STARTED", self._event_bus.subscribe("GENERATION_STARTED", self._on_generation_started)))
        self._event_sub_ids.append(("GENERATION_TOKEN", self._event_bus.subscribe("GENERATION_TOKEN", self._on_generation_token)))
        self._event_sub_ids.append(("GENERATION_COMPLETED", self._event_bus.subscribe("GENERATION_COMPLETED", self._on_generation_completed)))
        self._event_sub_ids.append(("GENERATION_FAILED", self._event_bus.subscribe("GENERATION_FAILED", self._on_generation_failed)))
        self._event_sub_ids.append(("GENERATION_CANCELLED", self._event_bus.subscribe("GENERATION_CANCELLED", self._on_generation_cancelled)))
        self._event_sub_ids.append(("PLUGIN_ENABLED", self._event_bus.subscribe("PLUGIN_ENABLED", self._on_plugin_event)))
        self._event_sub_ids.append(("PLUGIN_DISABLED", self._event_bus.subscribe("PLUGIN_DISABLED", self._on_plugin_event)))
        self._event_sub_ids.append(("PLUGIN_ERROR", self._event_bus.subscribe("PLUGIN_ERROR", self._on_plugin_event)))
        self._event_sub_ids.append(("MODEL_LOADED", self._event_bus.subscribe("MODEL_LOADED", self._on_model_loaded)))
        self._event_sub_ids.append(("MODEL_UNLOADED", self._event_bus.subscribe("MODEL_UNLOADED", self._on_model_unloaded)))
        self._event_sub_ids.append(("MODEL_LOAD_FAILED", self._event_bus.subscribe("MODEL_LOAD_FAILED", self._on_model_load_failed)))
        self._event_sub_ids.append(("API_ENGINE_ACTIVE", self._event_bus.subscribe("API_ENGINE_ACTIVE", self._on_api_engine_active)))

        # The Vision button reflects the current model from the very start
        self._sync_vision_availability()

    def _build_sidebar(self) -> QListWidget:
        nav = QListWidget()
        nav.setMaximumWidth(240)
        nav.setAccessibleName("Main navigation sidebar")
        items = [
            ("🏠 Home", "home"),
            ("💬 Chat", "chat"),
            ("🧠 Memory", "memory"),
            ("📚 Knowledge", "knowledge"),
            ("🤖 Agents", "agents"),
            ("📦 Models", "models"),
            ("🔧 Capabilities", "capabilities"),
            ("📁 Projects", "projects"),
            ("🛠 Tools", "tools"),
            ("🎙 Voice", "voice"),
            ("⚡ Automation", "automation"),
            ("🔧 Workflow Builder", "workflow"),
            ("⚙ Settings", "settings"),
        ]
        for label, key in items:
            item = QListWidgetItem(label)
            item.setData(1000, key)
            nav.addItem(item)
        return nav

    # ------------------------------------------------------------------ #
    def _wire_events(self) -> None:
        self._event_sub_ids.append(("CONFIG_CHANGED", self._event_bus.subscribe("CONFIG_CHANGED", self._on_config_changed)))
        self._event_sub_ids.append(("PROFILE_UPDATED", self._event_bus.subscribe("PROFILE_UPDATED", self._on_profile_updated_event)))
        # Surface agent/automation/workflow lifecycle events on the status bar
        # without changing the chat flow.  These are best-effort hints.
        for evt in (
            "PLAN_CREATED",
            "AGENT_TASK_STARTED",
            "AGENT_TASK_COMPLETED",
            "AGENT_FINISHED",
            "AGENT_ERROR",
            "WORKFLOW_STARTED",
            "WORKFLOW_STEP",
            "WORKFLOW_COMPLETED",
            "AUTOMATION_TASK_SCHEDULED",
            "AUTOMATION_TASK_COMPLETED",
            "AUTOMATION_TASK_UPDATED",
            "AUTOMATION_TASK_DELETED",
            "SCHEDULER_TICK",
            "PLUGIN_DISCOVERED",
            "PLUGIN_LOAD_START",
            "PLUGIN_LOADED",
            "PLUGIN_LOAD_FAILED",
            "PLUGIN_UNLOADED",
            "NAVIGATE_TO_MEMORY",
            "NAVIGATE_TO_AGENTS",
            "NAVIGATE_TO_TOOLS",
            "NAVIGATE_TO_VOICE",
        ):
            self._event_sub_ids.append((evt, self._event_bus.subscribe(evt, self._on_system_event)))

    def _unsubscribe_all_events(self) -> None:
        """Remove all EventBus subscriptions created by _wire_events."""
        for event_type, sub_id in self._event_sub_ids:
            try:
                self._event_bus.unsubscribe(event_type, sub_id)
            except Exception:
                logger.debug("EventBus unsubscribe failed for %s", event_type, exc_info=True)
        self._event_sub_ids = []

    def _on_system_event(self, event_type: str, data: dict) -> None:
        logger.debug("System event %s: %s", event_type, data)
        status = self.statusBar()
        if status is None:
            return
        if event_type == "PLAN_CREATED":
            status.showMessage(f"Plan created: {data.get('tasks', 0)} tasks", 3000)
        elif event_type == "WORKFLOW_STARTED":
            status.showMessage(f"Workflow '{data.get('workflow')}' started", 3000)
        elif event_type == "WORKFLOW_STEP":
            status.showMessage(f"Agent: {data.get('agent')}", 3000)
        elif event_type == "WORKFLOW_COMPLETED":
            status.showMessage("Workflow completed", 3000)
        elif event_type == "AGENT_FINISHED":
            status.showMessage("Agent finished", 3000)
        elif event_type == "AGENT_ERROR":
            status.showMessage("Agent error", 5000)
        elif event_type == "AUTOMATION_TASK_COMPLETED":
            status.showMessage(f"Automation: {data.get('task')}", 3000)
            self._refresh_automation_dashboard()
        elif event_type == "AUTOMATION_TASK_UPDATED" or event_type == "AUTOMATION_TASK_DELETED":
            self._refresh_automation_dashboard()
        elif event_type == "PLUGIN_DISCOVERED":
            status.showMessage(f"Plugin discovered: {data.get('plugin_id')}", 3000)
        elif event_type == "PLUGIN_LOAD_START":
            name = data.get("name") or data.get("plugin_id")
            status.showMessage(f"Loading plugin: {name}", 5000)
        elif event_type == "PLUGIN_LOADED":
            status.showMessage(f"Plugin loaded: {data.get('plugin_id')}", 3000)
        elif event_type == "PLUGIN_LOAD_FAILED":
            status.showMessage(f"Plugin invalid: {data.get('plugin_id') or data.get('reason')}", 5000)
        elif event_type == "PLUGIN_ENABLED":
            status.showMessage(f"Plugin enabled: {data.get('plugin_id')}", 3000)
        elif event_type == "PLUGIN_DISABLED":
            status.showMessage(f"Plugin disabled: {data.get('plugin_id')}", 3000)
        elif event_type == "PLUGIN_UNLOADED":
            status.showMessage(f"Plugin unloaded: {data.get('plugin_id')}", 3000)
        elif event_type == "PLUGIN_ERROR":
            status.showMessage(f"Plugin error: {data.get('plugin_id')}", 5000)
        elif event_type == "NAVIGATE_TO_MEMORY":
            status.showMessage("Navigate to Memory section", 2000)
        elif event_type == "NAVIGATE_TO_AGENTS":
            status.showMessage("Navigate to Agents section", 2000)
        elif event_type == "NAVIGATE_TO_TOOLS":
            status.showMessage("Navigate to Tools section", 2000)
        elif event_type == "NAVIGATE_TO_VOICE":
            status.showMessage("Navigate to Voice section", 2000)

    # ------------------------------------------------------------------ #
    def _pulse_event_loop(self) -> None:
        """Pump the Qt event loop without blocking.

        Present for backward compatibility with tests that patch it to
        detect whether processEvents-style pumping is used in the sync path.
        The Phase 4B-2 worker path does not call this.
        """
        QApplication.processEvents()

    def _start_generation(self, text: str, images: list | None = None) -> str:
        """Run process_message with per-generation cancel event and pulse callback.

        Determines whether to use the background QThread worker path (normal
        streaming chat) or the synchronous GUI-thread fallback (native tool
        calling requiring QMessageBox confirmation).

        Slash commands (lines starting with ``/``) are always routed through
        the synchronous GUI-thread path, regardless of incidental keywords in
        their arguments (e.g. ``/agent plan Otvori kalkulator``).  This
        ensures deterministic routing: a slash command never switches between
        sync and worker paths based on tool-keyword heuristics.  It also
        guarantees that all events are published on the GUI thread, preserving
        Qt thread-affinity for subscribers.
        """
        if self._generation_active:
            logger.info(
                "Generation already active — ignoring re-entrant _start_generation(%r)",
                text[:80],
            )
            return ""
        self._generation_active = True
        self._cancel_event = threading.Event()
        self._generation_cancel_event = self._cancel_event
        if hasattr(self._assistant, "_cancel_event"):
            self._assistant._cancel_event = self._cancel_event
        response = ""
        try:
            lowered = text.strip().lower()
            if images:
                # Multimodal path — always the worker (streaming chat);
                # images bypass tool heuristics.
                response = self._start_generation_worker(text, images=images)
            elif lowered.startswith("/"):
                response = self._start_generation_sync(text)
            else:
                needs_tool = self._assistant._message_needs_tool(lowered)
                if needs_tool:
                    response = self._start_generation_sync(text)
                else:
                    response = self._start_generation_worker(text)
        except Exception as exc:
            logger.exception("Generation error")
            self._chat.finish_streaming()
            self._response_displayed = True
            self._status.showMessage(f"Generation error: {exc}", 5000)
        finally:
            self._generation_active = False
            self._generation_cancel_event = None
            if hasattr(self._assistant, "_cancel_event"):
                self._assistant._cancel_event = None
        if not self._response_displayed:
            self._chat.add_message("assistant", response)
        self._current_response = ""
        return response

    def _start_generation_sync(self, text: str) -> str:
        """Synchronous GUI-thread generation path (native tool calling).

        Preserved from the original implementation for paths requiring
        QMessageBox confirmation or other Qt widget calls.
        """
        def pulse() -> None:
            QApplication.processEvents()
        return self._assistant.process_message(
            text,
            cancel_event=self._cancel_event,
            pulse_callback=pulse,
        )

    def _start_generation_worker(self, text: str, images: list | None = None) -> str:
        """Background generation via GenerationWorker(QThread).

        Uses QApplication.processEvents() to pump the event loop while
        waiting for the worker, keeping the return value synchronous
        for callers (including tests).
        """
        assert self._cancel_event is not None
        worker = GenerationWorker(
            self._assistant, text, self._cancel_event, images
        )
        self._generation_worker = worker

        worker.token_emitted.connect(self._on_worker_token, Qt.ConnectionType.QueuedConnection)
        worker.generation_cancelled.connect(self._on_worker_cancelled, Qt.ConnectionType.QueuedConnection)
        worker.generation_failed.connect(self._on_worker_failed, Qt.ConnectionType.QueuedConnection)

        done = threading.Event()
        result_holder: list = [None]

        def _on_finished(response: str) -> None:
            result_holder[0] = ("finished", response)
            done.set()

        def _on_cancelled() -> None:
            result_holder[0] = ("cancelled", "")
            done.set()

        def _on_failed(error: str) -> None:
            result_holder[0] = ("failed", error)
            done.set()

        worker.generation_finished.connect(_on_finished, Qt.ConnectionType.DirectConnection)
        worker.generation_cancelled.connect(_on_cancelled, Qt.ConnectionType.DirectConnection)
        worker.generation_failed.connect(_on_failed, Qt.ConnectionType.DirectConnection)

        worker.start()
        # Wait for the worker to finish, processing Qt events so queued
        # signal slots (GUI-thread handlers) are delivered.
        while not done.is_set():
            QApplication.processEvents()
        worker.wait()
        QApplication.processEvents()

        self._generation_worker = None
        if result_holder[0] is not None:
            kind, payload = result_holder[0]
            if kind == "finished":
                self._on_worker_finished(payload)
                return payload
            elif kind in ("cancelled", "failed"):
                return ""
        return ""

    def _on_worker_token(self, token: str) -> None:
        """GUI-thread slot: publishes GENERATION_TOKEN and updates chat UI."""
        if not self._chat.is_streaming():
            self._current_response = ""
            self._tokens_streamed = False
            self._chat.start_streaming()
        self._event_bus.publish("GENERATION_TOKEN", data={"token": token})

    def _on_worker_finished(self, response: str) -> None:
        """GUI-thread slot: publishes GENERATION_COMPLETED and AI_RESPONSE_RECEIVED."""
        cid = f"conv-{datetime.now(UTC).isoformat()}"
        model_name = self._assistant._engine.model_name if self._assistant._engine else "stub"
        self._event_bus.publish(
            "GENERATION_COMPLETED",
            data={"tokens_used": len(response), "response_length": len(response)},
        )
        self._event_bus.publish(
            "AI_RESPONSE_RECEIVED",
            data={
                "text": response,
                "conversation_id": cid,
                "model": model_name,
            },
        )

    def _on_worker_cancelled(self) -> None:
        """GUI-thread slot: publishes GENERATION_CANCELLED, preserves partial response."""
        self._event_bus.publish(
            "GENERATION_CANCELLED",
            data={"tokens_generated": len(self._current_response)},
        )

    def _on_worker_failed(self, error: str) -> None:
        """GUI-thread slot: publishes GENERATION_FAILED."""
        self._event_bus.publish(
            "GENERATION_FAILED", data={"error": error}
        )

    def _on_send(self, text: str) -> str:
        self._current_response = ""
        self._response_displayed = False
        self._tokens_streamed = False
        return self._start_generation(text)

    def _on_send_with_images(self, text: str, images: list) -> None:
        """Multimodal send — images forwarded to Assistant.process_message."""
        self._current_response = ""
        self._response_displayed = False
        self._tokens_streamed = False
        self._start_generation(text, images=images)

    def _sync_vision_availability(self) -> None:
        """Enable/disable the chat Vision button from the active model."""
        engine = getattr(self._assistant, "_engine", None)
        available = bool(getattr(engine, "supports_vision", False)) if engine else False
        try:
            self._chat.set_vision_available(available)
        except Exception:
            logger.debug("set_vision_available failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Voice input (Phase 7)
    # ------------------------------------------------------------------ #
    def _on_voice_input(self) -> None:
        if self._voice is None:
            return
        # Delegate to the VoiceManager lifecycle (REC/STOP/PROCESSING).
        self._voice.handle_mic_click()
        self._sync_voice_ui()

    def _on_voice_transcript(self, event_type: str, data: dict) -> None:
        """Handle a VOICE_TRANSCRIPT event by generating a response.

        Guards against re-entrant generation: if a generation is already
        active, the transcript is discarded to prevent a second
        GenerationWorker from corrupting shared state.
        Guards against events firing on a hidden or closing window.
        """
        if self._generation_active:
            logger.info(
                "Voice transcript received while generation is active — deferring (%d chars)",
                len(str(data.get("text", "")).strip()),
            )
            return
        if self.isHidden():
            logger.debug("Voice transcript received on hidden window — discarding")
            return
        text = str(data.get("text", ""))
        self._chat.add_message("user", text)
        self._current_response = ""
        self._response_displayed = False
        self._tokens_streamed = False
        self._start_generation(text)

    # ------------------------------------------------------------------ #
    # Phase 2C REC/STOP/PROCESSING lifecycle UI sync
    # ------------------------------------------------------------------ #
    def _sync_voice_ui(self) -> None:
        """Push VoiceManager state -> ChatWidget buttons (immediate repaint)."""
        if self._voice is None:
            return
        self._chat.set_voice_state(self._voice.state.value)
        self._chat.set_play_available(bool(self._voice.last_recording_path))

    def _on_voice_lifecycle(self, event_type: str, data: dict) -> None:
        """Voice-session lifecycle events drive the mic button label.

        ``VOICE_INPUT_START`` -> STOP (recording). ``VOICE_INPUT_END`` -> REC
        (session ended). PROCESSING is entered immediately from the STOP click
        (see ``_on_voice_input``); playback availability tracks retained audio.
        """
        if self._voice is None:
            return
        if event_type == "VOICE_INPUT_START":
            self._chat.set_voice_state("recording")
        elif event_type == "VOICE_INPUT_END":
            self._chat.set_voice_state("idle")
        elif event_type == "WAKE_WORD_DETECTED":
            self._on_voice_input()
        self._chat.set_play_available(bool(self._voice.last_recording_path))

    def _on_voice_error(self, event_type: str, data: dict) -> None:
        if self._voice is None:
            return
        message = str(data.get("error", "voice error"))
        self._chat.set_voice_state("error", message)
        self._chat.set_play_available(bool(self._voice.last_recording_path))
        status = self.statusBar()
        if status is not None:
            status.showMessage(f"Voice: {message}", 5000)

    def _on_play_recording(self) -> None:
        if self._voice is None:
            return
        self._voice.play_last_recording()

    def _on_voice_play_start(self, event_type: str, data: dict) -> None:
        logger.debug("Voice playback starting")
        if self._voice is not None:
            self._chat.set_voice_state("speaking")

    def _on_voice_play_done(self, event_type: str, data: dict) -> None:
        logger.debug("Voice playback finished")
        if self._voice is not None:
            self._chat.set_voice_state("idle")
            self._chat.set_play_available(bool(self._voice.last_recording_path))

    def _request_permission(self, tool_name: str, tool_desc: str) -> bool:
        """Modal confirmation dialog for risky tool actions.

        Uses :func:`QMetaObject.invokeMethod` with ``BlockingQueuedConnection``
        so the :class:`~PySide6.QtWidgets.QMessageBox` is created on the main
        (GUI) thread even when this callback is invoked from a worker
        ``QThread`` (e.g. :class:`AgentRunWorker`).  Without this the dialog
        would be constructed on the worker thread — a Qt threading violation
        that can cause deadlocks or undefined behaviour.

        Checks ``_agent_cancel_event`` before blocking so that cooperative
        cancellation or shutdown can proceed without deadlocking.
        """
        if self._agent_cancel_event is not None and self._agent_cancel_event.is_set():
            return False
        self._event_bus.publish(
            "ASK_FOR_PERMISSION",
            data={"tool": tool_name, "description": tool_desc},
        )
        self._permission_result = None
        QMetaObject.invokeMethod(
            self,
            "_show_permission_dialog",
            Qt.ConnectionType.BlockingQueuedConnection,
            Q_ARG(str, tool_name),
            Q_ARG(str, tool_desc),
        )
        approved = (
            self._permission_result == QMessageBox.StandardButton.Yes
            if self._permission_result is not None
            else False
        )
        self._event_bus.publish(
            "PERMISSION_RESPONSE",
            data={"tool": tool_name, "approved": approved},
        )
        return approved

    @Slot(str, str)
    def _show_permission_dialog(self, tool_name: str, tool_desc: str) -> None:
        """Show the permission dialog — always runs on the GUI thread."""
        if self._agent_cancel_event is not None and self._agent_cancel_event.is_set():
            self._permission_result = QMessageBox.StandardButton.No
            return
        msg = (
            f"AI wants to perform an action:\n\n"
            f"  Tool: {tool_name}\n"
            f"  Description: {tool_desc}\n\n"
            f"Allow?"
        )
        self._permission_result = QMessageBox.question(
            self,
            "Action confirmation",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

    def _on_ai_response(self, event_type: str, data: dict) -> None:
        model = data.get("model", self._assistant.model_name)
        self._status.set_model(model)
        text = data.get("text", "")
        if text and not self._tokens_streamed:
            # Non-streaming generation (native tool calling / error / stub)
            # delivers the final response as a complete string via this event.
            # When tokens already streamed a bubble, skip to avoid duplicates.
            self._chat.add_message("assistant", text)
        if text.strip() and self._voice is not None and self._config.get("voice.enabled", True):
            self._voice.speak(text)
        self._current_response = ""
        self._tokens_streamed = False
        self._response_displayed = True

    def _on_generation_started(self, event_type: str, data: dict) -> None:
        self._current_response = ""
        self._tokens_streamed = False
        self._chat.start_streaming()

    def _on_generation_token(self, event_type: str, data: dict) -> None:
        token = data.get("token", "")
        if token:
            self._current_response += token
            self._tokens_streamed = True
            self._chat.append_streaming_token(token)

    def _on_generation_completed(self, event_type: str, data: dict) -> None:
        self._chat.finish_streaming()
        self._current_response = ""
        self._response_displayed = True

    def _on_generation_cancelled(self, event_type: str, data: dict) -> None:
        """Handle generation cancellation — finish streaming and preserve partial response."""
        self._chat.finish_streaming()
        self._tokens_streamed = False
        self._response_displayed = True

    def _on_generation_failed(self, event_type: str, data: dict) -> None:
        error = data.get("error", "Unknown error")
        self._chat.finish_streaming()
        self._response_displayed = True
        self._status.showMessage(f"Generation error: {error}", 5000)
        self._current_response = ""

    def _on_config_changed(self, event_type: str, data: dict) -> None:
        key = data.get("key", "")
        if key == "ui.theme":
            self._theme.apply(data.get("value", "dark"))
        elif key == "ai.models_dir":
            models_dir = data.get("value")
            mm = getattr(self._assistant, "model_manager", None)
            if models_dir and mm is not None:
                from pathlib import Path

                mm.set_models_dir(Path(models_dir))
                engine = getattr(self._assistant, "_engine", None)
                if engine is not None and hasattr(engine, "configure"):
                    try:
                        engine.configure(mm)
                    except Exception as exc:
                        logger.warning("Engine reconfiguration after models_dir change failed: %s", exc)
                        if hasattr(self, "_models_page"):
                            self._models_page.set_model_manager(mm)
                            self._models_page._on_refresh()
        elif key in (
            "ai.max_tokens", "ai.temperature", "ai.top_p", "ai.top_k",
            "ai.min_p", "ai.repeat_penalty",
        ):
            logger.info("Generation setting changed: %s = %s", key, data.get("value"))
        elif key in (
            "memory.enabled",
            "memory.short_term_window",
            "memory.max_context_memories",
            "memory.embedding_model",
        ):
            logger.info("Memory setting changed: %s = %s", key, data.get("value"))
            self._status.showMessage("Memory settings updated", 2000)
            if key == "memory.embedding_model":
                logger.warning(
                    "memory.embedding_model changed — restart required for new backend to take effect"
                )

    def _on_model_loaded(self, event_type: str, data: dict) -> None:
        model_name = data.get("model", "unknown")
        self._status.set_model(model_name)
        self._status.set_model_status_text(f"Model: {model_name} (ready)")
        self._populate_model_combo()
        self._model_combo.setCurrentText(model_name)
        if hasattr(self, "_models_page"):
            from ai.models.model_loader import ModelStatus
            self._models_page.set_model_status(ModelStatus.MODEL_AVAILABLE, model_name)
        self._status.showMessage(f"Model loaded: {model_name}", 3000)

        if hasattr(self, "_capabilities_page"):
            self._capabilities_page.refresh()

        self._sync_vision_availability()

    def _on_model_unloaded(self, event_type: str, data: dict) -> None:
        """React to MODEL_UNLOADED — clear main window model indicators."""
        self._status.set_model("")
        self._status.set_model_status_text("Model: none")
        self._populate_model_combo()
        if hasattr(self, "_models_page"):
            from ai.models.model_loader import ModelStatus
            self._models_page.set_model_status(ModelStatus.NO_MODEL_AVAILABLE)
        self._status.showMessage("Model unloaded", 3000)

        if hasattr(self, "_capabilities_page"):
            self._capabilities_page.refresh()

        self._sync_vision_availability()

    def _populate_model_combo(self) -> None:
        """Populate _model_combo with all available chat-compatible models.

        The currently active model is selected.  When no model is active the
        combo lists available models so the user can pick one to load.  When
        no chat-compatible models exist at all, the combo shows a single
        "No model active" placeholder.

        Signal blocking prevents _on_model_changed from firing during
        programmatic rebuilds (no recursive switch attempts).
        """
        mm = getattr(self._assistant, "model_manager", None)

        self._model_combo.blockSignals(True)
        try:
            self._model_combo.clear()

            if not isinstance(mm, ModelManager):
                self._model_combo.addItem(self._assistant.model_name)
                return

            models = mm.list_models()
            active = mm.get_active_model()
            active_name = active.name if active else None

            chat_models = [
                m for m in models
                if m.model_type.is_chat_compatible
                or (_is_test_mode() and m.model_type == ModelType.UNKNOWN)
            ]

            if not chat_models:
                if active_name:
                    self._model_combo.addItem(active_name)
                else:
                    self._model_combo.addItem("No model active")
            else:
                for m in chat_models:
                    self._model_combo.addItem(m.name)

                if active_name:
                    idx = self._model_combo.findText(active_name)
                    if idx >= 0:
                        self._model_combo.setCurrentIndex(idx)
        finally:
            self._model_combo.blockSignals(False)

    def _on_model_load_failed(self, event_type: str, data: dict) -> None:
        error = data.get("error", "Unknown error")
        self._status.set_model_status_text(f"Model load failed: {error}")
        QMessageBox.critical(
            self,
            "Model Load Failed",
            f"Model could not be loaded.\n\nError: {error}\n\n"
            "Ensure llama-cpp-python is installed: pip install llama-cpp-python",
        )

    def _on_api_engine_active(self, event_type: str, data: dict) -> None:
        """Online API engine is serving a turn — surface it in the chat UI."""
        model = str(data.get("model", "online model"))
        self._chat.set_online_active(True)
        self._status.showMessage(f"Online model active: {model}", 4000)

    def _install_shortcuts(self) -> None:
        shortcut_new = QShortcut("Ctrl+N", self)
        shortcut_new.activated.connect(self._focus_chat_input)

        shortcut_settings = QShortcut("Ctrl+,", self)
        shortcut_settings.activated.connect(self.open_settings)

        shortcut_quit = QShortcut("Ctrl+Q", self)
        shortcut_quit.activated.connect(self._on_tray_quit)

        shortcut_voice = QShortcut("Ctrl+/", self)
        shortcut_voice.activated.connect(self._toggle_voice)

    def _apply_accessibility(self) -> None:
        self._sidebar.setAccessibleName("Main navigation sidebar")
        self._chat._input.setAccessibleName("Chat message input")
        self._chat._send_btn.setAccessibleName("Send message")
        self._chat._voice_btn.setAccessibleName("Voice input toggle")
        self._status.setAccessibleName("Application status bar")

    def _apply_polish(self) -> None:
        self._sidebar.setStyleSheet(
            "QListWidget { border: none; background: #111516; }"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:hover { background: #1C2221; }"
            "QListWidget::item:selected { background: #1D8A68; color: #EDF3F0; }"
        )
        self._chat._send_btn.setMinimumWidth(80)
        self._chat._voice_btn.setMinimumWidth(80)
        self._chat._send_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; border-radius: 6px; }"
            "QPushButton { background: #1D8A68; color: #EDF3F0; border: none; }"
            "QPushButton:hover { background: #249E78; }"
            "QPushButton:pressed { background: #245846; }"
        )

    def _focus_chat_input(self) -> None:
        self._chat._input.setFocus()
        self._chat._input.selectAll()

    def _toggle_voice(self) -> None:
        if self._voice is not None:
            self._on_voice_input()

    def closeEvent(self, event: Any) -> None:
        if self._generation_active and hasattr(self._assistant, "request_cancel"):
            self._assistant.request_cancel()
        if self._generation_worker is not None:
            gen_worker = self._generation_worker
            gen_worker.wait(5000)
            if gen_worker.isRunning():
                gen_worker.terminate()
                gen_worker.wait(1000)
            try:
                gen_worker.token_emitted.disconnect()
                gen_worker.generation_cancelled.disconnect()
                gen_worker.generation_failed.disconnect()
                gen_worker.generation_finished.disconnect()
            except Exception:
                logger.debug("generation worker signal disconnect failed", exc_info=True)
        if self._agent_worker is not None:
            # NEXT-D-81: Cooperative shutdown — signal cancellation first.
            if self._agent_cancel_event is not None:
                self._agent_cancel_event.set()
            # If the worker is blocked inside BlockingQueuedConnection
            # waiting for a permission dialog, pre-set the result so the
            # invokeMethod call can return and the worker can observe the
            # cancel_event.
            if self._agent_worker.isRunning() and self._permission_result is None:
                self._permission_result = QMessageBox.StandardButton.No
            try:
                self._agent_worker.finished.disconnect()
            except Exception:
                logger.debug("agent worker signal disconnect failed", exc_info=True)
            try:
                self._agent_worker.agent_event.disconnect()
            except Exception:
                logger.debug("agent worker event signal disconnect failed", exc_info=True)
            # Poll with processEvents instead of a single blocking wait(5000)
            # to keep the GUI thread responsive so pending invokeMethod events
            # (permission dialogs) can be drained and the worker can exit.
            deadline = time.monotonic() + 5
            while (
                self._agent_worker.isRunning()
                and not self._agent_worker.isFinished()
                and time.monotonic() < deadline
            ):
                QApplication.processEvents()
                self._agent_worker.wait(100)
            if self._agent_worker.isRunning():
                logger.warning(
                    "Agent worker did not finish within 5s after cancel — "
                    "using emergency termination"
                )
                self._agent_worker.terminate()
                self._agent_worker.wait(1000)
            self._agent_worker = None
            self._agent_active = False
            self._agent_cancel_event = None
        self._chat.finish_streaming()
        if self._tray is not None and self._tray._tray.isVisible():
            if self._voice is not None:
                try:
                    self._voice.stop()
                except Exception:
                    logger.debug("voice stop during hide-to-tray failed", exc_info=True)
            self.hide()
            event.ignore()
        else:
            self._unsubscribe_all_events()
            if self._voice is not None:
                try:
                    self._voice.stop()
                except Exception:
                    logger.debug("voice stop during close failed", exc_info=True)
            event.accept()

    def _on_tray_quit(self) -> None:
        self._tray.close_tray()
        self.close()

    def _on_plugin_event(self, event_type: str, data: dict) -> None:
        if self._tray is None:
            return
        plugin_id = data.get("plugin_id", "")
        if event_type == "PLUGIN_ENABLED":
            self._tray.show_notification("Plugin enabled", f"Plugin '{plugin_id}' is now enabled.")
        elif event_type == "PLUGIN_DISABLED":
            self._tray.show_notification("Plugin disabled", f"Plugin '{plugin_id}' is now disabled.")
        elif event_type == "PLUGIN_ERROR":
            reason = data.get("reason", "unknown error")
            self._tray.show_notification("Plugin error", f"Plugin '{plugin_id}' error: {reason}")

    def _on_home(self) -> None:
        self._router.navigate("home")

    def _on_new_chat(self) -> None:
        self._on_new_chat_requested()

    def _on_new_chat_requested(self) -> None:
        self._chat.clear()
        self._event_bus.publish("NEW_CHAT_REQUESTED", data={})
        self._refresh_conversation_sidebar()

    def _on_search_memory_requested(self, query: str) -> None:
        self._event_bus.publish("MEMORY_SEARCH_REQUESTED", data={"query": query})
        memory_page = getattr(self, "_memory_page", None)
        router = getattr(self, "_router", None)
        if memory_page is not None and router is not None:
            memory_page._search.setText(query)
            router.navigate("memory")
            memory_page.refresh_memories(query)
            count = len(memory_page._cards)
            self._status.showMessage(
                f"Found {count} memor{'y' if count == 1 else 'ies'} matching: {query}",
                3000,
            )
        else:
            self._status.showMessage(f"Searching memory for: {query}", 3000)

    def _on_stop_generation(self) -> None:
        """Handle stop request from ChatWidget.

        Sets the cancellation event so the generation loop exits
        cooperatively at the next token boundary.  Also signals any active
        agent run to stop at the next safe checkpoint (NEXT-D-67).
        """
        if hasattr(self._assistant, "request_cancel"):
            self._assistant.request_cancel()
        if self._agent_cancel_event is not None:
            self._agent_cancel_event.set()

    # ------------------------------------------------------------------ #
    # Conversation sidebar handlers
    # ------------------------------------------------------------------ #
    def _on_conversation_selected(self, conv_id: int) -> None:
        """Load conversation from storage and display in chat."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is None:
            return
        conv_data = memory.get_conversation(conv_id)
        if conv_data is None:
            return
        memory.select_conversation(conv_id)
        memory.load_conversation_into_stm(conv_id)
        messages = memory.get_messages(conv_id)
        self._chat.clear()
        for msg in messages:
            role = msg.role
            content = msg.content
            self._chat.add_message(role, content)
        self._conversation_sidebar.set_conversations(memory.list_conversations())

    def _on_delete_conversation(self, conv_id: int) -> None:
        """Delete a conversation."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is None:
            return
        reply = QMessageBox.question(
            self,
            "Delete Conversation",
            f"Delete conversation {conv_id}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            memory.delete_conversation(conv_id)
            self._conversation_sidebar.set_conversations(memory.list_conversations())

    def _on_message_deleted(self, message_id: int) -> None:
        """Delete a single message from the database per UI context-menu request."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is None:
            return
        memory.delete_message(message_id)

    def _on_rename_conversation(self, conv_id: int, new_title: str) -> None:
        """Rename a conversation."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is None:
            return
        if not new_title.strip():
            from PySide6.QtWidgets import QInputDialog
            new_title, ok = QInputDialog.getText(self, "Rename Conversation", "New title:")
            if not ok or not new_title.strip():
                return
        memory.rename_conversation(conv_id, new_title.strip())
        self._conversation_sidebar.set_conversations(memory.list_conversations())

    def _on_pin_conversation(self, conv_id: int, pinned: bool) -> None:
        """Pin or unpin a conversation."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is None:
            return
        memory.pin_conversation(conv_id, pinned)
        self._conversation_sidebar.set_conversations(memory.list_conversations())

    def _refresh_conversation_sidebar(self) -> None:
        """Update the conversation sidebar with the current list."""
        memory = getattr(self._assistant, "_memory", None)
        if memory is not None:
            self._conversation_sidebar.set_conversations(memory.list_conversations())

    def _on_export_chat(self) -> None:
        text = self._chat.export_conversation()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Conversation",
            "conversation.txt",
            "Text Files (*.txt);;Markdown Files (*.md);;JSON Files (*.json)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self._status.showMessage(f"Exported to {path}", 3000)

    def _on_search_memory(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        query, ok = QInputDialog.getText(self, "Search Memory", "Enter search query:")
        if not ok or not query.strip():
            return
        self._event_bus.publish("MEMORY_SEARCH_REQUESTED", data={"query": query})
        self._status.showMessage(f"Searching memory for: {query}", 3000)

    def _on_model_changed(self, model_name: str) -> None:
        if not model_name or model_name == "No model active":
            return
        current = self._assistant.model_name
        if model_name == current or current.startswith(model_name + " ["):
            return
        try:
            self._assistant.switch_model(model_name)
            self._status.showMessage(f"Switched to model: {model_name}", 3000)
        except Exception as exc:
            logger.error("Model switch failed: %s", exc)
            QMessageBox.critical(
                self,
                "Model Switch Failed",
                f"Could not switch to model '{model_name}'.\n\nError: {exc}\n\n"
                "Ensure llama-cpp-python is installed: pip install llama-cpp-python",
            )
            self._status.showMessage(f"Model switch failed: {exc}", 5000)
            self._populate_model_combo()

    def _navigate_and_refresh(self, route: str) -> None:
        """Canonical navigation + refresh dispatch.

        Called by both sidebar selection (``_on_sidebar_item_changed``)
        and quick-action navigation (via ``AssistantHub``) so that every
        route change flows through a single orchestration point.  This
        guarantees that the router, sidebar selection, and page-specific
        refresh all stay in sync regardless of how navigation was
        triggered.
        """
        if route == "settings":
            self._sync_sidebar_to_route(route)
            self.open_settings()
            return
        self._router.navigate(route)
        self._sync_sidebar_to_route(route)
        if route == "automation":
            self._refresh_automation_dashboard()
        elif route == "knowledge":
            self._refresh_knowledge_dashboard()
        elif route == "models":
            self._refresh_models_page()
        elif route == "memory":
            self._refresh_memory_page()
        elif route == "agents":
            self._refresh_agents_page()
        elif route == "projects":
            self._projects_page.refresh()
        elif route == "workflow":
            self._workflow_builder._refresh_workflow_list()

    def _sync_sidebar_to_route(self, route: str) -> None:
        """Select the sidebar item matching *route* without re-triggering navigation."""
        for i in range(self._sidebar.count()):
            item = self._sidebar.item(i)
            if item is not None and item.data(1000) == route:
                self._sidebar.blockSignals(True)
                try:
                    self._sidebar.setCurrentRow(i)
                finally:
                    self._sidebar.blockSignals(False)
                break

    def _on_sidebar_item_changed(self, current, previous) -> None:
        if current is None:
            return
        key = current.data(1000)
        self._navigate_and_refresh(key)

    def _refresh_automation_dashboard(self) -> None:
        if self._automation_manager is not None:
            self._automation_dashboard.set_workflows({name: self._automation_manager._workflows[name] for name in self._automation_manager.list_workflows()})
            self._automation_dashboard.set_tasks(self._automation_manager.scheduler.tasks)
            self._automation_dashboard.set_history(self._automation_manager.task_history)

    def _on_open_automation(self) -> None:
        self._stack.setCurrentWidget(self._automation_dashboard)
        self._refresh_automation_dashboard()

    def _on_run_workflow(self, name: str) -> None:
        if self._automation_manager is not None:
            result = self._automation_manager.run_workflow(name)
            self._status.showMessage(result, 5000)
            self._refresh_automation_dashboard()

    def _on_task_editor(self, task_name: str | None) -> None:
        if self._automation_manager is None:
            return
        task = None
        if task_name is not None:
            task = self._automation_manager.get_task(task_name)

        workflow_names = self._automation_manager.list_workflows()
        registry = self._automation_manager._registry
        tool_names = registry.list_all_tool_names() if registry else []

        dialog = TaskEditorDialog(
            parent=self, task=task,
            workflow_names=workflow_names, tool_names=tool_names,
        )
        if dialog.exec() == dialog.DialogCode.Accepted:
            saved_task = dialog.get_task()
            if saved_task is not None:
                if task_name is not None:
                    self._automation_manager.update_task(saved_task)
                else:
                    self._automation_manager.register_task(saved_task)
                self._save_scheduled_tasks()
                self._refresh_automation_dashboard()
                self._status.showMessage(f"Task '{saved_task.name}' saved", 3000)

    def _on_delete_scheduled_task(self, name: str) -> None:
        if self._automation_manager is None:
            return
        self._automation_manager.unregister_task(name)
        self._save_scheduled_tasks()
        self._refresh_automation_dashboard()
        self._status.showMessage(f"Task '{name}' deleted", 3000)

    def _on_run_scheduled_task(self, name: str) -> None:
        if self._automation_manager is None:
            return
        # GUI Run Now path: submit through the AutomationDispatcher so the
        # actual task/tool/workflow execution happens on an
        # AutomationTaskWorker — never synchronously on the GUI thread.
        # Completion (status bar + dashboard refresh) arrives asynchronously
        # via the dispatcher's task_finalized signal.
        dispatcher = self._automation_dispatcher
        if dispatcher is not None:
            task = self._automation_manager.get_task(name)
            if task is None:
                self._status.showMessage(f"Task '{name}' not found", 5000)
                return
            if not task.enabled:
                self._status.showMessage(f"Task '{name}' is disabled", 5000)
                return
            submitted = dispatcher.run_now(name)
            if submitted:
                self._status.showMessage(f"Task '{name}' started…", 3000)
            elif dispatcher.is_in_flight(name):
                self._status.showMessage(
                    f"Task '{name}' is already running", 5000
                )
            return
        # Fallback (no dispatcher wired — e.g. legacy/test constructions):
        # keep the historical synchronous behaviour.
        result = self._automation_manager.run_task_now(name)
        self._status.showMessage(f"Task '{name}': {result.message}", 5000)
        self._refresh_automation_dashboard()

    def _on_run_now_finalized(self, task_name: str, success: bool) -> None:
        """GUI-thread slot: a dispatcher-executed task finished (Run Now).

        Shows the outcome on the status bar and refreshes the automation
        dashboard.  Never blocks — connected to the dispatcher's
        ``task_finalized`` signal which is emitted on the GUI thread after
        state finalization.
        """
        task = (
            self._automation_manager.get_task(task_name)
            if self._automation_manager is not None
            else None
        )
        outcome = (
            task.result
            if task is not None and task.result
            else ("done" if success else "failed")
        )
        self._status.showMessage(f"Task '{task_name}': {outcome}", 5000)
        self._refresh_automation_dashboard()

    def _on_task_enabled_changed(self, name: str, enabled: bool) -> None:
        from automation.task import TaskStatus

        if self._automation_manager is None:
            return
        task = self._automation_manager.get_task(name)
        if task is None:
            return
        task.enabled = enabled
        if not enabled:
            task.status = TaskStatus.DISABLED
        else:
            task.status = TaskStatus.PENDING
            from datetime import datetime
            task.next_run = datetime.now()  # noqa: DTZ005
        self._save_scheduled_tasks()
        self._refresh_automation_dashboard()

    def _save_scheduled_tasks(self) -> None:
        if self._automation_manager is None or self._config is None:
            return
        try:
            tasks_file = self._config.get("automation.tasks_file", "tasks.json")
            persist_dir = Path(self._config.get("automation.persist_dir", str(DATA_DIR)))
            tasks_path = persist_dir / tasks_file
            self._automation_manager.save_tasks(tasks_path)
        except Exception:
            logger.warning("Failed to persist scheduled tasks", exc_info=True)

    def _refresh_knowledge_dashboard(self) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        self._knowledge_dashboard.set_documents(knowledge._documents)
        self._knowledge_dashboard.set_statistics(knowledge.get_statistics())

    def _on_knowledge_search(self, query: str) -> None:
        """Handle knowledge search request from KnowledgeDashboard."""
        context, results = self._assistant.run_knowledge_search(query)
        self._knowledge_dashboard.display_search_results(context, results)
        self._status.showMessage(f"Searched knowledge: {query}", 3000)

    def _refresh_models_page(self) -> None:
        model_manager = getattr(self._assistant, "model_manager", None)
        if model_manager is None:
            return
        model_manager.rescan()
        self._models_page.set_models(model_manager.list_models())
        self._models_page.set_active_model(self._assistant.model_name)

    def _refresh_memory_page(self) -> None:
        self._memory_page.refresh_memories(self._memory_page._search.text())
        self._refresh_conversation_sidebar()

    def _refresh_agents_page(self) -> None:
        self._agents_page.refresh()

    def _on_project_opened(self, project_id: str, project_name: str) -> None:
        self._status.showMessage(f"Opened project: {project_name}", 3000)
        self._update_chat_context()
        self._router.navigate("chat")
        self._sidebar.setCurrentRow(1)
        self._refresh_conversation_sidebar()

    def _on_project_created(self, project_id: str) -> None:
        self._status.showMessage("Project created", 2000)

    def _on_project_updated(self, project_id: str) -> None:
        self._status.showMessage("Project updated", 2000)
        self._update_chat_context()

    def _on_project_deleted(self, project_id: str) -> None:
        self._status.showMessage("Project deleted", 2000)
        self._update_chat_context()

    def _on_assign_agent(self, project_id: str, agent_name: str) -> None:
        agent_repo = getattr(self._assistant, "_agent_repository", None)
        if agent_repo is None:
            self._status.showMessage("Agent repository not available", 3000)
            return
        agent = agent_repo.get_agent_by_name(agent_name)
        if agent is None or agent.id is None:
            self._status.showMessage(f"Agent '{agent_name}' not found", 3000)
            return
        self._assistant.assign_agent_to_project(project_id, agent.id, agent.name)
        self._status.showMessage(f"Agent '{agent_name}' assigned to project", 3000)

    def _on_run_agent(self, project_id: str, goal: str) -> None:
        if self._agent_active:
            return
        self._agent_active = True
        self._agent_cancel_event = threading.Event()
        worker = AgentRunWorker(
            self._assistant, goal, project_id, self._agent_cancel_event
        )
        self._agent_worker = worker
        worker.finished.connect(self._on_agent_finished, Qt.ConnectionType.QueuedConnection)
        worker.agent_event.connect(self._on_agent_event, Qt.ConnectionType.QueuedConnection)
        worker.start()

    def _on_agent_event(self, event_type: str, data: dict) -> None:
        """GUI-thread slot: receives agent lifecycle events from the worker
        thread via the ``agent_event`` signal and publishes them on the
        EventBus from the main thread (NEXT-D-66)."""
        self._event_bus.publish(event_type, data=data)

    def _on_agent_finished(self, result: str, error: str) -> None:
        self._agent_active = False
        self._agent_worker = None
        self._agent_cancel_event = None
        if hasattr(self._assistant, "_cancel_event"):
            self._assistant._cancel_event = None
        if error:
            logger.error("Agent run failed: %s", error)
            QMessageBox.critical(self, "Agent Error", f"Agent execution failed:\n{error}")
        else:
            self._chat.add_message("system", f"Agent completed: {result[:200]}")
            self._status.showMessage("Agent run completed", 5000)

    def _update_chat_context(self) -> None:
        ctx = self._assistant.get_project_context()
        if ctx is not None:
            self._chat.set_project_context(ctx.name, ctx.project_id)
            project_label = f" [{ctx.name}]"
            base_placeholder = "Enter message..."
            if not self._chat._input.placeholderText().startswith(base_placeholder):
                self._chat.set_input_placeholder(base_placeholder + project_label)
            else:
                if project_label not in self._chat._input.placeholderText():
                    self._chat.set_input_placeholder(base_placeholder + project_label)
        else:
            self._chat.clear_project_context()
            self._chat.set_input_placeholder("Enter message...")

        if self._assistant.get_active_project_id() is not None:
            self._chat.add_message(
                "system",
                "Project context is active. You can discuss this project with the model.",
            )

    def _on_knowledge_index(self, directory: str) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        total = knowledge.index_directory(directory)
        self._status.showMessage(f"Indexed {total} chunks from {directory}", 5000)
        self._refresh_knowledge_dashboard()

    def _on_knowledge_index_file(self, file_path: str) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        total = knowledge.index_document(file_path)
        self._status.showMessage(f"Indexed {total} chunks from {file_path}", 5000)
        self._refresh_knowledge_dashboard()

    def _on_knowledge_rebuild(self, directory: str) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        total = knowledge.rebuild(directory)
        self._status.showMessage(f"Rebuilt {total} chunks from {directory}", 5000)
        self._refresh_knowledge_dashboard()

    def _on_knowledge_delete(self, doc_id: str) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        if not doc_id:
            return
        deleted = knowledge.delete_document(doc_id)
        if deleted:
            self._refresh_knowledge_dashboard()
            self._status.showMessage("Document deleted", 3000)
        else:
            self._status.showMessage("Document not found", 3000)

    def _on_knowledge_export(self) -> None:
        knowledge = getattr(self._assistant, "knowledge", None)
        if knowledge is None:
            return
        data = knowledge.export_to_dict()
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Knowledge Base",
            "knowledge_export.json",
            "JSON Files (*.json);;Markdown Files (*.md)",
        )
        if path:
            if path.endswith(".md"):
                content = knowledge.export_to_markdown()
            else:
                import json
                content = json.dumps(data, ensure_ascii=False, indent=2)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._status.showMessage(f"Knowledge exported to {path}", 3000)

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._config,
            self._event_bus,
            self._assistant,
            self._plugin_manager,
            getattr(self._assistant, "model_manager", None),
            self,
            voice_manager=self._voice,
        )
        dialog.profile_updated.connect(self._on_profile_updated)
        dialog.exec()

    def _on_profile_updated(self, profile: dict) -> None:
        logger.info("Assistant profile updated: %s", profile.get("identity", {}).get("name"))
        self._refresh_profile_ui()

    def _on_profile_updated_event(self, event_type: str, data: dict) -> None:
        """EventBus adapter: PROFILE_UPDATED → _on_profile_updated."""
        self._on_profile_updated(data)

    def _refresh_profile_ui(self) -> None:
        """Refresh all UI components that depend on the assistant profile."""
        if self._assistant_hub is not None:
            self._assistant_hub.refresh()
        if self._status is not None:
            name = getattr(self._assistant, "model_name", None) or "stub"
            self._status.set_model(name)
        if self._models_page is not None:
            self._models_page._on_refresh()

    @staticmethod
    def _create_placeholder_page(title: str, message: str = "Coming soon") -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"<h2>{title}</h2><p>{message}</p>")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return page
