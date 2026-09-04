"""Theme manager — applies Qt stylesheets using the official Graphite + Emerald palette.

The default ``grey_emerald`` theme uses the Graphite + Emerald color scheme
defined in the reference design previews (Izgled Aplikacije).  All themes
are dark variants; ``light`` provides a light-mode alternative.

Active theme is persisted in ``settings.json`` under ``ui.theme``.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QApplication

ThemeName = Literal["dark", "light", "cyber", "grey_emerald"]

_GRAPHITE_BG = "#151819"
_GRAPHITE_SIDEBAR = "#111516"
_GRAPHITE_CARD = "#1C2221"
_GRAPHITE_DARK_CARD = "#191F1E"
_EMERALD = "#1D8A68"
_EMERALD_HOVER = "#249E78"
_EMERALD_TEXT = "#62C7A3"
_EMERALD_SUCCESS = "#245846"
_EMERALD_SUCCESS_TEXT = "#7DE0B7"
_TEXT_PRIMARY = "#EDF3F0"
_TEXT_SECONDARY = "#8C9692"
_TEXT_MUTED = "#737D79"
_TEXT_DARK = "#59625F"
_BORDER = "#29302E"
_BORDER_SIDEBAR = "#202624"
_WARNING = "#D6A24A"
_ERROR = "#D96565"

_DARK_STYLE = f"""
QMainWindow {{ background: {_GRAPHITE_BG}; color: {_TEXT_PRIMARY}; }}
QWidget {{ color: {_TEXT_PRIMARY}; font-family: "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QTextEdit, QLineEdit, QComboBox {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY};
    border: 1px solid {_BORDER}; border-radius: 4px; }}
QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {_EMERALD}; }}
QListWidget {{ background: {_GRAPHITE_SIDEBAR}; border: none; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {_GRAPHITE_CARD}; }}
QListWidget::item:selected {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; }}
QPushButton {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; border: none;
    padding: 6px 12px; border-radius: 4px; font-weight: 700; }}
QPushButton:hover {{ background: {_EMERALD_HOVER}; }}
QPushButton:pressed {{ background: {_EMERALD_SUCCESS}; }}
QPushButton#secondary_button {{ background: transparent; color: {_TEXT_MUTED};
    border: 1px solid {_BORDER_SIDEBAR}; }}
QPushButton#secondary_button:hover {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY}; }}
QStatusBar {{ background: {_GRAPHITE_CARD}; color: {_TEXT_SECONDARY}; border-top: 1px solid {_BORDER}; }}
QMenuBar {{ background: {_GRAPHITE_SIDEBAR}; color: {_TEXT_PRIMARY}; spacing: 6px;
    border-bottom: 1px solid {_BORDER}; }}
QMenuBar::item:selected {{ background: {_EMERALD}; }}
QMenuBar::item:hover {{ background: {_GRAPHITE_CARD}; }}
QToolBar {{ background: {_GRAPHITE_SIDEBAR}; border: none; spacing: 6px; }}
QToolBar::separator {{ border: 1px solid {_BORDER_SIDEBAR}; }}
QSplitter::handle {{ background-color: {_BORDER}; }}
QDialog {{ background: {_GRAPHITE_BG}; color: {_TEXT_PRIMARY}; }}
QGroupBox {{ border: 1px solid {_BORDER}; border-radius: 6px; margin-top: 12px;
    padding-top: 8px; font-weight: 700; }}
QGroupBox::title {{ color: {_EMERALD_TEXT}; padding-left: 8px; }}
QTabBar::tab {{ background: {_GRAPHITE_CARD}; color: {_TEXT_SECONDARY};
    padding: 6px 12px; border: 1px solid {_BORDER}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; }}
QTabWidget::pane {{ border: 1px solid {_BORDER}; border-radius: 4px; }}
QToolTip {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY};
    border: 1px solid {_BORDER}; border-radius: 4px; font-size: 9px; }}
"""

_LIGHT_STYLE = """
QMainWindow {{ background: #f3f3f3; color: #242424; }}
QWidget {{ color: #242424; font-family: "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QTextEdit, QLineEdit, QComboBox {{ background: #fff; color: #242424;
    border: 1px solid #ccc; border-radius: 4px; }}
QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border-color: #007acc; }}
QListWidget {{ background: #fff; border: none; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: #e8e8e8; }}
QListWidget::item:selected {{ background: #007acc; color: #fff; }}
QPushButton {{ background: #007acc; color: #fff; border: none;
    padding: 6px 12px; border-radius: 4px; font-weight: 700; }}
QPushButton:hover {{ background: #0062a3; }}
QPushButton:pressed {{ background: #004d80; }}
QStatusBar {{ background: #e8e8e8; color: #686868; border-top: 1px solid #ccc; }}
QMenuBar {{ background: #e8e8e8; color: #242424; spacing: 6px;
    border-bottom: 1px solid #ccc; }}
QMenuBar::item:selected {{ background: #007acc; }}
QMenuBar::item:hover {{ background: #d6e4f0; }}
QDialog {{ background: #f3f3f3; color: #242424; }}
QGroupBox {{ border: 1px solid #ccc; border-radius: 6px; margin-top: 12px;
    padding-top: 8px; font-weight: 700; }}
QTabBar::tab {{ background: #fff; color: #686868;
    padding: 6px 12px; border: 1px solid #ccc; border-bottom: none; }}
QTabBar::tab:selected {{ background: #007acc; color: #fff; }}
QTabWidget::pane {{ border: 1px solid #ccc; border-radius: 4px; }}
"""

_GREY_EMERALD_STYLE = f"""
QMainWindow {{ background: {_GRAPHITE_BG}; color: {_TEXT_PRIMARY}; }}
QWidget {{ color: {_TEXT_PRIMARY}; font-family: "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QTextEdit, QLineEdit, QComboBox {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY};
    border: 1px solid {_BORDER}; border-radius: 4px; }}
QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border-color: {_EMERALD}; }}
QListWidget {{ background: {_GRAPHITE_SIDEBAR}; border: none; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {_GRAPHITE_CARD}; }}
QListWidget::item:selected {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; }}
QPushButton {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; border: none;
    padding: 6px 12px; border-radius: 4px; font-weight: 700; }}
QPushButton:hover {{ background: {_EMERALD_HOVER}; }}
QPushButton:pressed {{ background: {_EMERALD_SUCCESS}; }}
QPushButton#secondary_button {{ background: transparent; color: {_TEXT_MUTED};
    border: 1px solid {_BORDER_SIDEBAR}; }}
QPushButton#secondary_button:hover {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY}; }}
QStatusBar {{ background: {_GRAPHITE_CARD}; color: {_TEXT_SECONDARY}; border-top: 1px solid {_BORDER}; }}
QMenuBar {{ background: {_GRAPHITE_SIDEBAR}; color: {_TEXT_PRIMARY}; spacing: 6px;
    border-bottom: 1px solid {_BORDER}; }}
QMenuBar::item:selected {{ background: {_EMERALD}; }}
QMenuBar::item:hover {{ background: {_GRAPHITE_CARD}; }}
QToolBar {{ background: {_GRAPHITE_SIDEBAR}; border: none; spacing: 6px; }}
QSplitter::handle {{ background-color: {_BORDER}; }}
QDialog {{ background: {_GRAPHITE_BG}; color: {_TEXT_PRIMARY}; }}
QGroupBox {{ border: 1px solid {_BORDER}; border-radius: 6px; margin-top: 12px;
    padding-top: 8px; font-weight: 700; }}
QGroupBox::title {{ color: {_EMERALD_TEXT}; padding-left: 8px; }}
QTabBar::tab {{ background: {_GRAPHITE_CARD}; color: {_TEXT_SECONDARY};
    padding: 6px 12px; border: 1px solid {_BORDER}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; }}
QTabWidget::pane {{ border: 1px solid {_BORDER}; border-radius: 4px; }}
QToolTip {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY};
    border: 1px solid {_BORDER}; border-radius: 4px; font-size: 9px; }}
"""

_CYBER_STYLE = """
QMainWindow {{ background: #0d1117; color: #c9d1d9; }}
QWidget {{ color: #c9d1d9; font-family: "Segoe UI", Arial, sans-serif; font-size: 12pt; }}
QTextEdit, QLineEdit, QComboBox {{ background: #161b22; color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 4px; }}
QTextEdit:focus, QLineEdit:focus, QComboBox:focus {{ border-color: #2196f3; }}
QListWidget {{ background: #161b22; border: none; }}
QListWidget::item {{ padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: #1f2428; }}
QListWidget::item:selected {{ background: #2196f3; color: #c9d1d9; }}
QPushButton {{ background: #2196f3; color: #0d1117; border: none;
    padding: 6px 12px; border-radius: 4px; font-weight: 700; }}
QPushButton:hover {{ background: #388bfd; }}
QPushButton:pressed {{ background: #1d73b8; }}
QStatusBar {{ background: #161b22; color: #8b949e; border-top: 1px solid #30363d; }}
QMenuBar {{ background: #161b22; color: #c9d1d9; spacing: 6px;
    border-bottom: 1px solid #30363d; }}
QMenuBar::item:selected {{ background: #2196f3; }}
QMenuBar::item:hover {{ background: #1f2428; }}
QDialog {{ background: #0d1117; color: #c9d1d9; }}
QGroupBox {{ border: 1px solid #30363d; border-radius: 6px; margin-top: 12px;
    padding-top: 8px; font-weight: 700; }}
QTabBar::tab {{ background: #161b22; color: #8b949e;
    padding: 6px 12px; border: 1px solid #30363d; border-bottom: none; }}
QTabBar::tab:selected {{ background: #2196f3; color: #c9d1d9; }}
QTabWidget::pane {{ border: 1px solid #30363d; border-radius: 4px; }}
"""

_STYLES: dict[ThemeName, str] = {
    "dark": _DARK_STYLE,
    "light": _LIGHT_STYLE,
    "cyber": _CYBER_STYLE,
    "grey_emerald": _GREY_EMERALD_STYLE,
}


class ThemeManager:
    """Applies and persists Qt stylesheet themes using the Graphite + Emerald palette."""

    def __init__(self, app: QApplication, initial_theme: ThemeName = "grey_emerald") -> None:
        self._app = app
        self._theme: ThemeName = initial_theme
        self.apply(initial_theme)

    def apply(self, theme: ThemeName) -> None:
        if theme not in _STYLES:
            raise ValueError(f"Unknown theme: {theme}")
        self._app.setStyleSheet(_STYLES[theme])
        self._theme = theme
