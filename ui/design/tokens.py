"""Design tokens — the single source of truth for project colors.

All values are extracted from the official previews in ``design_previews/``
(documentation: docs/design_system.md). No hex may be hardcoded
outside this module.

Two palette modes:
- INSTALLER (darker, greener) -> wizard / installation flow
- WORKSPACE (lighter)          -> main application (AppShell)
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Shared — semantics
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    """One mode of the Graphite + Emerald theme."""

    name: str
    # Surfaces
    surface: str          # main window background
    surface_dark: str     # sidebar / context panel
    surface_card: str     # cards
    surface_input: str    # input fields
    # Borders
    border: str           # main border
    border_soft: str      # subtle borders (sidebar, bottom bars)
    border_input: str     # inputs / secondary buttons
    # Emerald accents
    emerald: str          # primary color (buttons, accents)
    emerald_hover: str    # primary hover
    emerald_text: str     # emerald text (statuses, current step)
    # Text
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_primary: str  # text on the primary button
    # Status
    success: str
    success_bg: str
    success_text: str
    warning: str
    error: str
    # Emerald tint helper (rgba strings are created by the tint() function)
    _emerald_rgb: tuple[int, int, int] = (29, 138, 104)

    def tint(self, alpha: float) -> str:
        """Returns an rgba() emerald tint with the given alpha (0-1)."""
        r, g, b = self._emerald_rgb
        return f"rgba({r}, {g}, {b}, {alpha})"

    def success_tint(self, alpha: float) -> str:
        return f"rgba(69, 184, 138, {alpha})"

    def warning_tint(self, alpha: float) -> str:
        return f"rgba(214, 162, 74, {alpha})"

    def error_tint(self, alpha: float) -> str:
        return f"rgba(217, 101, 101, {alpha})"


# ---------------------------------------------------------------------------
# WORKSPACE mode (main application) — from assistant_workspace_preview.py
# ---------------------------------------------------------------------------

WORKSPACE = Palette(
    name="workspace",
    surface="#202326",
    surface_dark="#181A1D",
    surface_card="#292D31",
    surface_input="#292D31",
    border="#373C41",
    border_soft="#373C41",
    border_input="#373C41",
    emerald="#27C48A",
    emerald_hover="#1E9D70",
    emerald_text="#27C48A",
    text_primary="#F1F3F4",
    text_secondary="#A8AFB5",
    text_muted="#6E757B",
    text_on_primary="#101513",
    success="#45B88A",
    success_bg="#245846",
    success_text="#7DE0B7",
    warning="#D9B44A",
    error="#E35D6A",
    _emerald_rgb=(39, 196, 138),
)

# ---------------------------------------------------------------------------
# INSTALLER mode (wizard) — from the wizard HTML preview + official_theme
# ---------------------------------------------------------------------------

INSTALLER = Palette(
    name="installer",
    surface="#151819",
    surface_dark="#111516",
    surface_card="#1C2221",
    surface_input="#151819",
    border="#29302E",
    border_soft="#202624",
    border_input="#343C39",
    emerald="#1D8A68",
    emerald_hover="#249E78",
    emerald_text="#62C7A3",
    text_primary="#EDF3F0",
    text_secondary="#A5AFAB",
    text_muted="#737D79",
    text_on_primary="#FFFFFF",
    success="#45B88A",
    success_bg="#245846",
    success_text="#7DE0B7",
    warning="#D6A24A",
    error="#D96565",
    _emerald_rgb=(29, 138, 104),
)

# Page background outside the window (only the wizard screen uses it)
INSTALLER_PAGE_BG = "#0D1010"

# Wizard-specific extras (used by components per the INSTALLER palette)
INSTALLER_CARD_DARK = "#191F1E"      # darker card (feature grid, model-stats)
INSTALLER_BOTTOM_BORDER = "#252B29"  # wizard bottom bar border
INSTALLER_DISABLED_BG = "#202624"    # disabled button
INSTALLER_DISABLED_TEXT = "#59625F"
INSTALLER_HOVER_BG = "#29302E"       # secondary button hover
INSTALLER_LOGO_TEXT = "#E8FFF6"

# ---------------------------------------------------------------------------
# Registry and helpers
# ---------------------------------------------------------------------------

PALETTES: dict[str, Palette] = {
    "workspace": WORKSPACE,
    "installer": INSTALLER,
}

DEFAULT_WORKSPACE = WORKSPACE
DEFAULT_INSTALLER = INSTALLER


def get_palette(name: str) -> Palette:
    """Returns the palette by name ('workspace' | 'installer')."""
    try:
        return PALETTES[name]
    except KeyError:
        return WORKSPACE


# Typography — Segoe UI throughout the design
FONT_FAMILY = "Segoe UI"

# Sizes (pt) for the workspace (per assistant_workspace_preview.py)
# Values were raised for readability (10pt -> 11pt base text per
# user request #6).
FONT_PAGE_TITLE = 22
FONT_ASSISTANT_NAME = 16
FONT_SECTION_TITLE = 12
FONT_BODY = 11

# Radius values from the preview
RADIUS_CARD = 10
RADIUS_ASSISTANT_CARD = 14
RADIUS_BUTTON = 6
RADIUS_INPUT = 7
RADIUS_BADGE = 5
RADIUS_NAV = 6
