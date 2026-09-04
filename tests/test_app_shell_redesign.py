"""Testovi AppShell redizajna (Faza 3): topbar, toggle, selected nav, context."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QWidget

from ui.app_shell import AppShell


def _make_shell(pages: list[tuple[str, QWidget]] | None = None) -> AppShell:
    pages = pages or [("Home", QWidget()), ("Chat", QWidget()), ("Models", QWidget())]
    return AppShell(theme=None, pages=pages, default_route="Home")


class TestTopbar:
    def test_topbar_exists_with_controls(self, qapp):
        shell = _make_shell()
        assert shell._menu_button.text() == "☰"
        assert shell._context_button.text() == "Context"
        assert shell._topbar_title.text() == "Assistant"

    def test_toggle_sidebar(self, qapp):
        shell = _make_shell()
        assert shell._sidebar_visible is True
        shell.toggle_sidebar()
        assert shell._sidebar_visible is False
        assert shell._sidebar.isVisible() is False
        shell.toggle_sidebar()
        assert shell._sidebar_visible is True

    def test_toggle_context_panel(self, qapp):
        shell = _make_shell()
        assert shell._context_visible is True
        shell.toggle_context_panel()
        assert shell._context_visible is False
        assert shell._context_panel.isVisible() is False


class TestSidebarNavigation:
    def test_nav_selected_state_follows_route(self, qapp):
        shell = _make_shell()
        # Default route Home -> Home checked
        assert shell._nav_buttons["Home"].isChecked() is True
        assert shell._nav_buttons["Chat"].isChecked() is False

        shell._navigate("Chat")
        assert shell._nav_buttons["Chat"].isChecked() is True
        assert shell._nav_buttons["Home"].isChecked() is False

    def test_advanced_routes_included(self, qapp):
        pages = [
            ("Home", QWidget()),
            ("Chat", QWidget()),
            ("Models", QWidget()),
            ("Agents", QWidget()),
            ("Automation", QWidget()),
        ]
        shell = _make_shell(pages)
        for route in ("Models", "Agents", "Automation"):
            assert route in shell._nav_buttons, f"{route} nije u navigaciji"

    def test_nav_click_navigates(self, qapp):
        home, chat = QWidget(), QWidget()
        shell = _make_shell([("Home", home), ("Chat", chat)])
        shell._nav_buttons["Chat"].click()
        assert shell._pages_widget.currentWidget() is chat
        assert shell._nav_buttons["Chat"].isChecked() is True

    def test_new_conversation_button(self, qapp):
        shell = _make_shell()
        # Bez asistenta: samo navigira na Chat, ne pada
        shell._on_new_conversation()
        assert shell._pages_widget.currentWidget() is shell._page_map["Chat"]


class TestContextPanel:
    def test_context_panel_content(self, qapp):
        shell = _make_shell()
        assert "AI MODEL" in shell._context_model_label.text().upper() or \
            "No model loaded" in shell._context_model_label.text()
        assert "recent messages" in shell._context_memory_label.text()

    def test_update_model_status(self, qapp):
        shell = _make_shell()
        shell.update_model_status("Qwen2.5-Coder-7B")
        assert "Qwen2.5-Coder-7B" in shell._context_model_label.text()
        assert "●" in shell._context_model_label.text()

    def test_update_memory_count(self, qapp):
        shell = _make_shell()
        shell.update_memory_count(42)
        assert "42" in shell._context_memory_label.text()

    def test_set_assistant_name(self, qapp):
        shell = _make_shell()
        shell.set_assistant_name("Jarvis")
        assert shell._topbar_title.text() == "Jarvis"


class TestShellStyle:
    def test_no_local_stylesheet(self, qapp):
        """AppShell NE sme imati lokalni QSS — stilovi dolaze iz ThemeManager-a."""
        shell = _make_shell()
        assert shell.styleSheet() == ""


class TestEventBusIntegration:
    def test_shell_subscribes_to_model_events(self, qapp):
        from core.event_bus import EventBus

        bus = EventBus()
        shell = _make_shell()
        shell._event_bus = bus
        shell._subscribe_events()
        assert len(shell._event_sub_ids) == 5

        bus.publish("MODEL_LOADED", data={"model": "Qwen2.5-Coder-7B"})
        assert "Qwen2.5-Coder-7B" in shell._context_model_label.text()

        bus.publish("MODEL_UNLOADED", data={})
        assert "No model loaded" in shell._context_model_label.text()
        shell._unsubscribe_events()

    def test_shell_subscribes_to_memory_events(self, qapp):
        from core.event_bus import EventBus

        bus = EventBus()
        shell = _make_shell()
        shell._event_bus = bus
        shell._subscribe_events()

        bus.publish("MEMORY_UPDATED", data={"count": 17})
        assert "17" in shell._context_memory_label.text()
        shell._unsubscribe_events()

    def test_unsubscribe_stops_delivery(self, qapp):
        from core.event_bus import EventBus

        bus = EventBus()
        shell = _make_shell()
        shell._event_bus = bus
        shell._subscribe_events()
        shell._unsubscribe_events()

        bus.publish("MODEL_LOADED", data={"model": "test-model"})
        assert "test-model" not in shell._context_model_label.text()

    def test_new_conversation_publishes_event(self, qapp):
        from core.event_bus import EventBus

        bus = EventBus()
        received: list[tuple[str, object]] = []

        def handler(event_type, data):
            received.append((event_type, data))

        bus.subscribe("NEW_CHAT_REQUESTED", handler)

        shell = _make_shell()
        shell._event_bus = bus
        shell._on_new_conversation()
        assert received == [("NEW_CHAT_REQUESTED", {})]
        assert shell._pages_widget.currentWidget() is shell._page_map["Chat"]
