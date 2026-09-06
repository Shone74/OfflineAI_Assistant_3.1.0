"""Theme manager — applies QSS from the design system (ui/design).

The official theme is "Graphite + Emerald" in two modes (docs/design_system.md):
- ``grey_emerald`` — WORKSPACE mode (main application; lighter variant)
- ``installer``     — INSTALLER mode (wizard; darker variant)
- ``dark``         — alias for the INSTALLER mode (legacy compatibility)

The legacy themes ``light`` and ``cyber`` were removed in favor of the official design.

The active theme is persisted in ``settings.json`` under ``ui.theme``.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QApplication

from ui.design import INSTALLER, WORKSPACE, Palette
from ui.design.qss import build_full_qss

ThemeName = Literal["dark", "grey_emerald", "installer", "workspace"]

# Map of theme name -> palette mode (design tokens)
_THEME_PALETTE: dict[str, str] = {
    "dark": "installer",
    "grey_emerald": "workspace",
    "installer": "installer",
    "workspace": "workspace",
}

# Cache of generated stylesheets
_QSS_CACHE: dict[str, str] = {}


def _stylesheet_for(theme: str) -> str:
    palette_name = _THEME_PALETTE.get(theme, "workspace")
    if palette_name not in _QSS_CACHE:
        _QSS_CACHE[palette_name] = build_full_qss(palette_name)
    return _QSS_CACHE[palette_name]


def get_theme_palette(theme: str) -> Palette:
    """Returns the Palette object (from tokens) for the given theme."""
    return WORKSPACE if _THEME_PALETTE.get(theme) == "workspace" else INSTALLER


class ThemeManager:
    """Applies and persists Qt stylesheets from the design system."""

    def __init__(self, app: QApplication, initial_theme: ThemeName = "grey_emerald") -> None:
        self._app = app
        self._theme: ThemeName = initial_theme
        self.apply(initial_theme)

    def apply(self, theme: ThemeName) -> None:
        if theme not in _THEME_PALETTE:
            # Legacy names ("light", "cyber") are mapped to the official theme
            theme = "grey_emerald"
        self._app.setStyleSheet(_stylesheet_for(theme))
        self._theme = theme  # type: ignore[assignment]

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def palette(self) -> Palette:
        """Active Palette (tokens) — for components that need colors directly."""
        return get_theme_palette(self._theme)
