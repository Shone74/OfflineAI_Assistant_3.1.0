"""Standalone final application bootstrap.

Initializes the real backend services and presents them through the
reference-based AppShell.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from app.application import ApplicationManager
from ui.agents_page import AgentsPage
from ui.app_shell import AppShell
from ui.assistant_hub import AssistantHub
from ui.automation_dashboard import AutomationDashboard
from ui.capabilities_page import CapabilitiesPage
from ui.chat_voice_coordinator import ChatVoiceCoordinator
from ui.chat_widget import ChatWidget
from ui.home_page import HomePage
from ui.knowledge_dashboard import KnowledgeDashboard
from ui.memory_page import MemoryPage
from ui.models_page import ModelsPage
from ui.projects_page import ProjectsPage
from ui.settings_page import SettingsPage
from ui.tools_page import ToolsPage
from ui.voice_page import VoicePage
from ui.workflow_builder import WorkflowBuilder


def _wire_knowledge_dashboard(knowledge: KnowledgeDashboard, assistant) -> None:
    """Connect the AppShell's KnowledgeDashboard to real handlers.

    H3: the search/index/rebuild/delete operations run on QThread workers
    (ui.knowledge_worker) so the GUI thread never blocks, and the
    dashboard — previously unconnected in the final AppShell — becomes
    functional.  Workers are tracked in a holder owned by the dashboard
    so they outlive the operation; each handler is re-entry guarded.
    """
    from ui.knowledge_worker import start_knowledge_index, start_knowledge_search

    holders = {"search": [], "index": []}
    state = {"searching": False, "indexing": False}

    def _on_search(query: str) -> None:
        if state["searching"]:
            return

        def _completed(context: str, results: list) -> None:
            state["searching"] = False
            knowledge.display_search_results(context, results)

        def _failed(error: str) -> None:
            state["searching"] = False
            knowledge._preview.setPlainText(f"Search failed: {error}")

        state["searching"] = True
        start_knowledge_search(assistant, query, _completed, _failed, holders["search"])

    def _on_index(directory: str) -> None:
        kb = getattr(assistant, "knowledge", None)
        if kb is None or state["indexing"]:
            return

        def _completed(count: int, op: str) -> None:
            state["indexing"] = False
            get_stats = getattr(kb, "get_statistics", dict)
            knowledge.set_statistics(get_stats())
            knowledge.set_documents(getattr(kb, "_documents", {}))

        def _failed(error: str) -> None:
            state["indexing"] = False

        state["indexing"] = True
        start_knowledge_index(kb, "index_directory", directory, _completed, _failed, holders["index"])

    def _on_rebuild(directory: str) -> None:
        kb = getattr(assistant, "knowledge", None)
        if kb is None or state["indexing"]:
            return

        def _completed(count: int, op: str) -> None:
            state["indexing"] = False
            knowledge.set_statistics(kb.get_statistics())
            knowledge.set_documents(kb._documents)

        def _failed(error: str) -> None:
            state["indexing"] = False

        state["indexing"] = True
        start_knowledge_index(kb, "rebuild", directory, _completed, _failed, holders["index"])

    def _on_index_file(file_path: str) -> None:
        kb = getattr(assistant, "knowledge", None)
        if kb is None or state["indexing"]:
            return

        def _completed(count: int, op: str) -> None:
            state["indexing"] = False
            knowledge.set_statistics(kb.get_statistics())
            knowledge.set_documents(kb._documents)

        def _failed(error: str) -> None:
            state["indexing"] = False

        state["indexing"] = True
        start_knowledge_index(kb, "index_document", file_path, _completed, _failed, holders["index"])

    def _on_delete(doc_id: str) -> None:
        kb = getattr(assistant, "knowledge", None)
        if kb is None or not doc_id:
            return
        try:
            kb.delete_document(doc_id)
        except Exception:
            return
        knowledge.set_statistics(kb.get_statistics())
        knowledge.set_documents(kb._documents)

    def _on_export() -> None:
        kb = getattr(assistant, "knowledge", None)
        if kb is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            knowledge,
            "Export Knowledge Base",
            "knowledge_export.json",
            "JSON Files (*.json);;Markdown Files (*.md)",
        )
        if not path:
            return
        if path.lower().endswith(".md"):
            content = kb.export_to_markdown()
        else:
            import json
            content = json.dumps(kb.export_to_dict(), ensure_ascii=False, indent=2)
        try:
            with open(path, "w", encoding="utf-8") as export_file:
                export_file.write(content)
        except OSError:
            return

    knowledge.search_requested.connect(_on_search)
    knowledge.index_requested.connect(_on_index)
    knowledge.index_file_requested.connect(_on_index_file)
    knowledge.rebuild_requested.connect(_on_rebuild)
    knowledge.delete_requested.connect(_on_delete)
    knowledge.export_requested.connect(_on_export)
    # Seed the dashboard with the current knowledge base state.
    kb = getattr(assistant, "knowledge", None)
    if kb is not None:
        try:
            knowledge.set_statistics(kb.get_statistics())
            knowledge.set_documents(kb._documents)
        except Exception:
            pass


def _build_pages(manager: ApplicationManager, navigator) -> list[tuple[str, QWidget]]:
    assistant = manager._assistant
    config = manager._config
    event_bus = manager._event_bus
    voice = manager._voice
    plugin_manager = manager._plugin_manager
    automation_manager = manager._automation

    chat = ChatWidget()
    # Chat + Voice + Assistant wiring (Phase 7): send/voice signals and
    # VOICE_* events have a consumer inside the AppShell; the Automatic
    # Listening toggle works through the coordinator.
    coordinator = ChatVoiceCoordinator(
        chat=chat,
        assistant=assistant,
        voice_manager=voice,
        event_bus=event_bus,
    )
    coordinator.wire()
    manager._chat_coordinator = coordinator
    memory = MemoryPage(assistant=assistant)
    knowledge = KnowledgeDashboard(navigator=navigator, assistant=assistant)
    _wire_knowledge_dashboard(knowledge, assistant)
    models = ModelsPage(assistant=assistant, model_manager=manager._model_manager, event_bus=event_bus)
    capabilities = CapabilitiesPage(assistant=assistant)
    projects = ProjectsPage(assistant=assistant)
    agents = AgentsPage(assistant=assistant)
    tools = ToolsPage(assistant=assistant, event_bus=event_bus)
    voice_page = VoicePage(config=config, event_bus=event_bus, voice_manager=voice)
    automation = AutomationDashboard(navigator=navigator)
    workflow = WorkflowBuilder(automation_manager=automation_manager, navigator=navigator)
    settings_page = SettingsPage(
        config=config,
        event_bus=event_bus,
        assistant=assistant,
        plugin_manager=plugin_manager,
        model_manager=manager._model_manager,
        voice_manager=voice,
    )

    pages = [
        ("Chat", chat),
        ("Memory", memory),
        ("Knowledge", knowledge),
        ("Models", models),
        ("Capabilities", capabilities),
        ("Projects", projects),
        ("Agents", agents),
        ("Tools", tools),
        ("Voice", voice_page),
        ("Automation", automation),
        ("Workflow", workflow),
        ("Settings", settings_page),
    ]
    return pages


def main() -> int:
    manager = ApplicationManager()
    try:
        # Do not show the legacy MainWindow — the AppShell (below) is the
        # primary window.  On first run, the wizard/welcome dialog is
        # still shown inside start().
        exit_code = manager.start(show_main_window=False)
        if exit_code != 0:
            return exit_code

        app = QApplication.instance() or QApplication(sys.argv)

        theme = manager._theme
        assistant = manager._assistant
        config = manager._config
        assistant_name = config.get("app.name", "Assistant")

        shell_holder: dict[str, AppShell] = {}

        def navigator(route: str) -> None:
            shell_holder["shell"]._navigate(route)

        home = HomePage(
            theme=theme,
            assistant_name=assistant_name,
            navigator=navigator,
            assistant=assistant,
            event_bus=manager._event_bus,
        )
        hub = AssistantHub(assistant=assistant, navigator=navigator)

        pages = _build_pages(manager, navigator)
        all_pages = [("Home", home), ("Assistant Hub", hub), *pages]

        model_name = getattr(assistant, "model_name", None) or "No model loaded"
        capabilities = []
        try:
            caps = getattr(assistant, "model_capabilities", None)
            if caps:
                capabilities = [c for c, active in caps._asdict().items() if active][:8]
        except Exception:
            pass
        memory_count = 0
        try:
            memory = getattr(assistant, "_memory", None)
            if memory is not None:
                stm = getattr(memory, "_short_term", None)
                if stm is not None:
                    memory_count = len(stm.get_history())
        except Exception:
            pass

        shell = AppShell(
            theme=theme,
            assistant_name=assistant_name,
            pages=all_pages,
            default_route="Home",
            assistant=assistant,
            model_name=model_name,
            capabilities=capabilities,
            memory_count=memory_count,
            event_bus=manager._event_bus,
        )
        shell._chat_coordinator = getattr(manager, "_chat_coordinator", None)
        shell_holder["shell"] = shell
        shell.show()

        def _on_about_to_quit() -> None:
            # ApplicationManager.stop() handles coordinator teardown, knowledge
            # persistence, and component cleanup.  The idempotency guard at
            # the top of stop() ensures this is safe even if main()'s finally
            # block also calls stop() during exception-driven shutdown.
            try:
                manager.stop()
            except Exception:
                pass

        app.aboutToQuit.connect(_on_about_to_quit)

        return app.exec()
    finally:
        # Guarantee cleanup even on startup exception (start() or AppShell
        # construction failure).  stop() is idempotent via the _shutting_down
        # guard, so the aboutToQuit handler's call above becomes a no-op.
        try:
            manager.stop()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
