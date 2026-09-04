"""Tests for Finalna Aplikacija standalone foundation."""

from __future__ import annotations

import os
import sys

import pytest
from PySide6.QtWidgets import QApplication, QWidget

# Ensure the standalone app root is importable when running tests from the
# ``tests/`` directory without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.app_shell import AppShell
from ui.home_page import HomePage


class TestStandaloneImports:
    """Verify the standalone application imports cleanly."""

    def test_app_shell_import(self) -> None:
        from ui.app_shell import AppShell

        assert AppShell is not None

    def test_home_page_import(self) -> None:
        from ui.home_page import HomePage

        assert HomePage is not None

    def test_application_final_import(self) -> None:
        from app.application_final import main as app_main

        assert app_main is not None


class TestAppShell:
    """Verify AppShell instantiates and navigates."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_shell_creates_with_defaults(self) -> None:
        shell = AppShell(theme=None, pages=[("Home", QWidget())])
        assert shell is not None
        assert shell._default_route == "Home"

    def test_shell_default_route(self) -> None:
        page = QWidget()
        shell = AppShell(theme=None, pages=[("Home", page)], default_route="Home")
        assert shell._pages_widget.currentWidget() is page

    def test_shell_navigate_changes_page(self) -> None:
        home = QWidget()
        chat = QWidget()
        shell = AppShell(theme=None, pages=[("Home", home), ("Chat", chat)])
        shell._navigate("Chat")
        assert shell._pages_widget.currentWidget() is chat

    def test_shell_navigate_unknown_route(self) -> None:
        home = QWidget()
        shell = AppShell(theme=None, pages=[("Home", home)])
        shell._navigate("Nonexistent")
        assert shell._pages_widget.currentWidget() is home


class TestHomePage:
    """Verify HomePage instantiates and displays."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_home_page_creates(self) -> None:
        page = HomePage(theme=None, assistant_name="Test")
        assert page is not None

    def test_home_page_has_cards(self) -> None:
        page = HomePage(theme=None, assistant_name="Test")
        assert page._ai_card is not None
        assert page._system_card is not None
        assert page._memory_card is not None
        assert page._privacy_card is not None
