"""Design tokens — jedini izvor istine za boje projekta.

Sve vrednosti su izvucene iz zvaničnih preview-a u ``Izgled Aplikaccije/``
(dokumentacija: docs/design_system.md). Nijedan hex ne sme biti hardkodiran
van ovog modula.

Dva režima palete:
- INSTALLER (tamniji, zeleniji)  -> wizard / instalacioni tok
- WORKSPACE (svetliji)           -> glavna aplikacija (AppShell)
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Shared — semantika
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Palette:
    """Jedan režim Graphite + Emerald teme."""

    name: str
    # Povrsine
    surface: str          # glavni background prozora
    surface_dark: str     # sidebar / context panel
    surface_card: str     # kartice
    surface_input: str    # input polja
    # Borderi
    border: str           # glavni border
    border_soft: str      # subtle borderi (sidebar, bottom trake)
    border_input: str     # inputi / sekundarne dugmad
    # Emerald akcenti
    emerald: str          # primarna boja (dugmad, akcenti)
    emerald_hover: str    # hover primarne
    emerald_text: str     # emerald tekst (statusi, current step)
    # Tekst
    text_primary: str
    text_secondary: str
    text_muted: str
    text_on_primary: str  # tekst na primarnom dugmetu
    # Status
    success: str
    success_bg: str
    success_text: str
    warning: str
    error: str
    # Emerald tint helper (rgba stringovi se prave funkcijom tint())
    _emerald_rgb: tuple[int, int, int] = (29, 138, 104)

    def tint(self, alpha: float) -> str:
        """Vraca rgba() emerald tint sa datom alfa (0-1)."""
        r, g, b = self._emerald_rgb
        return f"rgba({r}, {g}, {b}, {alpha})"

    def success_tint(self, alpha: float) -> str:
        return f"rgba(69, 184, 138, {alpha})"

    def warning_tint(self, alpha: float) -> str:
        return f"rgba(214, 162, 74, {alpha})"

    def error_tint(self, alpha: float) -> str:
        return f"rgba(217, 101, 101, {alpha})"


# ---------------------------------------------------------------------------
# WORKSPACE režim (glavna aplikacija) — iz assistant_workspace_preview.py
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
# INSTALLER režim (wizard) — iz wizard HTML preview-a + official_theme
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

# Page background izvan prozora (samo wizard ekran koristi)
INSTALLER_PAGE_BG = "#0D1010"

# Wizard-specific sitnice (koriste ih components prema INSTALLER paleti)
INSTALLER_CARD_DARK = "#191F1E"      # tamnija kartica (feature grid, model-stats)
INSTALLER_BOTTOM_BORDER = "#252B29"  # border donje trake wizard-a
INSTALLER_DISABLED_BG = "#202624"    # disabled dugme
INSTALLER_DISABLED_TEXT = "#59625F"
INSTALLER_HOVER_BG = "#29302E"       # hover sekundarne dugmadi
INSTALLER_LOGO_TEXT = "#E8FFF6"

# ---------------------------------------------------------------------------
# Registar i helperi
# ---------------------------------------------------------------------------

PALETTES: dict[str, Palette] = {
    "workspace": WORKSPACE,
    "installer": INSTALLER,
}

DEFAULT_WORKSPACE = WORKSPACE
DEFAULT_INSTALLER = INSTALLER


def get_palette(name: str) -> Palette:
    """Vraća paletu po imenu ('workspace' | 'installer')."""
    try:
        return PALETTES[name]
    except KeyError:
        return WORKSPACE


# Typography — Segoe UI kroz ceo dizajn
FONT_FAMILY = "Segoe UI"

# Velicine (pt) za workspace (prema assistant_workspace_preview.py)
FONT_PAGE_TITLE = 22
FONT_ASSISTANT_NAME = 16
FONT_SECTION_TITLE = 12
FONT_BODY = 10

# Radius vrednosti iz preview-a
RADIUS_CARD = 10
RADIUS_ASSISTANT_CARD = 14
RADIUS_BUTTON = 6
RADIUS_INPUT = 7
RADIUS_BADGE = 5
RADIUS_NAV = 6
