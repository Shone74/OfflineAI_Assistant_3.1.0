"""Standalone final application bootstrap.

Initializes the real backend services and presents them through the
reference-based AppShell.
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QWidget

from app.application import ApplicationManager
from ui.app_shell import AppShell
from ui.home_page import HomePage
from ui.assistant_hub import AssistantHub
from ui.chat_widget import ChatWidget
from ui.memory_page import MemoryPage
from ui.knowledge_dashboard import KnowledgeDashboard
from ui.models_page import ModelsPage
from ui.capabilities_page import CapabilitiesPage
from ui.projects_page import ProjectsPage
from ui.agents_page import AgentsPage
from ui.tools_page import ToolsPage
from ui.voice_page import VoicePage
from ui.automation_dashboard import AutomationDashboard
from ui.workflow_builder import WorkflowBuilder
from ui.settings_page import SettingsPage


def _build_pages(manager: ApplicationManager, navigator) -> list[tuple[str, QWidget]]:
    assistant = manager._assistant
    config = manager._config
    event_bus = manager._event_bus
    theme = manager._theme
    security = manager._security
    voice = manager._voice
    plugin_manager = manager._plugin_manager
    automation_manager = manager._automation

    chat = ChatWidget()
    memory = MemoryPage(assistant=assistant)
    knowledge = KnowledgeDashboard(navigator=navigator)
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
    # Ne prikazuj legacy MainWindow — AppShell (ispod) je primarni prozor.
    # Ako je first-run, wizard/welcome dijalog i dalje se prikazuje unutar start().
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
    shell_holder["shell"] = shell
    shell.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
