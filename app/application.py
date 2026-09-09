"""Application manager — full lifecycle bootstrap for Phase 13.

Wires together every component:
    ConfigManager → EventBus → Router → ModelManager → LLMEngine
      → MemoryManager → ToolRegistry → Assistant → ThemeManager → MainWindow
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from agent.orchestrator import AgentOrchestrator
from agent.planner import LLMPlanner, Planner, StubPlanner
from agent.repository import AgentRepository
from ai.engine.llm_engine import LlamaCppEngine, LLMEngine
from ai.models.model_loader import ModelStatus, get_model_status, has_llama_cpp
from ai.models.model_manager import ModelManager
from automation.manager import AutomationManager
from automation.workflow import Workflow
from core.assistant import Assistant
from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logger import apply_log_level, get_logger
from core.paths import (
    DATA_DIR,
    ensure_dirs,
    get_knowledge_docs_dir,
    get_model_category_dir,
    get_models_root,
    get_plugins_dir,
    user_data_root,
)
from core.router import Router
from core.security_layer import SecurityLayer
from database.database_manager import DatabaseManager
from knowledge.knowledge_base import KnowledgeBase
from knowledge.rag_pipeline import RAGPipeline
from knowledge.retriever import RAGRetriever
from memory.embeddings import load_embedding_model
from memory.memory_manager import MemoryManager
from plugins import PluginManager
from project.manager import ProjectManager, WorkspaceManager
from security.auditor import SecurityAuditor
from security.permission_manager import PermissionManager
from tools import create_registry
from tools.base import ToolRegistry
from ui.main_window import MainWindow
from ui.theme_manager import ThemeManager
from ui.translations import Language, TranslationManager
from ui.welcome_dialog import WelcomeDialog
from ui.welcome_wizard import WelcomeWizard
from voice import VoiceManager
from voice.audio import AudioConfig, create_audio
from voice.stt import create_stt
from voice.tts import create_tts

logger = get_logger("app")


def _has_display() -> bool:
    """Check if a display is available for Qt GUI."""
    import os
    platform = os.environ.get("QT_QPA_PLATFORM", "")
    if platform == "offscreen":
        return False
    if os.environ.get("DISPLAY") is None and sys.platform != "win32":
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if user32.GetProcessWindowStation() is None:
                return False
        except Exception as exc:
            logger.debug("Display check failed: %s", exc)
    return True


HAS_DISPLAY = _has_display()


class _StartupModelLoadWorker(QThread):
    """Background worker for loading the default model during startup.

    Only the blocking model-load operation runs in the worker thread.
    Engine configuration happens in the worker as well (plain Python,
    no Qt objects). Event publication and GUI updates happen on the
    main thread via Qt signals.
    """

    success = Signal(str)  # model_name
    failure = Signal(str)  # error_message

    def __init__(
        self,
        model_manager: ModelManager,
        engine: LLMEngine,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_manager = model_manager
        self._engine = engine

    def run(self) -> None:
        try:
            if self._model_manager.list_models():
                model = self._model_manager.select_default()
                self._engine.configure(self._model_manager)
                if model is not None:
                    self.success.emit(model.name)
                else:
                    self.failure.emit("No model loaded")
            else:
                self.failure.emit("No models available")
        except Exception as exc:
            logger.error("Startup model load failed: %s", exc)
            self.failure.emit(str(exc))


class ApplicationManager:
    """Coordinates startup and shutdown of all application subsystems."""

    def __init__(self) -> None:
        self._started = False
        self._app: QApplication | None = None
        self._config: ConfigManager | None = None
        self._event_bus: EventBus | None = None
        self._router: Router | None = None
        self._assistant: Assistant | None = None
        self._theme: ThemeManager | None = None
        self._window: MainWindow | None = None
        self._model_manager: ModelManager | None = None
        self._engine: LLMEngine | None = None
        self._memory: MemoryManager | None = None
        self._tools: ToolRegistry | None = None
        self._permission_manager: PermissionManager | None = None
        self._auditor: SecurityAuditor | None = None
        self._security: SecurityLayer | None = None
        self._plugin_manager: PluginManager | None = None
        self._voice: VoiceManager | None = None
        self._knowledge: KnowledgeBase | None = None
        self._rag: RAGPipeline | None = None
        self._planner: Planner | None = None
        self._orchestrator: AgentOrchestrator | None = None
        self._automation: AutomationManager | None = None
        self._automation_dispatcher: Any | None = None
        self._scheduler_timer: QTimer | None = None
        self._db_manager: DatabaseManager | None = None
        self._workspace_manager: WorkspaceManager | None = None
        self._project_manager: ProjectManager | None = None
        self._model_load_worker: QThread | None = None
        self._shutting_down: bool = False

    def _ensure_user_dirs(self) -> None:
        """Ensure user data directories exist before any component writes to them.

        Delegates to :func:`core.paths.ensure_dirs` — the single explicit
        directory-creation point.  Importing ``core.paths`` alone never
        creates directories.
        """
        try:
            ensure_dirs()
            logger.debug("User data directories ensured")
        except OSError as exc:
            logger.warning("Could not create user data directories: %s", exc)

    def _is_first_run(self) -> bool:
        """Check if this is the first run (welcome not yet completed)."""
        if self._config is None:
            return True
        return not self._config.get("first_run.completed", False)

    def _mark_first_run_complete(self) -> None:
        """Mark first run as completed in config."""
        if self._config is not None:
            try:
                self._config.set("first_run.completed", True)
            except (OSError, RuntimeError) as exc:
                logger.error("Failed to persist first_run.completed: %s", exc)

    def _show_welcome(self) -> bool:
        """Show the welcome dialog/wizard and return whether it was accepted.

        Returns ``True`` only when a welcome UI was displayed and the user
        accepted/completed it.  Returns ``False`` when the welcome was not
        shown (headless, missing dependencies) or was rejected/closed by the
        user.  In all ``False`` cases the first-run flag must NOT be persisted.
        """
        if not HAS_DISPLAY:
            logger.info("Headless mode detected — skipping welcome dialog")
            return False

        if self._model_manager is None or self._engine is None:
            return False

        model_name = self._config.get("ai.model_name", "N/A") if self._config else "N/A"
        model_caps = None
        models = self._model_manager.list_models()
        has_backend = has_llama_cpp()
        model_status = get_model_status(models, has_backend and len(models) > 0)

        for info in models:
            if info.name == model_name:
                model_caps = info.capabilities
                break
        if models and model_caps is None:
            for info in models:
                if info.name != model_name and info.capabilities is not None:
                    model_name = info.name
                    model_caps = info.capabilities
                    break
            if model_caps is None:
                model_name = models[0].name
                model_caps = models[0].capabilities
        if not models:
            model_name = self._engine.model_name if self._engine else "N/A"

        lang_code = self._config.get("app.language", "en") if self._config else "en"
        language = Language.from_string(lang_code)

        if language != TranslationManager.get_language():
            TranslationManager.set_language(language)

        if model_status == ModelStatus.NO_MODEL_AVAILABLE or model_status == ModelStatus.STUB_MODE:
            wizard = WelcomeWizard(self._model_manager, self._event_bus)  # type: ignore[arg-type]
            result = wizard.exec()
            return result != 0

        dialog = WelcomeDialog(
            model_name=model_name,
            model_capabilities=model_caps,
            model_status=model_status,
        )
        result = dialog.exec()
        return result != 0

    def start(self, show_main_window: bool = True) -> int:
        if self._started:
            logger.warning("Application is already running")
            return 0

        logger.info("Starting Offline AI Assistant (Phase 13.1)")

        self._app = QApplication(sys.argv)
        
        self._ensure_user_dirs()
        
        self._config = ConfigManager()
        apply_log_level(self._config.get("logging.level", "INFO"))
        self._event_bus = EventBus.get_instance()
        self._router = Router()

        # PHASE 3: all model storage derives from the single user-selected
        # models root (models.storage_root -> core.paths.get_models_root).
        # The llm category dir under that root is the primary models dir;
        # configured search paths (absolute only) are honoured as-is.
        models_root = get_models_root()
        llm_category_dir = get_model_category_dir("llm")
        models_dir = self._config.get("ai.models_dir")
        if not models_dir or not Path(models_dir).is_absolute():
            models_dir = str(llm_category_dir)
        search_paths = self._config.get("ai.model_search_paths", [str(llm_category_dir)])
        ollama_dir = self._config.get("ai.ollama_models_dir", "")
        ollama_models_dir = Path(ollama_dir) if ollama_dir else None
        n_threads = self._config.get("ai.n_threads", 4)
        n_gpu_layers = self._config.get("ai.n_gpu_layers", 0)
        n_ctx = self._config.get("ai.n_ctx", 4096)
        auto_gpu = self._config.get("ai.auto_gpu_layers", False)
        # PHASE 4: canonical GPU execution mode (auto / cpu / gpu).  An
        # expert n_gpu_layers override is validated by the runtime decision
        # point, never bypassing hard capability limits.
        gpu_mode = str(self._config.get("ai.gpu_mode", "auto") or "auto").lower()
        if gpu_mode not in ("auto", "cpu", "gpu"):
            logger.warning("Invalid ai.gpu_mode %r — falling back to 'auto'", gpu_mode)
            gpu_mode = "auto"
        logger.info(
            "Model storage root: %s (llm category: %s)", models_root, models_dir
        )
        self._model_manager = ModelManager(
            models_dir=Path(models_dir),
            search_paths=[Path(p) for p in search_paths],
            ollama_models_dir=ollama_models_dir,
            n_threads=n_threads,
            n_gpu_layers=n_gpu_layers,
            n_ctx=n_ctx,
            auto_gpu_layers=auto_gpu,
            gpu_mode=gpu_mode,
        )
        self._engine = LlamaCppEngine()
        self._memory = MemoryManager(
            short_term_window=self._config.get("memory.short_term_window", 10),
            embedding_backend=self._config.get("memory.embedding_model", "stub"),
        )

        self._knowledge = KnowledgeBase(
            embedding_model=load_embedding_model(
                self._config.get("memory.embedding_model", "stub")
            ),
        )
        self._rag = RAGPipeline(RAGRetriever(self._knowledge))

        self._tools = create_registry(event_bus=self._event_bus, knowledge_base=self._rag)
        self._permission_manager = PermissionManager()
        self._auditor = SecurityAuditor(event_bus=self._event_bus)
        self._security = SecurityLayer(
            registry=self._tools,
            pm=self._permission_manager,
            auditor=self._auditor,
            event_bus=self._event_bus,
        )

        from tools.file_security import configure_default_validator_from_config

        configure_default_validator_from_config(self._config)

        self._plugin_manager = PluginManager(self._tools, self._event_bus, config=self._config)
        try:
            # CWD-independent default: the writable runtime plugins directory
            # under the user-data root (where operators drop plugins).  An
            # absolute configured value is used as-is; a relative value is
            # resolved against the user-data root, never against the CWD.
            plugins_dir = self._config.get("plugins.directory", "")
            if not plugins_dir:
                plugins_dir = str(get_plugins_dir())
            elif not Path(plugins_dir).is_absolute():
                plugins_dir = str(user_data_root() / plugins_dir)
            n = self._plugin_manager.discover_and_load(plugins_dir)
            logger.info("Plugin manager ready — %d plugin(s) loaded", n)
        except Exception:
            logger.warning("Plugin loading failed — continuing without plugins")
        self._plugin_manager.load_plugin_states()

        # Load persisted knowledge metadata before indexing
        knowledge_file = self._config.get("knowledge.file", "knowledge.json")
        knowledge_dir = Path(self._config.get("knowledge.persist_dir", str(DATA_DIR)))
        knowledge_path = knowledge_dir / knowledge_file
        loaded_count = 0
        if knowledge_path.exists():
            try:
                loaded_count = self._knowledge.load_file(knowledge_path)
                logger.info(
                    "Loaded %d persisted knowledge document(s) from %s",
                    loaded_count,
                    knowledge_path,
                )
            except Exception:
                logger.warning("Failed to load persisted knowledge from %s", knowledge_path)

        # Index documents from knowledge directory
        # CWD-independent default: the writable runtime knowledge documents
        # directory under the user-data root (where the user drops *.md/*.txt
        # files).  The indexer only reads this directory; the persistent
        # index stays under the data directory.  An absolute configured
        # value is used as-is; a relative value resolves against the
        # user-data root, never against the CWD.
        docs_dir = self._config.get("knowledge.directory", "")
        if not docs_dir:
            docs_dir = str(get_knowledge_docs_dir())
        elif not Path(docs_dir).is_absolute():
            docs_dir = str(user_data_root() / docs_dir)
        try:
            indexed = self._knowledge.index_directory(docs_dir)
            if indexed > 0 or loaded_count == 0:
                logger.info(
                    "Knowledge base ready — indexed %d chunk(s) from %s (%d persisted)",
                    indexed,
                    docs_dir,
                    loaded_count,
                )
            else:
                logger.info("Knowledge base ready - %d chunk(s) from %d persisted", loaded_count, loaded_count)
        except Exception:
            logger.info("Knowledge base ready (no indexed documents)")

        self._db_manager = DatabaseManager()
        self._agent_repository = AgentRepository(self._db_manager, event_bus=self._event_bus)

        # Seed built-in specialized agents (Researcher, Writer, Coder, ...)
        # on first run — user-created/edited agents are never overwritten.
        try:
            from agent.defaults import seed_builtin_agents

            seeded = seed_builtin_agents(self._agent_repository)
            if seeded:
                logger.info("Built-in agents ready (%d seeded)", seeded)
        except Exception:
            logger.warning("Built-in agent seeding skipped", exc_info=True)

        if self._tools is not None:
            from ai.engine.llm_engine import GenerationConfig

            n_ctx = self._config.get("ai.n_ctx", 4096)
            planner_max_tokens = min(self._config.get("ai.max_tokens", 512), n_ctx - 1)
            planner_config = GenerationConfig(
                max_tokens=planner_max_tokens,
                temperature=self._config.get("ai.temperature", 0.7),
                top_p=self._config.get("ai.top_p", 0.9),
                top_k=self._config.get("ai.top_k", 40),
                min_p=self._config.get("ai.min_p", 0.05),
                repeat_penalty=self._config.get("ai.repeat_penalty", 1.1),
            )
            self._planner = LLMPlanner(
                self._engine,
                tool_registry=self._tools,
                generation_config=planner_config,
            )
            self._orchestrator = AgentOrchestrator(
                self._event_bus, agent_repository=self._agent_repository
            )
        logger.info("Agent System ready (planner + orchestrator)")

        if self._tools is not None:
            self._automation = AutomationManager(
                tool_registry=self._tools, event_bus=self._event_bus
            )
            self._automation.register_workflow(
                Workflow.of(
                    "system_check",
                    [{"tool": "system_info", "params": {}}],
                    description="Show system information",
                    event_bus=self._event_bus,
                )
            )
            logger.info("Loaded persisted workflows")

            workflow_file = self._config.get("automation.file", "workflows.json")
            tasks_file = self._config.get("automation.tasks_file", "tasks.json")
            persist_dir = Path(self._config.get("automation.persist_dir", str(DATA_DIR)))
            workflow_path = persist_dir / workflow_file
            tasks_path = persist_dir / tasks_file
            try:
                loaded = self._automation.load_file(workflow_path)
                if loaded > 0:
                    logger.info("Loaded %d persisted workflow(s) from %s", loaded, workflow_path)
            except Exception:
                logger.warning("Failed to load persisted workflows from %s", workflow_path)

            try:
                loaded_tasks = self._automation.load_tasks(tasks_path)
                if loaded_tasks > 0:
                    logger.info("Loaded %d scheduled task(s) from %s", loaded_tasks, tasks_path)
            except Exception:
                logger.warning("Failed to load scheduled tasks from %s", tasks_path)

            logger.info("Automation manager ready (system_check workflow + scheduler)")

            # Off-GUI-thread task execution: the QTimer tick stays on the GUI
            # thread (cheap due-evaluation), while each due task's actual
            # execution runs on an AutomationTaskWorker.  Completion returns
            # to the GUI thread via a queued signal; all state mutation and
            # EventBus publication stay on the GUI thread.
            from automation.worker import AutomationDispatcher

            self._automation_dispatcher = AutomationDispatcher(
                self._automation, event_bus=self._event_bus
            )
            self._scheduler_timer = QTimer()
            self._scheduler_timer.timeout.connect(self._tick_automation)
            logger.info("Automation scheduler created (start deferred until MainWindow ready)")

        self._workspace_manager = WorkspaceManager(self._db_manager)
        self._project_manager = ProjectManager(self._db_manager)
        logger.info("Project/Workspace management ready")

        self._assistant = Assistant(
            config=self._config,
            event_bus=self._event_bus,
            router=self._router,
            model_manager=self._model_manager,
            engine=self._engine,
            memory=self._memory,
            tools=self._tools,
            knowledge=self._knowledge,
            rag_pipeline=self._rag,
            planner=self._planner,
            orchestrator=self._orchestrator,
            automation_manager=self._automation,
            plugin_manager=self._plugin_manager,
            workspace_manager=self._workspace_manager,
            project_manager=self._project_manager,
            agent_repository=self._agent_repository,
        )

        # Inject the assistant's effective profile into the shared planner so
        # that LLMPlanner._build_prompt includes identity, personality, communication
        # style, etc.  (The planner is created before the Assistant, so the profile
        # cannot be passed at construction time.)
        if self._planner is not None:
            self._planner.profile = self._assistant.get_effective_profile()

        # Load persisted agents into the orchestrator so that named-agent
        # multi-agent workflows have agents available at startup.  Must happen
        # after self._assistant is constructed because the planner factory
        # needs the assistant's effective profile.
        if (
            self._orchestrator is not None
            and self._tools is not None
            and self._assistant is not None
        ):
            _assistant = self._assistant

            def _make_planner(system_prompt: str) -> Any:
                profile = _assistant.get_effective_profile()
                if self._engine is not None and self._engine.is_ready:
                    return LLMPlanner(
                        self._engine,
                        tool_registry=self._tools,
                        profile=profile,
                        system_prompt=system_prompt,
                        generation_config=planner_config,
                    )
                return StubPlanner(
                    tool_registry=self._tools,
                    profile=profile,
                    system_prompt=system_prompt,
                )

            loaded_agents = self._orchestrator.load_persisted_agents(
                tool_registry=self._tools,
                planner_factory=_make_planner,
            )
            try:
                loaded_count = int(loaded_agents)
            except (TypeError, ValueError):
                loaded_count = 0
            if loaded_count > 0:
                logger.info("Loaded %d persisted agent(s) into orchestrator", loaded_count)

        theme_name = self._config.get("ui.theme", "dark")
        self._theme = ThemeManager(self._app, initial_theme=theme_name)

        if self._is_first_run():
            try:
                accepted = self._show_welcome()
            except Exception:
                logger.exception("First-run welcome dialog failed — continuing with defaults")
                accepted = False
            if accepted:
                self._mark_first_run_complete()

        voice_cfg = self._config.get("voice", {})
        audio_cfg = self._config.get("audio", {})
        stt_cfg = voice_cfg.get("stt", {})
        tts_cfg = voice_cfg.get("tts", {})
        input_dev_name = audio_cfg.get("input_device_name", "")
        input_dev_idx = audio_cfg.get("input_device_index")
        output_dev_name = audio_cfg.get("output_device_name", "")
        output_dev_idx = audio_cfg.get("output_device_index")
        audio_config = AudioConfig(
            device=input_dev_idx if input_dev_name else None,
            input_device_name=input_dev_name,
            input_device_hostapi=audio_cfg.get("input_device_hostapi", ""),
            output_device_index=output_dev_idx if output_dev_name else None,
            output_device_name=output_dev_name,
            output_device_hostapi=audio_cfg.get("output_device_hostapi", ""),
            prefer_wasapi=audio_cfg.get("prefer_wasapi", True),
            wasapi_fallback_to_mme=audio_cfg.get("wasapi_fallback_to_mme", True),
        )
        self._voice = VoiceManager(
            event_bus=self._event_bus,
            audio_manager=create_audio(
                config=audio_config,
                preferred="sounddevice" if voice_cfg.get("enabled", True) else "stub",
            ),
            stt=create_stt(
                preferred="whisper" if stt_cfg.get("provider", "faster-whisper") == "faster-whisper" else "stub",
                model_name=stt_cfg.get("model", "tiny"),
                device=stt_cfg.get("device", "auto"),
                language=voice_cfg.get("language", "auto"),
            ),
            tts=create_tts(preferred=tts_cfg.get("provider", "pyttsx3")),
            config=self._config,
        )
        self._voice.initialize()
        logger.info(
            "Voice manager ready (STT=%s, TTS=%s, audio=%s)",
            self._voice.stt_name,
            self._voice.tts_name,
            self._voice.audio_name,
        )
        if voice_cfg.get("enabled", True):
            # Wake word respects the voice.wake_word.enabled sub-setting
            wake_cfg = voice_cfg.get("wake_word", {})
            if isinstance(wake_cfg, dict) and wake_cfg.get("enabled", True):
                self._voice.start_wake_word()
            else:
                logger.info("Wake word disabled via voice.wake_word.enabled — not starting")

        self._window = MainWindow(
            config=self._config,
            event_bus=self._event_bus,
            theme=self._theme,
            assistant=self._assistant,
            security=self._security,
            voice=self._voice,
            plugin_manager=self._plugin_manager,
            automation_manager=self._automation,
            automation_dispatcher=getattr(self, "_automation_dispatcher", None),
        )
        self._voice.flush_pending_startup_errors()
        if show_main_window:
            self._window.show()

        self._assistant.start()
        self._event_bus.subscribe("NEW_CHAT_REQUESTED", self._on_new_chat_requested)

        # Start default model loading in background after the GUI is visible
        # and the event loop is able to process paint/input events.
        if self._model_manager is not None and self._model_manager.list_models():
            self._start_model_load_worker()

        if self._scheduler_timer is not None and not self._scheduler_timer.isActive():
            self._scheduler_timer.start(1000)
            logger.info("Automation scheduler started (1 s tick)")

        self._started = True
        logger.info(
            "Application started successfully (security + voice + knowledge + agent + automation active)"
        )
        return 0

    def stop(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True

        # Shutdown chat voice coordinator first (created externally by
        # application_final.main; lives on the GUI thread and may own a
        # short transcription worker that must finish before teardown).
        coordinator = getattr(self, "_chat_coordinator", None)
        if coordinator is not None:
            try:
                coordinator.shutdown()
            except Exception:
                logger.warning("ChatVoiceCoordinator shutdown failed", exc_info=True)
            self._chat_coordinator = None

        # Wait for the startup model load worker to finish naturally before
        # proceeding with model/engine teardown.  The worker may be inside
        # llama_cpp.Llama() or another blocking Python/C-extension call.
        # Do NOT call terminate() — that can corrupt native state.
        # QThread.wait() is used here as safe shutdown coordination: it
        # blocks the GUI thread only during teardown and guarantees the
        # worker has fully exited before ModelManager/engine cleanup begins.
        worker = getattr(self, "_model_load_worker", None)
        self._model_load_worker = None
        if worker is not None and worker.isRunning():
            logger.info(
                "Waiting for startup model load worker to finish before teardown"
            )
            worker.wait()

        # Save knowledge persistence before shutdown
        if self._knowledge is not None and self._config is not None:
            try:
                knowledge_file = self._config.get("knowledge.file", "knowledge.json")
                knowledge_dir = Path(self._config.get("knowledge.persist_dir", str(DATA_DIR)))
                knowledge_path = knowledge_dir / knowledge_file
                self._knowledge.save_file(knowledge_path)
                logger.info("Knowledge persisted to %s", knowledge_path)
            except Exception:
                logger.warning("Failed to persist knowledge")

        # Stop the automation dispatcher and wait (bounded) for any running
        # task workers BEFORE persisting tasks — otherwise a task finishing
        # after save_tasks() would lose its final state, and a still-running
        # worker would outlive the application (zombie QThread).
        dispatcher = getattr(self, "_automation_dispatcher", None)
        self._automation_dispatcher = None
        if dispatcher is not None:
            try:
                dispatcher.shutdown()
            except Exception:
                logger.warning("Automation dispatcher shutdown failed", exc_info=True)

        # Save workflow persistence before shutdown
        if self._automation is not None and self._config is not None:
            try:
                workflow_file = self._config.get("automation.file", "workflows.json")
                tasks_file = self._config.get("automation.tasks_file", "tasks.json")
                persist_dir = Path(self._config.get("automation.persist_dir", str(DATA_DIR)))
                workflow_path = persist_dir / workflow_file
                tasks_path = persist_dir / tasks_file
                self._automation.save_file(workflow_path)
                logger.info("Workflows persisted to %s", workflow_path)
                self._automation.save_tasks(tasks_path)
                logger.info("Scheduled tasks persisted to %s", tasks_path)
            except Exception:
                logger.warning("Failed to persist workflows/tasks")

        # Save plugin enable/disable state before shutdown
        plugin_manager = getattr(self, "_plugin_manager", None)
        if plugin_manager is not None:
            try:
                plugin_manager.save_plugin_states()
                logger.info("Plugin states persisted")
            except Exception:
                logger.warning("Failed to persist plugin states")

        # Each remaining cleanup step is independently guarded: one
        # failing cleanup must never truncate the rest of shutdown.
        if self._memory is not None:
            try:
                self._memory.close()
            except Exception:
                logger.warning("Memory close failed during shutdown", exc_info=True)

        if self._model_manager is not None:
            try:
                self._model_manager.unload()
            except Exception:
                logger.warning("Model unload failed during shutdown", exc_info=True)
        if self._assistant is not None:
            try:
                self._assistant.stop()
            except Exception:
                logger.warning("Assistant stop failed during shutdown", exc_info=True)
        db = getattr(self, "_db_manager", None)
        if db is not None:
            try:
                db.close()
            except Exception:
                logger.warning("Database close failed during shutdown", exc_info=True)
        timer = getattr(self, "_scheduler_timer", None)
        if timer is not None:
            try:
                timer.stop()
                logger.info("Automation scheduler stopped")
            except Exception:
                logger.warning(
                    "Scheduler timer stop failed during shutdown", exc_info=True
                )
            timer = None
        voice = getattr(self, "_voice", None)
        if voice is not None:
            try:
                voice.stop()
                logger.info("Voice resources released")
            except Exception:
                logger.warning("Voice stop failed during shutdown", exc_info=True)
        window = getattr(self, "_window", None)
        if window is not None:
            try:
                window._unsubscribe_all_events()
                window._voice = None  # break reference cycle for VoicePage
                window.close()
                logger.info("MainWindow closed and cleaned up")
            except Exception:
                logger.warning("Window cleanup failed during shutdown", exc_info=True)
        self._started = False
        logger.info("Application stopped")

    def _tick_automation(self) -> None:
        """Timer callback: due-evaluate on the GUI thread (runs on Qt main thread).

        The due scan is a cheap ``is_due`` check; the actual task execution is
        submitted to worker threads by the dispatcher, so this callback never
        blocks the GUI on tool/workflow work.
        """
        dispatcher = getattr(self, "_automation_dispatcher", None)
        if dispatcher is not None:
            try:
                dispatcher.tick()
                return
            except Exception:
                logger.exception("Automation dispatcher tick failed")
        if self._automation is not None:
            try:
                self._automation.tick()
            except Exception:
                logger.exception("Automation scheduler tick failed")

    def run(self) -> int:
        """Start the application and enter the Qt event loop.

        If start() raises an exception (e.g., MainWindow construction failure),
        stop() is called to clean up partially-initialized resources before
        re-raising. If start() returns a non-zero exit code or HAS_DISPLAY
        is False, no cleanup is needed (consistent with the existing contract).
        """
        try:
            exit_code = self.start()
        except Exception:
            self.stop()
            raise
        if exit_code != 0:
            return exit_code
        assert self._app is not None
        if not HAS_DISPLAY:
            logger.info("Headless mode — app initialized, skipping GUI")
            return 0
        try:
            return self._app.exec()
        finally:
            self.stop()

    @property
    def is_started(self) -> bool:
        return self._started

    def _start_model_load_worker(self) -> None:
        """Start background loading of the default AI model."""
        if self._assistant is None or self._model_manager is None or self._engine is None:
            return
        if self._model_load_worker is not None:
            logger.warning("Model load worker already running")
            return

        worker = _StartupModelLoadWorker(
            model_manager=self._model_manager,
            engine=self._engine,
        )
        worker.success.connect(self._on_startup_model_loaded)
        worker.failure.connect(self._on_startup_model_load_failed)
        # Standard Qt worker lifetime: once the thread has fully exited,
        # deleteLater reclaims the QThread.  Without this, the wrapper
        # could be destroyed while the thread is still finishing (the
        # "QThread: Destroyed while thread is still running" hazard).
        worker.finished.connect(worker.deleteLater)
        worker.start()
        self._model_load_worker = worker
        logger.info("Default model loading started in background")

    @Slot(str)
    def _on_startup_model_loaded(self, model_name: str) -> None:
        """GUI-thread slot: default model loaded successfully."""
        if getattr(self, "_shutting_down", False):
            return
        assert self._event_bus is not None
        logger.info("Default model loaded: %s", model_name)
        self._event_bus.publish(
            "MODEL_LOADED",
            data={"model": model_name},
        )

    @Slot(str)
    def _on_startup_model_load_failed(self, error: str) -> None:
        """GUI-thread slot: default model loading failed."""
        if getattr(self, "_shutting_down", False):
            return
        assert self._event_bus is not None
        logger.error("Default model load failed: %s", error)
        self._event_bus.publish(
            "MODEL_LOAD_FAILED",
            data={"error": error},
        )

    def _on_new_chat_requested(self, event_type: str, data: dict) -> None:
        """Handle New Chat: clear ShortTermMemory.

        Preserves all durable data (SQLite memories, settings, projects,
        knowledge documents). Only the active short-term conversation buffer
        is reset so the next user message starts with a clean context.
        """
        if self._memory is not None:
            snapshot = None
            if self._assistant is not None:
                try:
                    profile = self._assistant.get_effective_profile()
                    if isinstance(profile, dict):
                        snapshot = profile
                except Exception:
                    logger.debug("Could not retrieve profile snapshot for new conversation", exc_info=True)
            self._memory.start_conversation(profile_snapshot=snapshot)
            logger.info("New chat requested — ShortTermMemory cleared")


def main() -> int:
    """Entry point used by the ``offline-ai`` console script."""
    manager = ApplicationManager()
    return manager.run()
