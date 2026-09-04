"""Theme manager — primenjuje QSS iz dizajn sistema (ui/design).

Zvanična tema je "Graphite + Emerald" u dva režima (docs/design_system.md):
- ``grey_emerald`` — WORKSPACE režim (glavna aplikacija; svetlija varijanta)
- ``installer``     — INSTALLER režim (wizard; tamnija varijanta)
- ``dark``         — alias za INSTALLER režim (legacy kompatibilnost)

Legacy teme ``light`` i ``cyber`` su uklonjene u korist zvaničnog dizajna.

Aktivna tema se perzistira u ``settings.json`` pod ``ui.theme``.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import QApplication

from ui.design import INSTALLER, WORKSPACE, Palette
from ui.design.qss import build_full_qss

ThemeName = Literal["dark", "grey_emerald", "installer", "workspace"]

# Mapa imena teme -> režim palete (design tokens)
_THEME_PALETTE: dict[str, str] = {
    "dark": "installer",
    "grey_emerald": "workspace",
    "installer": "installer",
    "workspace": "workspace",
}

# Keš generisanih stylesheet-ova
_QSS_CACHE: dict[str, str] = {}


def _stylesheet_for(theme: str) -> str:
    palette_name = _THEME_PALETTE.get(theme, "workspace")
    if palette_name not in _QSS_CACHE:
        _QSS_CACHE[palette_name] = build_full_qss(palette_name)
    return _QSS_CACHE[palette_name]


def get_theme_palette(theme: str) -> Palette:
    """Vraća Palette objekat (iz tokens) za datu temu."""
    return WORKSPACE if _THEME_PALETTE.get(theme) == "workspace" else INSTALLER


class ThemeManager:
    """Applies and persists Qt stylesheets from the design system."""

    def __init__(self, app: QApplication, initial_theme: ThemeName = "grey_emerald") -> None:
        self._app = app
        self._theme: ThemeName = initial_theme
        self.apply(initial_theme)

    def apply(self, theme: ThemeName) -> None:
        if theme not in _THEME_PALETTE:
            # Legacy imena ("light", "cyber") mapiramo na zvaničnu temu
            theme = "grey_emerald"
        self._app.setStyleSheet(_stylesheet_for(theme))
        self._theme = theme  # type: ignore[assignment]

    @property
    def theme(self) -> str:
        return self._theme

    @property
    def palette(self) -> Palette:
        """Aktivna Palette (tokens) — za komponente kojima trebaju boje direktno."""
        return get_theme_palette(self._theme)
