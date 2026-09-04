"""QSS builder — generiše stylesheet-ove iz design tokens-a.

Nijedan QSS string ovde ne sadrži hardkodirane hex vrednosti; sve dolazi
iz ``ui.design.tokens``. Selektori prate objectName konvencije iz
workspace prototipa (#topbar, #sidebar, #nav_button, #primary_button...).
"""

from __future__ import annotations

from ui.design.tokens import FONT_FAMILY, Palette


def _base(p: Palette) -> str:
    """Globalni base stylesheet za dati režim palete."""
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    outline: none;
}}
QMainWindow, QWidget#page_root {{
    background: {p.surface};
    color: {p.text_primary};
}}
QLabel {{
    background: transparent;
    color: {p.text_primary};
}}
QLineEdit, QTextEdit, QPlainTextEdit {{
    background: {p.surface_input};
    color: {p.text_primary};
    border: 1px solid {p.border_input};
    border-radius: {7}px;
    padding: 8px 10px;
    selection-background-color: {p.emerald};
    selection-color: {p.text_on_primary};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1px solid {p.emerald};
}}
QComboBox {{
    background: {p.surface_input};
    color: {p.text_primary};
    border: 1px solid {p.border_input};
    border-radius: {7}px;
    padding: 6px 10px;
}}
QComboBox:hover {{
    border: 1px solid {p.emerald};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: {p.surface_card};
    color: {p.text_primary};
    border: 1px solid {p.border};
    selection-background-color: {p.tint(0.35)};
    selection-color: {p.text_primary};
}}
QCheckBox, QRadioButton {{
    background: transparent;
    color: {p.text_secondary};
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.border_input};
    border-radius: 4px;
    background: {p.surface_input};
}}
QCheckBox::indicator:checked {{
    background: {p.emerald};
    border: 1px solid {p.emerald};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.surface_card};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.border};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {p.surface_card};
    border-radius: 5px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}
QScrollBar::add-page, QScrollBar::sub-page {{
    background: transparent;
}}
QToolTip {{
    background: {p.surface_card};
    color: {p.text_primary};
    border: 1px solid {p.border};
    padding: 6px;
}}
"""


def shell_qss(p: Palette) -> str:
    """QSS za AppShell strukturu (topbar, sidebar, context panel, stranice)."""
    return f"""
/* ---------------- Topbar ---------------- */
QFrame#topbar {{
    background: {p.surface};
    border: none;
    border-bottom: 1px solid {p.border};
}}
QLabel#topbar_title {{
    color: {p.text_primary};
    font-size: 12pt;
    font-weight: 600;
}}
QLabel#status_local {{
    color: {p.emerald_text};
    font-weight: 600;
}}
QPushButton#topbar_button {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 6px 10px;
    color: {p.text_secondary};
    font-size: 12pt;
}}
QPushButton#topbar_button:hover {{
    background: {p.surface_card};
    color: {p.text_primary};
}}

/* ---------------- Sidebar ---------------- */
QFrame#sidebar {{
    background: {p.surface_dark};
    border: none;
    border-right: 1px solid {p.border};
}}
QLabel#sidebar_assistant_name {{
    color: {p.emerald_text};
    font-size: 13pt;
    font-weight: 600;
    background: transparent;
}}
QLabel#sidebar_subtitle {{
    color: {p.text_secondary};
    background: transparent;
}}
QLabel#sidebar_section {{
    color: {p.text_muted};
    font-size: 8pt;
    font-weight: 700;
    background: transparent;
}}
QPushButton#nav_button {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 10px 12px;
    color: {p.text_secondary};
    font-size: 10pt;
    text-align: left;
}}
QPushButton#nav_button:hover {{
    background: {p.surface_card};
    color: {p.text_primary};
}}
QPushButton#nav_button:checked {{
    background: {p.tint(0.12)};
    color: {p.emerald_text};
    font-weight: 600;
}}
QPushButton#new_conversation {{
    background: {p.tint(0.10)};
    border: 1px solid {p.tint(0.25)};
    border-radius: 6px;
    padding: 10px 12px;
    color: {p.emerald_text};
    font-weight: 600;
    text-align: left;
}}
QPushButton#new_conversation:hover {{
    background: {p.tint(0.16)};
}}

/* ---------------- Context panel ---------------- */
QFrame#context_panel {{
    background: {p.surface_dark};
    border: none;
    border-left: 1px solid {p.border};
}}
QLabel#context_section_title {{
    color: {p.text_muted};
    font-size: 8pt;
    font-weight: 700;
}}
QLabel#context_value {{
    color: {p.text_primary};
    background: transparent;
}}
QLabel#context_privacy {{
    color: {p.emerald_text};
    background: transparent;
}}

/* ---------------- Stranice ---------------- */
QLabel#page_title {{
    color: {p.text_primary};
    font-size: 22pt;
    font-weight: 600;
    background: transparent;
}}
QLabel#page_subtitle {{
    color: {p.text_secondary};
    background: transparent;
}}
QLabel#section_title {{
    color: {p.text_primary};
    font-size: 12pt;
    font-weight: 600;
    background: transparent;
}}

/* ---------------- Kartice ---------------- */
QFrame#card, QFrame#assistant_card {{
    background: {p.surface_card};
    border: 1px solid {p.border};
    border-radius: 10px;
}}
QFrame#card:hover {{
    border: 1px solid {p.emerald};
}}
QLabel#card_title {{
    color: {p.text_muted};
    font-size: 8pt;
    font-weight: 700;
    background: transparent;
}}
QLabel#card_value {{
    color: {p.text_primary};
    font-weight: 600;
    background: transparent;
}}
QLabel#card_detail {{
    color: {p.text_secondary};
    background: transparent;
}}

/* ---------------- Dugmad ---------------- */
QPushButton#primary_button {{
    background: {p.emerald};
    color: {p.text_on_primary};
    border: 1px solid {p.emerald};
    border-radius: 6px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton#primary_button:hover {{
    background: {p.emerald_hover};
    border: 1px solid {p.emerald_hover};
}}
QPushButton#primary_button:disabled {{
    background: {p.surface_card};
    color: {p.text_muted};
    border: 1px solid {p.border};
}}
QPushButton#secondary_button {{
    background: transparent;
    color: {p.text_secondary};
    border: 1px solid {p.border_input};
    border-radius: 6px;
    padding: 9px 18px;
}}
QPushButton#secondary_button:hover {{
    background: {p.surface_card};
    color: {p.text_primary};
}}
QPushButton#danger_button:hover {{
    border: 1px solid {p.error};
    color: {p.error};
}}
"""


def buttons_qss(p: Palette) -> str:
    """Samo dugmad — za dijaloge/stranice koje ne koriste ceo shell_qss."""
    return f"""
QPushButton#primary_button {{
    background: {p.emerald};
    color: {p.text_on_primary};
    border: 1px solid {p.emerald};
    border-radius: 6px;
    padding: 9px 18px;
    font-weight: 600;
}}
QPushButton#primary_button:hover {{
    background: {p.emerald_hover};
}}
QPushButton#primary_button:disabled {{
    background: {p.surface_card};
    color: {p.text_muted};
    border: 1px solid {p.border};
}}
QPushButton#secondary_button {{
    background: transparent;
    color: {p.text_secondary};
    border: 1px solid {p.border_input};
    border-radius: 6px;
    padding: 9px 18px;
}}
QPushButton#secondary_button:hover {{
    background: {p.surface_card};
    color: {p.text_primary};
}}
"""


def chat_qss(p: Palette) -> str:
    """Chat stranica — poruke, capability dugmad, input red."""
    return f"""
QTextEdit#chat_view {{
    background: {p.surface};
    border: none;
}}
QFrame#chat_header {{
    background: {p.surface};
    border: none;
    border-bottom: 1px solid {p.border};
}}
QLabel#chat_assistant_name {{
    color: {p.text_primary};
    font-size: 12pt;
    font-weight: 600;
}}
QPushButton#capability_button {{
    background: {p.surface_card};
    border: 1px solid {p.border};
    border-radius: 6px;
    padding: 6px 12px;
    color: {p.text_secondary};
}}
QPushButton#capability_button:hover {{
    border: 1px solid {p.emerald};
    color: {p.text_primary};
}}
QPushButton#capability_button:disabled {{
    color: {p.text_muted};
}}
QPushButton#send_button {{
    background: {p.emerald};
    color: {p.text_on_primary};
    border: 1px solid {p.emerald};
    border-radius: 7px;
    min-width: 45px;
    min-height: 38px;
    font-weight: 700;
}}
QPushButton#send_button:hover {{
    background: {p.emerald_hover};
}}
"""


def wizard_qss(p: Palette) -> str:
    """Wizard/installer ekrani — koristi INSTALLER paletu."""
    return f"""
QWizard {{
    background: {p.surface};
}}
QFrame#wizard_sidebar {{
    background: {p.surface_dark};
    border: none;
    border-right: 1px solid {p.border_soft};
}}
QLabel#wizard_step_default {{
    color: {p.text_muted};
    background: transparent;
    font-size: 12px;
    padding: 9px 10px;
    border-radius: 7px;
}}
QLabel#wizard_step_completed {{
    color: {p.text_secondary};
    background: transparent;
    font-size: 12px;
    padding: 9px 10px;
    border-radius: 7px;
}}
QLabel#wizard_step_current {{
    color: {p.emerald_text};
    background: {p.tint(0.12)};
    font-size: 12px;
    padding: 9px 10px;
    border-radius: 7px;
    font-weight: 600;
}}
QFrame#banner {{
    background: {p.tint(0.08)};
    border: 1px solid {p.tint(0.22)};
    border-radius: 8px;
}}
QFrame#banner_warning {{
    background: {p.warning_tint(0.07)};
    border: 1px solid {p.warning_tint(0.18)};
    border-radius: 8px;
}}
QFrame#banner_error {{
    background: {p.error_tint(0.07)};
    border: 1px solid {p.error_tint(0.22)};
    border-radius: 8px;
}}
QLabel#badge {{
    background: {p.tint(0.18)};
    color: {p.emerald_text};
    font-size: 8px;
    font-weight: 700;
    padding: 3px 8px;
    border-radius: 4px;
}}
QProgressBar#storage_bar {{
    background: {p.border};
    border: none;
    border-radius: 2px;
    max-height: 4px;
    text-align: center;
}}
QProgressBar#storage_bar::chunk {{
    background: {p.emerald};
    border-radius: 2px;
}}
QProgressBar#install_progress {{
    background: {p.border};
    border: none;
    border-radius: 4px;
    max-height: 7px;
    text-align: center;
    color: {p.emerald_text};
}}
QProgressBar#install_progress::chunk {{
    background: {p.emerald};
    border-radius: 4px;
}}
"""


def build_full_qss(palette_name: str) -> str:
    """Kompletan QSS za dati režim ('workspace' | 'installer')."""
    from ui.design.tokens import get_palette

    p = get_palette(palette_name)
    return "\n".join([_base(p), shell_qss(p), chat_qss(p), wizard_qss(p)])
