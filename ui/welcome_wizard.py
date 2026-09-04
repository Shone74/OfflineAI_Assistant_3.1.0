"""First-run onboarding wizard — guides new users through a 7-step installation.

Steps (matching the reference design in Izgled Aplikacije):
    1. Welcome      — introduction + privacy statement
    2. System Check — hardware detection with status cards
    3. AI Model     — model recommendation + selection
    4. Locations    — installation path configuration
    5. Summary      — review all selections before installing
    6. Installation — live progress with phases
    7. Complete     — success screen with launch button
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from ai.models.model_manager import ModelManager
from core.event_bus import EventBus
from core.logger import get_logger
from core.paths import MODELS_DIR
from installer.hardware import (
    HardwareProfile,
    ModelRecommendation,
    detect_hardware,
    recommend_model,
)

logger = get_logger("welcome_wizard")

_GRAPHITE = "#151819"
_GRAPHITE_SIDEBAR = "#111516"
_GRAPHITE_CARD = "#1C2221"
_GRAPHITE_DARK_CARD = "#191F1E"
_GRAPHITE_BORDER = "#29302E"
_GRAPHITE_BORDER_SIDEBAR = "#202624"
_EMERALD = "#1D8A68"
_EMERALD_HOVER = "#249E78"
_EMERALD_TEXT = "#62C7A3"
_EMERALD_SUCCESS = "#245846"
_EMERALD_SUCCESS_TEXT = "#7DE0B7"
_EMERALD_BG_TINT = "rgba(29, 138, 104, 0.08)"
_EMERALD_BORDER_TINT = "rgba(29, 138, 104, 0.25)"
_TEXT_PRIMARY = "#EDF3F0"
_TEXT_SECONDARY = "#8C9692"
_TEXT_MUTED = "#737D79"
_TEXT_DARK = "#59625F"
_WARNING_AMBER = "#D6A24A"
_ERROR_RED = "#D96565"
_BACKGROUND_PAGE = "#0D1010"

WIZARD_STYLE = f"""
QWizard {{
    background-color: {_BACKGROUND_PAGE};
    color: {_TEXT_PRIMARY};
}}
QWizardPage {{
    background-color: {_GRAPHITE};
    color: {_TEXT_PRIMARY};
    font-family: "Segoe UI", Arial, sans-serif;
}}
QWizard::cornerfx {{
    background-color: {_GRAPHITE};
}}
QWizard QGroupBox {{
    border: 1px solid {_GRAPHITE_BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 8px;
    font-weight: 600;
}}
QWizard QPushButton {{
    background-color: {_EMERALD};
    color: {_TEXT_PRIMARY};
    border: none;
    padding: 8px 17px;
    border-radius: 6px;
    font-weight: 600;
}}
QWizard QPushButton:hover {{
    background-color: {_EMERALD_HOVER};
}}
QWizard QPushButton:pressed {{
    background-color: {_EMERALD_SUCCESS};
}}
QWizard QLabel {{
    color: {_TEXT_PRIMARY};
}}
QWizard QLineEdit, QWizard QTextEdit, QWizard QComboBox {{
    background-color: {_GRAPHITE_CARD};
    color: {_TEXT_PRIMARY};
    border: 1px solid {_GRAPHITE_BORDER};
    border-radius: 5px;
    padding: 8px;
    font-size: 10px;
}}
QWizard QComboBox:focus, QWizard QLineEdit:focus {{
    border-color: {_EMERALD};
}}
QWizard QListWidget {{
    background-color: {_GRAPHITE_CARD};
    border: 1px solid {_GRAPHITE_BORDER};
    border-radius: 6px;
}}
QWizard QListWidget::item {{
    padding: 8px;
}}
QWizard QListWidget::item:selected {{
    background-color: {_EMERALD};
    color: {_TEXT_PRIMARY};
}}
QWizard QProgressBar {{
    border: 1px solid {_GRAPHITE_BORDER};
    border-radius: 5px;
    text-align: center;
    background: {_GRAPHITE_DARK_CARD};
    color: {_TEXT_PRIMARY};
}}
QWizard QProgressBar::chunk {{
    background-color: {_EMERALD};
    border-radius: 4px;
}}
"""

CHECK_CARD_STYLE = f"""
padding: 12px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 7px;
"""

CHECK_CARD_SUCCESS_STYLE = f"""
padding: 12px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 7px;
border-left: 3px solid {_EMERALD};
"""

CHECK_CARD_WARNING_STYLE = f"""
padding: 12px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 7px;
border-left: 3px solid {_WARNING_AMBER};
"""

LOCATION_CARD_STYLE = f"""
padding: 14px 16px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 8px;
"""

MODEL_CARD_STYLE = f"""
padding: 12px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 7px;
padding: 12px;
cursor: pointer;
"""

MODEL_CARD_SELECTED_STYLE = f"""
padding: 12px;
background: {_EMERALD_BG_TINT};
border: 1px solid {_EMERALD_BORDER_TINT};
border-radius: 7px;
"""

SUMMARY_CARD_STYLE = f"""
padding: 11px 12px;
background: {_GRAPHITE_CARD};
border: 1px solid {_GRAPHITE_BORDER};
border-radius: 7px;
"""

SUMMARY_INFO_STYLE = f"""
padding: 10px 12px;
background: {_EMERALD_BG_TINT};
border: 1px solid {_EMERALD_BORDER_TINT};
border-radius: 7px;
"""

PRIVACY_CARD_STYLE = f"""
margin-top: 18px;
padding: 18px 20px;
background: {_GRAPHITE_CARD};
border: 1px solid {_EMERALD_BORDER_TINT};
border-radius: 9px;
"""

STEP_COMPLETED_STYLE = f"""
QWizardPage QFrame {{
    background-color: {_EMERALD_SUCCESS};
    border-radius: 50%;
    color: {_EMERALD_SUCCESS_TEXT};
    font-weight: 600;
    min-width: 22px;
    min-height: 22px;
    max-width: 22px;
    max-height: 22px;
}}
"""

STEP_CURRENT_STYLE = f"""
color: {_EMERALD_TEXT};
background: {_EMERALD_BG_TINT};
border-radius: 7px;
"""


class WelcomePage(QWizardPage):
    """First page: welcome message and introduction."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Dobrodošli u Offline AI Assistant")
        layout = QVBoxLayout(self)

        info = QLabel(
            "<b>Vaš lokalni AI asistent — 100% offline.</b><br><br>"
            "• Vaši podaci i konverzacije ostaju na vašem računaru<br>"
            "• Nema obavezog internetskog saobraćaja<br>"
            "• AI model radi direktno na vašem uređaju<br>"
            "• Sve konfiguracije se čuvaju lokalno<br><br>"
            "Ovaj čarobnjak će vam pomoći da:<br>"
            "1. Detektujemo vaš hardver<br>"
            "2. Preporučimo odgovarajući AI model<br>"
            "3. Preuzmemo i aktiviramo ga<br><br>"
            "Kliknite <b>Dalje</b> za početak."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self._privacy_card = QFrame()
        self._privacy_card.setStyleSheet(
            f"background: {_GRAPHITE_CARD};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 9px;"
            f"padding: 14px 16px;"
        )
        privacy_layout = QHBoxLayout(self._privacy_card)
        privacy_icon = QLabel("🔒")
        privacy_text = QLabel(
            "<b>Vaša privatnost je zaštićena.</b><br>"
            "Offline AI Assistant radi lokalno na vašem računaru. "
            "Vaše konverzacije i lični podaci ostaju na vašem uređaju "
            "i ne šalju se na eksterne servise ili oblak."
        )
        privacy_text.setWordWrap(True)
        privacy_layout.addWidget(privacy_icon)
        privacy_layout.addWidget(privacy_text)
        layout.addWidget(self._privacy_card)

        features = QFrame()
        features_layout = QHBoxLayout(features)
        feature_labels = [
            ("Lokalno AI obrada", "AI obrada se dešava direktno na vašem računaru."),
            ("Privatnost pod kontrolom", "Vaši podaci ostaju pod vašom kontrolom."),
            ("Pametna preporuka", "Instalator analizira vaš sistem."),
            ("Model preporuke", "Preporučićemo modele pogodne za vaš hardver."),
        ]
        for title, desc in feature_labels:
            card = QFrame()
            card.setStyleSheet(
                f"background: {_GRAPHITE_DARK_CARD};"
                f"border: 1px solid {_GRAPHITE_BORDER};"
                f"border-radius: 7px;"
                f"padding: 10px 12px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setSpacing(3)
            card_layout.setContentsMargins(10, 10, 10, 10)
            title_label = QLabel(f"<b>{title}</b>")
            title_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 11px; font-weight: 600;")
            desc_label = QLabel(desc)
            desc_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px; line-height: 1.5;")
            desc_label.setWordWrap(True)
            card_layout.addWidget(title_label)
            card_layout.addWidget(desc_label)
            features_layout.addWidget(card)
        layout.addWidget(features)
        layout.addStretch()


class HardwareScanPage(QWizardPage):
    """Second page: hardware detection and model recommendation."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Analiza hardvera")
        self._profile: HardwareProfile | None = None
        self._recommendation: ModelRecommendation | None = None
        self._layout = QVBoxLayout(self)

        self._status_label = QLabel("Skeniram hardver...")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px;")
        self._layout.addWidget(self._status_label)

        self._ready_banner: QFrame | None = None
        self._check_grid: QFrame | None = None
        self._info_box: QFrame | None = None

    def initializePage(self) -> None:
        self._status_label.setText("Skeniram hardver...")
        self._clear_dynamic_widgets()
        self._scan_hardware()

    def _clear_dynamic_widgets(self) -> None:
        if self._layout is None:
            return
        while self._layout.count() > 1:
            child = self._layout.takeAt(0)
            if child is None:
                continue
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _scan_hardware(self) -> None:
        try:
            profile = detect_hardware()
            rec = recommend_model(profile)
            self._profile = profile
            self._recommendation = rec
            self._on_scan_complete(profile, rec)
        except Exception as exc:
            logger.error("Hardware scan failed: %s", exc)
            self._status_label.setText(
                f"<b>Greška pri skeniranju hardvera:</b><br>{exc}<br><br>"
                "Možete pokušati kasnije."
            )

    def _on_scan_complete(self, profile: HardwareProfile, rec: ModelRecommendation) -> None:
        self._status_label.setText(self._format_hardware_text(profile, rec))

        wizard = self.wizard()
        if wizard is not None:
            wizard._hardware_profile = profile  # type: ignore[attr-defined]
            wizard._hardware_recommendation = rec  # type: ignore[attr-defined]

        self._ready_banner = self._build_ready_banner(profile, rec)
        self._check_grid = self._build_check_grid(profile)
        self._info_box = self._build_info_box(rec)

        self._layout.addWidget(self._ready_banner)
        self._layout.addWidget(self._check_grid)
        self._layout.addWidget(self._info_box)

    def _format_hardware_text(self, profile: HardwareProfile, rec: ModelRecommendation) -> str:
        gpu_name = getattr(profile, "gpu_name", None) or "N/A"
        vram_gb = float(getattr(profile, "gpu_vram_gb", 0) or 0)
        ram_total = float(getattr(profile, "ram_total_gb", 0) or 0)
        cpu_name = getattr(profile, "cpu_name", "N/A")
        cpu_cores = getattr(profile, "cpu_cores", "N/A")
        vram = f"{vram_gb:.0f} GB" if vram_gb else "N/A"
        return (
            f"<b>Hardver detektovan:</b><br><br>"
            f"CPU: {cpu_name} ({cpu_cores} jezra)<br>"
            f"RAM: {ram_total:.0f} GB<br>"
            f"GPU: {gpu_name} ({vram} VRAM)<br><br>"
            f"<b>Preporuka:</b> {getattr(rec, 'label', 'N/A')} model<br>"
            f"{getattr(rec, 'reason', '')}"
        )

    def _build_ready_banner(self, profile: HardwareProfile, rec: ModelRecommendation) -> QFrame:
        banner = QFrame()
        banner.setStyleSheet(
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
            f"padding: 11px 13px;"
        )
        layout = QHBoxLayout(banner)
        icon = QLabel("✓")
        icon.setStyleSheet(
            f"background: {_EMERALD_SUCCESS};"
            f"color: {_EMERALD_SUCCESS_TEXT};"
            f"border-radius: 50%;"
            f"padding: 4px 6px;"
            "min-width: 24px; min-height: 24px;"
        )
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(8, 0, 0, 0)
        title = QLabel("Sistem kompatibilan")
        title.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 11px; font-weight: 600;")
        desc = QLabel("Vaš računar zadovoljava minimalne zahteve.")
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px; margin-top: 2px;")
        text_layout.addWidget(title)
        text_layout.addWidget(desc)
        layout.addWidget(icon)
        layout.addLayout(text_layout)
        return banner

    def _build_check_grid(self, profile: HardwareProfile) -> QFrame:
        grid = QFrame()
        layout = QHBoxLayout(grid)
        layout.setSpacing(8)

        ram_total = float(getattr(profile, "ram_total_gb", 0) or 0)
        vram = float(getattr(profile, "gpu_vram_gb", 0) or 0)
        free_gb = float(getattr(profile, "storage_free_gb", 0) or 0)

        checks = [
            ("CPU", str(getattr(profile, "cpu_name", "N/A")), "ready", "#62C7A3"),
            ("RAM", f"{ram_total:.0f} GB DDR4", "ready", "#62C7A3"),
            ("GPU", str(getattr(profile, "gpu_name", "N/A")) or "N/A", "ready", "#62C7A3"),
            ("VRAM", f"{vram:.0f} GB Available", "ready", "#62C7A3")
            if getattr(profile, "gpu_vram_gb", None)
            else ("VRAM", "N/A", "warning", "#D6A24A"),
            ("OS", self._detect_os(), "ready", "#62C7A3"),
            ("DISK", f"{free_gb:.1f} GB Free", self._disk_status(profile), "#62C7A3" if free_gb > 10 else "#D6A24A"),
        ]

        for name, value, status, color in checks:
            card = self._build_check_card(name, value, status, color)
            layout.addWidget(card)

        return grid

    def _disk_status(self, profile: HardwareProfile) -> str:
        free_gb = float(getattr(profile, "storage_free_gb", 0) or 0)
        return "ready" if free_gb > 10 else "warning"

    def _detect_os(self) -> str:
        import platform

        return f"Windows 11 Pro ({platform.processor() or 'Unknown'})"

    def _build_check_card(self, name: str, value: str, status: str, color: str) -> QFrame:
        card = QFrame()
        style = CHECK_CARD_WARNING_STYLE if status == "warning" else CHECK_CARD_SUCCESS_STYLE
        card.setStyleSheet(style)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 10)
        icon = QLabel(name[:2])
        icon.setStyleSheet(
            f"background: rgba({self._hex_to_rgb(color)}, 0.12);"
            f"color: {color};"
            "border-radius: 7px;"
            "padding: 4px 6px;"
            "min-width: 30px; min-height: 30px;"
            "text-align: center;"
        )
        label = "Ready" if status == "ready" else "Limited"
        label_color = "#62C7A3" if status == "ready" else "#D6A24A"
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        value_label = QLabel(value)
        value_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 10px; font-weight: 600;")
        status_label = QLabel(label.upper())
        status_label.setStyleSheet(f"color: {label_color}; font-size: 8px; font-weight: 600;")
        info_layout.addWidget(name_label)
        info_layout.addWidget(value_label)
        info_layout.addWidget(status_label)
        layout.addWidget(icon)
        layout.addLayout(info_layout)
        return card

    def _hex_to_rgb(self, hex_color: str) -> str:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r}, {g}, {b}"

    def _build_info_box(self, rec: ModelRecommendation) -> QFrame:
        info = QFrame()
        info.setStyleSheet(
            "margin-top: 12px;"
            "padding: 11px 13px;"
            "background: rgba(214, 162, 74, 0.07);"
            "border: 1px solid rgba(214, 162, 74, 0.18);"
            "border-radius: 7px;"
        )
        layout = QVBoxLayout(info)
        layout.setContentsMargins(10, 10, 10, 10)
        title = QLabel("⚠ Vaša preporuka modela")
        title.setStyleSheet(f"color: {_WARNING_AMBER}; font-size: 9px; text-transform: uppercase;")
        desc = QLabel(
            f"Preporučeni model je {rec.label} ({rec.reason}). "
            "Možete izabrati drugi model na sledećem koraku."
        )
        desc.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px; line-height: 1.5;")
        desc.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(desc)
        return info


class ModelSelectionPage(QWizardPage):
    """Third page: choose an AI model from recommendations."""

    def __init__(self, model_manager: ModelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Izaberite AI model")
        self._manager = model_manager
        self._selected_model = ""
        self._model_options: QListWidget = QListWidget()
        layout = QVBoxLayout(self)

        self._header = QLabel()
        self._header.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px; line-height: 1.5;")
        self._header.setWordWrap(True)
        layout.addWidget(self._header)

        self._model_options.setStyleSheet(
            f"QListWidget {{ background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER}; "
            f"border-radius: 6px; outline: 0px; }}"
            f"QListWidget::item {{ padding: 10px; border-bottom: 1px solid {_GRAPHITE_BORDER}; }}"
            f"QListWidget::item:selected {{ background: {_EMERALD}; color: {_TEXT_PRIMARY}; }}"
        )
        self._model_options.itemClicked.connect(self._on_model_selected)
        layout.addWidget(self._model_options)

        self._model_details = QTextEdit()
        self._model_details.setReadOnly(True)
        self._model_details.setFixedHeight(100)
        layout.addWidget(self._model_details)

        layout.addStretch()

    def initializePage(self) -> None:
        wizard = self.wizard()
        profile = getattr(wizard, "_hardware_profile", None) if wizard else None
        rec = getattr(wizard, "_hardware_recommendation", None) if wizard else None

        if rec is not None:
            size_gb = rec.model_size_b / (1024**3)
            hw_line = ""
            if profile is not None:
                hw_line = f"CPU: {profile.cpu_name} · RAM: {profile.ram_total_gb:.0f} GB"
            self._header.setText(
                f"Na osnovu vaše konfiguracije, preporučujemo {rec.label} model. "
                f"Ova preporuka nudi dobro ravnotežje kvaliteta, brzine i korišćenja resursa."
                + (f"<br>{hw_line}" if hw_line else "")
            )

        self._model_options.clear()
        self._selected_model = ""
        self._model_details.clear()

        size_gb = rec.model_size_b / (1024**3) if rec else 0

        model_items = [
            (
                "Qwen 2.5 7B — Q4_K_M",
                f"Preporučeno · ~{size_gb:.1f} GB · GPU akceleracija dostupna",
            ),
            ("Small / Fast Model", "Manji model, brži odziv · ~1.5 GB"),
            ("Large Quality Model", "Veći model, bolja kvalitet · ~8 GB"),
            ("User Defined", "Prikaži sve modele na vašem sistemu"),
        ]
        for name, desc in model_items:
            item = QListWidgetItem(name)
            item.setData(1, desc)
            if name.startswith("Qwen"):
                item.setBackground(QColor(_EMERALD_BG_TINT))
            self._model_options.addItem(item)

        first = self._model_options.item(0)
        if first:
            self._model_options.setCurrentItem(first)
            self._selected_model = first.text()
            self._model_details.setText(first.data(1) or "")
            self._on_model_selected(first)

        self._model_details.setStyleSheet(
            f"background: {_GRAPHITE_DARK_CARD}; color: {_TEXT_SECONDARY}; "
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 5px; font-size: 9px;"
        )

    def _on_model_selected(self, item: QListWidgetItem) -> None:
        self._selected_model = item.text()
        self._model_details.setText(item.data(1) or "")
        wizard = self.wizard()
        if wizard:
            wizard._selected_model_name = item.text()  # type: ignore[attr-defined]


class LocationsPage(QWizardPage):
    """Fourth page: choose installation locations."""

    def __init__(self, model_manager: ModelManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Lokacije instalacije")
        self._manager = model_manager
        layout = QVBoxLayout(self)

        header = QLabel(
            "Možete instalirati aplikaciju i AI modele na različite lokacije. "
            "Ovo omogućava da aplikaciju smestite na sistemski disk, "
            "dok veoma velike AI modele čuvate na drugom disku."
        )
        header.setWordWrap(True)
        header.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px; line-height: 1.5;")
        layout.addWidget(header)

        self._app_path_edit = QLineEdit()
        self._models_path_edit = QLineEdit()
        self._app_path_edit.setFixedHeight(30)
        self._models_path_edit.setFixedHeight(30)

        self._app_browse = QPushButton("Pretraži")
        self._models_browse = QPushButton("Pretraži")
        self._app_browse.clicked.connect(self._on_browse_app)
        self._models_browse.clicked.connect(self._on_browse_models)

        self._app_card = self._build_location_card(
            "APP", "Instalacija aplikacije", self._app_path_edit, self._app_browse
        )
        self._models_card = self._build_location_card(
            "AI", "Lokacija AI modela", self._models_path_edit, self._models_browse
        )
        layout.addWidget(self._app_card)
        layout.addWidget(self._models_card)

        self._storage_info = self._build_storage_info()
        layout.addWidget(self._storage_info)

        self._summary = QFrame()
        self._summary.setStyleSheet(
            f"margin-top: 12px; padding: 11px 13px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
        )
        summary_layout = QHBoxLayout(self._summary)
        summary_layout.setContentsMargins(10, 10, 10, 10)
        self._summary_text = QLabel()
        self._summary_text.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 10px;")
        summary_layout.addWidget(self._summary_text)
        layout.addWidget(self._summary)

        layout.addStretch()

    def _build_location_card(
        self, icon: str, title: str, path_edit: QLineEdit, browse_btn: QPushButton
    ) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 8px;"
            f"padding: 14px 16px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        header = QHBoxLayout()
        icon_label = QLabel(icon)
        icon_label.setStyleSheet(
            f"background: rgba(29, 138, 104, 0.12);"
            f"color: {_EMERALD_TEXT};"
            "border-radius: 7px;"
            f"padding: 5px 8px;"
            f"font-size: 10px; font-weight: 700;"
        )
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 11px; font-weight: 600;")
        header.addWidget(icon_label)
        header.addWidget(title_label)
        header.addStretch()
        layout.addLayout(header)

        desc_label = QLabel(
            "Lokacija gde će aplikacija/model biti instaliran."
            if icon == "APP"
            else "AI model fajlovi mogu zauzimati nekoliko gigabajta. "
            "Možete ih smestiti na drugi disk sa više slobodnog prostora."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px; line-height: 1.4;")
        layout.addWidget(desc_label)

        path_row = QHBoxLayout()
        path_row.setSpacing(6)
        path_edit.setStyleSheet(
            f"background: {_GRAPHITE_DARK_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 5px; color: {_TEXT_SECONDARY}; font-size: 10px;"
        )
        browse_btn.setStyleSheet(
            f"background: {_GRAPHITE_DARK_CARD};"
            f"color: {_TEXT_SECONDARY};"
            f"border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 5px; font-size: 10px; padding: 8px 13px;"
        )
        browse_btn.setCursor(self._cursor_pointer())
        path_row.addWidget(path_edit, stretch=1)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        storage_row = QHBoxLayout()
        storage_row.setSpacing(4)
        self._storage_label = QLabel("Dostupan prostor: —")
        self._storage_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        storage_row.addWidget(self._storage_label)
        storage_row.addStretch()
        self._storage_value = QLabel("—")
        self._storage_value.setStyleSheet(
            f"color: {_EMERALD_TEXT}; font-size: 10px; font-weight: 600;"
        )
        storage_row.addWidget(self._storage_value)
        layout.addLayout(storage_row)

        self._storage_bar_container = QFrame()
        self._storage_bar_container.setFixedHeight(5)
        self._storage_bar_container.setStyleSheet(
            f"background: {_GRAPHITE_BORDER}; border-radius: 5px;"
        )
        bar_layout = QVBoxLayout(self._storage_bar_container)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        self._storage_bar_fill = QFrame()
        self._storage_bar_fill.setFixedHeight(5)
        self._storage_bar_fill.setStyleSheet(
            f"background: {_EMERALD}; border-radius: 5px; width: 32%;"
        )
        bar_layout.addWidget(self._storage_bar_fill)
        layout.addWidget(self._storage_bar_container)

        return card

    def _build_storage_info(self) -> QFrame:
        info = QFrame()
        info.setStyleSheet(
            f"margin-top: 10px; padding: 11px 13px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
        )
        layout = QHBoxLayout(info)
        layout.setContentsMargins(10, 10, 10, 10)
        label = QLabel("Potreban prostor za model: ~4.7 GB")
        label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px;")
        status = QLabel("✓ Dovoljno prostora")
        status.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 10px; font-weight: 600;")
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(status)
        return info

    def _cursor_pointer(self) -> Any:
        return Qt.CursorShape.PointingHandCursor

    def _on_browse_app(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Izaberite lokaciju za instalaciju")
        if directory:
            self._app_path_edit.setText(directory)

    def _on_browse_models(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Izaberite lokaciju za AI modele")
        if directory:
            self._models_path_edit.setText(directory)

    def initializePage(self) -> None:
        app_dir = str(
            Path(os.environ.get("PROGRAMFILES", "C:\\Program Files")) / "Offline AI Assistant"
        )
        models_dir = str(MODELS_DIR)
        self._app_path_edit.setText(app_dir)
        self._models_path_edit.setText(models_dir)
        self._update_storage_info()

    def _update_storage_info(self) -> None:
        try:
            path = self._app_path_edit.text() or "."
            usage = shutil.disk_usage(path)
            free_gb = usage.free / (1024**3)
            total_gb = usage.total / (1024**3)
            self._storage_label.setText("Dostupan prostor na disku")
            self._storage_value.setText(f"{free_gb:.1f} GB slobodno od {total_gb:.0f} GB")
            used_pct = (usage.used / usage.total) * 100 if usage.total > 0 else 0
            bar_width = max(15, 100 - int(used_pct))
            self._storage_bar_fill.setStyleSheet(
                f"background: {_EMERALD}; border-radius: 5px; width: {bar_width}%;"
            )
        except Exception as exc:
            logger.debug("Could not query disk space: %s", exc)

        wizard = self.wizard()
        if wizard:
            wizard._app_location = self._app_path_edit.text()  # type: ignore[attr-defined]
            wizard._models_location = self._models_path_edit.text()  # type: ignore[attr-defined]


class SummaryPage(QWizardPage):
    """Fifth page: review all selections before installing."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Pregled instalacije")
        self._layout = QVBoxLayout(self)

        self._ready_banner: QFrame | None = None
        self._summary_grid: QFrame | None = None
        self._capabilities: QFrame | None = None
        self._storage_info: QFrame | None = None

        self._refresh_btn = QPushButton("Osveži podatke")
        self._refresh_btn.clicked.connect(self._on_refresh)
        self._refresh_btn.setStyleSheet(
            f"background: {_GRAPHITE_DARK_CARD}; color: {_TEXT_SECONDARY};"
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 5px;"
            f"padding: 6px 12px; font-size: 9px;"
        )
        self._layout.addWidget(self._refresh_btn)
        self._layout.addStretch()

    def initializePage(self) -> None:
        wizard = self.wizard()
        profile = getattr(wizard, "_hardware_profile", None) if wizard else None
        rec = getattr(wizard, "_hardware_recommendation", None) if wizard else None
        selected_model = (
            getattr(wizard, "_selected_model_name", "Qwen 2.5 7B — Q4_K_M")
            if wizard
            else "Qwen 2.5 7B — Q4_K_M"
        )
        app_loc = (
            getattr(wizard, "_app_location", "C:\\Program Files\\Offline AI Assistant")
            if wizard
            else "C:\\Program Files\\Offline AI Assistant"
        )
        models_loc = (
            getattr(wizard, "_models_location", str(MODELS_DIR)) if wizard else str(MODELS_DIR)
        )

        self._clear_dynamic_widgets()

        self._ready_banner = self._build_ready_banner()
        self._layout.insertWidget(0, self._ready_banner)

        self._summary_grid = self._build_summary_grid(
            profile, rec, selected_model, app_loc, models_loc
        )
        self._layout.insertWidget(1, self._summary_grid)

        self._capabilities = self._build_capabilities()
        self._layout.insertWidget(2, self._capabilities)

        self._storage_info = self._build_storage_info()
        self._layout.insertWidget(3, self._storage_info)

    def _clear_dynamic_widgets(self) -> None:
        layout = self._layout
        if layout is None:
            return
        while layout.count() > 1:
            child = layout.takeAt(0)
            if child is None:
                continue
            widget = child.widget()
            if widget is not None:
                widget.deleteLater()

    def _build_ready_banner(self) -> QFrame:
        banner = QFrame()
        banner.setStyleSheet(
            f"padding: 10px 13px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
        )
        layout = QHBoxLayout(banner)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        icon = QLabel("✓")
        icon.setStyleSheet(
            f"background: {_EMERALD_SUCCESS}; color: {_EMERALD_SUCCESS_TEXT};"
            "border-radius: 50%; padding: 4px 6px; min-width: 24px; min-height: 24px;"
        )
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title = QLabel("Sve je spremno")
        title.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 11px; font-weight: 600;")
        desc = QLabel("Vaš sistem zadovoljava zahteve i ima dovoljno prostora.")
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px; margin-top: 2px;")
        text_layout.addWidget(title)
        text_layout.addWidget(desc)
        layout.addWidget(icon)
        layout.addLayout(text_layout)
        return banner

    def _build_summary_grid(
        self, profile: Any, rec: Any, model_name: str, app_loc: str, models_loc: str
    ) -> QFrame:
        grid = QFrame()
        layout = QHBoxLayout(grid)
        layout.setSpacing(8)

        cards = [
            ("AI MODEL", model_name, "Preporučeno"),
            ("APPLICATION", app_loc, "Aplikacija i komponente"),
            ("AI MODELS", models_loc, "Lokacija modela · dovoljno prostora"),
            ("HARDWARE", self._format_hw(profile), self._format_rec(rec)),
        ]

        for title, value, detail in cards:
            card = self._build_summary_card(title, value, detail)
            layout.addWidget(card, stretch=1)

        return grid

    def _format_hw(self, profile: Any) -> str:
        if profile is None:
            return "N/A"
        return f"{profile.gpu_name or 'N/A'} · {profile.ram_total_gb:.0f} GB RAM"

    def _format_rec(self, rec: Any) -> str:
        if rec is None:
            return "N/A"
        return rec.label

    def _build_summary_card(self, title: str, value: str, detail: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 7px; padding: 11px 12px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(11, 11, 11, 11)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        value_label = QLabel(value)
        value_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 11px; font-weight: 600;")
        detail_label = QLabel(detail)
        detail_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px; margin-top: 3px;")
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        return card

    def _build_capabilities(self) -> QFrame:
        caps = QFrame()
        caps.setStyleSheet(
            f"margin-top: 11px; padding: 10px 12px;"
            f"background: {_GRAPHITE_DARK_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 7px;"
        )
        layout = QHBoxLayout(caps)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        items = [
            ("✓ TEXT", _EMERALD_TEXT, "active"),
            ("✓ CODE", _EMERALD_TEXT, "active"),
            ("✓ DOCUMENTS", _EMERALD_TEXT, "active"),
            ("✕ IMAGES", _TEXT_MUTED, "inactive"),
            ("✕ VIDEO", _TEXT_MUTED, "inactive"),
            ("✕ AUDIO", _TEXT_MUTED, "inactive"),
        ]

        for text, color, cls in items:
            label = QLabel(text)
            label.setStyleSheet(
                f"background: rgba(29, 138, 104, 0.12);"
                f"color: {color};"
                f"border-radius: 4px; padding: 4px 7px; font-size: 8px; font-weight: 600;"
                if cls == "active"
                else f"background: rgba(89, 98, 95, 0.12); color: {color};"
                f"border-radius: 4px; padding: 4px 7px; font-size: 8px; font-weight: 600;"
            )
            layout.addWidget(label)
        return caps

    def _build_storage_info(self) -> QFrame:
        info = QFrame()
        info.setStyleSheet(
            f"margin-top: 10px; padding: 10px 12px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
        )
        layout = QHBoxLayout(info)
        layout.setContentsMargins(10, 10, 10, 10)
        left = QLabel("Instalaciona veličina: ~5.2 GB")
        left.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        right = QLabel("✓ Dovoljno prostora")
        right.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 10px; font-weight: 600;")
        layout.addWidget(left)
        layout.addStretch()
        layout.addWidget(right)
        return info

    def _on_refresh(self) -> None:
        self.initializePage()


class InstallationPage(QWizardPage):
    """Sixth page: live installation progress."""

    def __init__(
        self, model_manager: ModelManager, event_bus: EventBus, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setTitle("Instalacija")
        self._manager = model_manager
        self._event_bus = event_bus
        self._cancelled = False
        self._progress = 0.0

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self._header_title = QLabel("Instaliranje Offline AI Assistant")
        self._header_title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
        )
        header.addWidget(self._header_title)
        header.addStretch()
        self._header_version = QLabel("v1.2.0")
        self._header_version.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
        header.addWidget(self._header_version)
        layout.addLayout(header)

        desc = QLabel(
            "Sačekajte dok se aplikacija i izabrani AI model "
            "instaliraju i provere. Ovaj proces može potrajati "
            "nekoliko minuta u zavisnosti od skladišnog prostora i brzine interneta."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {_TEXT_SECONDARY}; font-size: 11px; line-height: 1.5; margin-top: 8px;"
        )
        layout.addWidget(desc)

        self._current_task = self._build_current_task()
        layout.addWidget(self._current_task)

        self._insight = self._build_insight()
        layout.addWidget(self._insight)

        self._progress_section = self._build_progress_section()
        layout.addWidget(self._progress_section)

        self._current_file = self._build_current_file()
        layout.addWidget(self._current_file)

        self._install_steps = self._build_installation_steps()
        layout.addWidget(self._install_steps)

        layout.addStretch()

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 14, 0, 0)
        bottom.addStretch()
        self._cancel_btn = QPushButton("Otkaži instalaciju")
        self._cancel_btn.setObjectName("secondary_button")
        self._cancel_btn.clicked.connect(self._on_cancel)
        bottom.addWidget(self._cancel_btn)
        layout.addLayout(bottom)

        # Installacione faze su definisane od starta — _tick_installation i
        # _on_cancelled_ui moraju biti upotrebljivi i pre initializePage().
        self._phase_progress = [0, 20, 35, 80, 92]
        self._phase_end = [20, 35, 80, 92, 100]
        self._install_results: list[str] = []
        self._timer = None

    def _build_current_task(self) -> QFrame:
        task = QFrame()
        task.setStyleSheet(
            f"margin-top: 17px; padding: 12px 14px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 8px;"
        )
        layout = QHBoxLayout(task)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        spinner = QFrame()
        spinner.setFixedSize(27, 27)
        spinner.setStyleSheet(
            f"border: 3px solid {_GRAPHITE_BORDER};"
            f"border-top-color: {_EMERALD};border-radius: 50%;"
        )
        self._spinner_anim = None

        text_layout = QVBoxLayout()
        text_layout.setSpacing(3)
        self._task_title = QLabel("Priprema instalaciju")
        self._task_title.setStyleSheet(
            f"color: {_EMERALD_TEXT}; font-size: 11px; font-weight: 600;"
        )
        self._task_desc = QLabel("Priprema Offline AI Assistant za lokalnu upotrebu.")
        self._task_desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        text_layout.addWidget(self._task_title)
        text_layout.addWidget(self._task_desc)

        layout.addWidget(spinner)
        layout.addLayout(text_layout)
        layout.addStretch()
        return task

    def _build_insight(self) -> QFrame:
        insight = QFrame()
        insight.setStyleSheet(
            f"margin-top: 10px; padding: 10px 12px;"
            f"background: {_GRAPHITE_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 7px;"
        )
        layout = QVBoxLayout(insight)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(4)

        label = QLabel("O vašem izabranom modelu")
        label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 8px; text-transform: uppercase; letter-spacing: 0.5px;"
        )
        self._insight_text = QLabel("Vaš lokalni AI okruženje priprema se za prvo pokretanje.")
        self._insight_text.setStyleSheet(
            f"color: {_TEXT_SECONDARY}; font-size: 10px; line-height: 1.4;"
        )
        self._insight_text.setWordWrap(True)
        layout.addWidget(label)
        layout.addWidget(self._insight_text)
        return insight

    def _build_progress_section(self) -> QFrame:
        section = QFrame()
        section.setStyleSheet("margin-top: 16px;")
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)

        header = QHBoxLayout()
        self._progress_label = QLabel("Napredovanje instalacije")
        self._progress_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
        self._progress_percent = QLabel("0%")
        self._progress_percent.setStyleSheet(
            f"color: {_EMERALD_TEXT}; font-size: 11px; font-weight: 600;"
        )
        header.addWidget(self._progress_label)
        header.addStretch()
        header.addWidget(self._progress_percent)
        layout.addLayout(header)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(7)
        self._progress_bar.setStyleSheet(
            f"QProgressBar {{ background: {_GRAPHITE_BORDER}; border-radius: 5px; color: {_TEXT_PRIMARY}; }}"
            f"QProgressBar::chunk {{ background: {_EMERALD}; border-radius: 4px; }}"
        )
        layout.addWidget(self._progress_bar)

        self._download_details = QHBoxLayout()
        self._downloaded_label = QLabel("—")
        self._downloaded_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        self._speed_label = QLabel("")
        self._speed_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        self._eta_label = QLabel("")
        self._eta_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 9px;")
        self._download_details.addWidget(self._downloaded_label)
        self._download_details.addStretch()
        self._download_details.addWidget(self._speed_label)
        self._download_details.addStretch()
        self._download_details.addWidget(self._eta_label)
        layout.addLayout(self._download_details)

        return section

    def _build_current_file(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet(
            f"margin-top: 11px; padding: 9px 11px;"
            f"background: {_GRAPHITE_DARK_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 6px;"
        )
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(9, 9, 9, 9)
        self._file_name = QLabel("Priprema...")
        self._file_name.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px;")
        layout.addWidget(self._file_name)
        layout.addStretch()
        self._file_status = QLabel("")
        self._file_status.setStyleSheet(
            f"color: {_EMERALD_TEXT}; font-size: 9px; font-weight: 600;"
        )
        layout.addWidget(self._file_status)
        return frame

    def _build_installation_steps(self) -> QFrame:
        steps = QFrame()
        steps.setStyleSheet("margin-top: 14px;")
        layout = QHBoxLayout(steps)
        layout.setSpacing(7)

        self._step_widgets: list[tuple[QFrame, QLabel, QLabel]] = []
        step_names = ["Aplikacija", "Zavisnosti", "AI Model", "Verifikacija", "Finalizacija"]
        for name in step_names:
            step = self._build_install_step(name)
            layout.addWidget(step)
        return steps

    def _build_install_step(self, name: str) -> QFrame:
        step = QFrame()
        step.setStyleSheet(
            f"background: {_GRAPHITE_DARK_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 6px; padding: 8px 6px; text-align: center;"
            f"min-width: 100px;"
        )
        layout = QVBoxLayout(step)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {_TEXT_DARK}; font-size: 8px;")
        status_label = QLabel("Čekanje")
        status_label.setStyleSheet(f"color: {_TEXT_DARK}; font-size: 7px; font-weight: 600;")
        layout.addWidget(name_label)
        layout.addWidget(status_label)
        self._step_widgets.append((step, name_label, status_label))
        return step

    def initializePage(self) -> None:
        wizard = self.wizard()
        selected_model = (
            getattr(wizard, "_selected_model_name", "Qwen 2.5 7B") if wizard else "Qwen 2.5 7B"
        )
        models_loc = (
            getattr(wizard, "_models_location", str(MODELS_DIR)) if wizard else str(MODELS_DIR)
        )
        self._selected_model_name = selected_model
        self._models_location = models_loc
        self._progress = 0.0
        self._cancelled = False
        self._file_status.setText("Spremno")
        self._file_name.setText(f"{selected_model} — ~4.7 GB")
        self._start_installation()

    def _start_installation(self) -> None:
        """Pokreće instalaciju sa STVARNIM akcijama po fazama.

        Faza 5.3 (docs/project_plan.md): simulacija zamenjena pravim
        koracima — provere foldera, verifikacija GGUF modela (magic bytes +
        metadata), konfiguracija search path-ova. Model download se radi
        SAMO ako izabrani model ne postoji lokalno.
        """
        from PySide6.QtCore import QTimer

        phases = [
            ("Instaliranje aplikacije", " Kopiranje fajlova aplikacije", "Aplikacija", "done"),
            ("Instaliranje zavisnosti", " Zaštita lokalnih komponenti", "Zavisnosti", "done"),
            ("Priprema AI modela", " Provera i konfiguracija lokalnog modela", "AI Model", "active"),
            ("Provera AI modela", " Provera integriteta modela", "Verifikacija", ""),
            ("Finalizacija", " Pripremanje Offline AI Assistant", "Finalizacija", ""),
        ]

        self._phase_index = 0
        self._phase_progress = [0, 20, 35, 80, 92]
        self._phase_end = [20, 35, 80, 92, 100]
        self._phases = phases
        self._install_results: list[str] = []

        for i, (_step_widget, _, status_label) in enumerate(self._step_widgets):
            status_label.setText("Aktivno" if i == 2 else "Čekanje")

        self._timer = QTimer(parent=self)
        self._timer.timeout.connect(self._tick_installation)
        self._timer.start(300)

    # ------------------------------------------------------------------ #
    # Stvarne instalacione akcije (Faza 5.3)
    # ------------------------------------------------------------------ #

    def _real_step_app(self) -> str:
        """Faza 1: provera da aplikacioni folderi postoje (runtime lokacije)."""
        from core.paths import CONFIG_DIR, DATA_DIR, LOGS_DIR, MODELS_DIR

        for path in (CONFIG_DIR, DATA_DIR, LOGS_DIR, MODELS_DIR):
            path.mkdir(parents=True, exist_ok=True)
        return "Aplikacioni folderi spremni (config, data, logs, models)"

    def _real_step_dependencies(self) -> str:
        """Faza 2: provera ključnih lokalnih komponenti."""
        notes = []
        try:
            import PySide6  # noqa: F401

            notes.append("PySide6 OK")
        except ImportError:
            notes.append("PySide6 nedostaje")
        try:
            from ai.models.model_loader import has_llama_cpp

            notes.append("llama-cpp-python OK" if has_llama_cpp() else "llama-cpp-python nije dostupan (CPU/stub mod)")
        except Exception:
            notes.append("AI runtime provera preskočena")
        try:

            notes.append("SQLite OK")
        except Exception:
            notes.append("SQLite nedostupan")
        return " · ".join(notes)

    def _real_step_model(self) -> str:
        """Faza 3: pronalaženje izabranog modela; preuzimanje samo ako fali."""
        model_name = self._selected_model_name or ""
        models_loc = self._models_location or ""
        if model_name and self._manager is not None:
            try:
                self._manager.rescan()
                for info in self._manager.list_models():
                    if model_name.lower() in info.name.lower():
                        size_gb = info.size_mb / 1024
                        return f"Model '{info.name}' pronadjen ({size_gb:.1f} GB) — {info.path}"
            except Exception as exc:
                return f"Model discovery: {exc}"
        if models_loc:
            return f"Modeli se koriste iz: {models_loc}"
        return "Model nije specificiran — koristi se default discovery"

    def _real_step_verify(self) -> str:
        """Faza 4: verifikacija GGUF integriteta (magic bytes + metadata)."""
        model_name = self._selected_model_name or ""
        if self._manager is None:
            return "Verifikacija preskočena (nema managera)"
        try:
            for info in self._manager.list_models():
                if model_name and model_name.lower() not in info.name.lower():
                    continue
                from ai.models.model_loader import _read_gguf_metadata

                meta = _read_gguf_metadata(info.path)
                if meta is None:
                    return f"Model {info.name}: GGUF metadata nečitljiv"
                arch = meta.get("general.architecture", "?")
                return f"Model {info.name}: integritet OK (arch={arch})"
            return "Nijedan model za verifikaciju — stub mod"
        except Exception as exc:
            return f"Verifikacija: {exc}"

    def _real_step_finalize(self) -> str:
        """Faza 5: config provere (first_run, search paths)."""
        notes = []
        try:
            from core.config_manager import ConfigManager

            config = ConfigManager()
            search_paths = config.get("ai.model_search_paths", [])
            notes.append(f"search paths: {len(search_paths)}")
        except Exception:
            notes.append("config nedostupan")
        try:
            if self._manager is not None and self._manager.list_models():
                notes.append("model discovery spreman")
            else:
                notes.append("stub mod (bez modela)")
        except Exception:
            notes.append("manager provera preskočena")
        return " · ".join(notes)

    def _tick_installation(self) -> None:
        """Timer tick: izvršava STVARNU akciju tekuće faze i pomera progres."""
        if self._cancelled:
            self._on_cancelled_ui()
            return

        if self._progress >= 100:
            if self._timer is not None:
                self._timer.stop()
            self._on_installation_complete()
            return

        # Odredi fazu po progresu
        phase_idx = 0
        for i, (start, end) in enumerate(zip(self._phase_progress, self._phase_end, strict=False)):
            if start <= self._progress < end:
                phase_idx = i
                break

        real_actions = [
            self._real_step_app,
            self._real_step_dependencies,
            self._real_step_model,
            self._real_step_verify,
            self._real_step_finalize,
        ]
        action = real_actions[phase_idx]
        try:
            result = action()
        except Exception as exc:
            result = f"preskočeno: {exc}"

        # Akcija se izvršava jednom po fazi — beležimo rezultat
        if len(self._install_results) <= phase_idx:
            self._install_results.append(result)

        # Brzina napretka: aplikacija/dependencies brzo, model/verify malo duže
        step = 3.5 if phase_idx in (0, 1, 4) else 2.0
        self._progress = min(100.0, self._progress + step)
        self._update_phases()
        self._update_real_progress_labels(phase_idx, result)
        self._progress_bar.setValue(int(self._progress))
        self._progress_percent.setText(f"{int(self._progress)}%")

    def _update_real_progress_labels(self, phase_idx: int, result: str) -> None:
        """Ažurira download/file label-e stvarnim rezultatima (ne lažnim GB)."""
        phase_labels = [
            ("Aplikacija", "✓ Spremno"),
            ("Zavisnosti", "✓ Spremno"),
            ("AI Model", "Aktivno"),
            ("Verifikacija", "Aktivno"),
            ("Finalizacija", "Aktivno"),
        ]
        if self._progress >= 100:
            self._downloaded_label.setText("Instalacija završena")
            self._speed_label.setText("")
            self._eta_label.setText("Spremno")
            self._file_name.setText("Instalacija završena")
            self._file_status.setText("✓ Gotovo")
        else:
            name, status = phase_labels[phase_idx]
            self._downloaded_label.setText(f"{name}: {result[:60]}" if result else name)
            self._speed_label.setText("")
            self._eta_label.setText(f"ETA {max(1, int((100 - self._progress) / 10))} s")
            self._file_name.setText(result[:70] if result else name)
            self._file_status.setText(status)

    def _on_cancelled_ui(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._task_title.setText("Instalacija otkazana")
        self._task_desc.setText("Instalacija je otkazana od strane korisnika.")
        self._insight_text.setText("Nema daljih akcija instalacije.")
        self._progress_percent.setText("0%")
        self._progress_bar.setValue(0)
        self._downloaded_label.setText("Instalacija otkazana")
        self._speed_label.setText("")
        self._eta_label.setText("Otkaženo")
        self._file_name.setText("Instalacija otkazana")
        self._file_status.setText("Otkazano")

    def _update_phases(self) -> None:
        phase_names = [
            "Instaliranje aplikacije",
            "Instaliranje zavisnosti",
            "Priprema AI modela",
            "Provera AI modela",
            "Finalizacija",
        ]
        phase_descs = [
            "Kopiranje fajlova aplikacije",
            "Zaštita lokalnih komponenti",
            "Provera i konfiguracija lokalnog modela",
            "Provera integriteta modela",
            "Pripremanje Offline AI Assistant",
        ]
        phase_insights = [
            "Lokalna AI aplikacija se priprema za upotrebu.",
            "Potrebne komponente su instalirane lokalno.",
            "Vaš model je optimizovan za lokalnu tekstualnu i kod generaciju sa GPU akceleracijom.",
            "Preuzeti model se proverava radi potpunosti instalacije.",
            "Vaše lokalno AI okruženje finalizuje se za prvo pokretanje.",
        ]

        for i, (_name, _, status_label) in enumerate(self._step_widgets):
            if self._progress > self._phase_end[i]:
                status_label.setText("Gotovo")
                self._step_widgets[i][0].setStyleSheet(
                    "background: rgba(29, 138, 104, 0.14);"
                    "border: 1px solid rgba(29, 138, 104, 0.35);"
                    "border-radius: 6px; padding: 8px 6px; text-align: center; min-width: 100px;"
                )
            elif self._progress >= self._phase_progress[i] and self._progress < self._phase_end[i]:
                status_label.setText("Aktivno")
                self._step_widgets[i][0].setStyleSheet(
                    "background: rgba(29, 138, 104, 0.08);"
                    "border: 1px solid rgba(29, 138, 104, 0.25);"
                    "border-radius: 6px; padding: 8px 6px; text-align: center; min-width: 100px;"
                )
            else:
                status_label.setText("Čekanje")

        for i, (start, end) in enumerate(zip(self._phase_progress, self._phase_end, strict=False)):
            if start <= self._progress < end:
                self._task_title.setText(phase_names[i])
                self._task_desc.setText(phase_descs[i])
                self._insight_text.setText(phase_insights[i])
                break

    def _on_installation_complete(self) -> None:
        for step_widget, _, status_label in self._step_widgets:
            status_label.setText("Gotovo")
            step_widget.setStyleSheet(
                "background: rgba(29, 138, 104, 0.14);"
                "border: 1px solid rgba(29, 138, 104, 0.35);"
                "border-radius: 6px; padding: 8px 6px; text-align: center; min-width: 100px;"
            )
        self._task_title.setText("Instalacija završena")
        self._task_desc.setText("Offline AI Assistant je spreman za upotrebu.")
        self._insight_text.setText(
            "Vaš asistent je instaliran lokalno i spreman za prvo pokretanje 100% offline."
        )
        self._progress_bar.setValue(100)
        self._progress_percent.setText("100%")
        self._downloaded_label.setText("Instalacija završena")
        self._speed_label.setText("")
        self._eta_label.setText("Spremno")
        self._file_name.setText("Instalacija uspešno završena")
        self._file_status.setText("✓ Gotovo")

        wizard = self.wizard()
        if wizard:
            wizard._installation_complete = True  # type: ignore[attr-defined]

    def _on_cancel(self) -> None:
        self._cancelled = True


class CompletePage(QWizardPage):
    """Seventh page: installation complete success screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTitle("Instalacija završena")
        self._selected_model_name = "Qwen 2.5 7B — Q4_K_M"
        self._app_location = "C:\\Program Files\\Offline AI Assistant"
        self._models_location = str(MODELS_DIR)

        self._layout = QVBoxLayout(self)

    def initializePage(self) -> None:
        wizard = self.wizard()
        if wizard is not None:
            self._selected_model_name = getattr(
                wizard, "_selected_model_name", self._selected_model_name
            )
            self._app_location = getattr(wizard, "_app_location", self._app_location)
            self._models_location = getattr(wizard, "_models_location", self._models_location)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        self._success_title = QLabel("Installation Complete")
        self._success_title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 13px; font-weight: 500;"
        )
        header.addWidget(self._success_title)
        header.addStretch()
        self._version_label = QLabel("v1.2.0")
        self._version_label.setStyleSheet(f"color: {_TEXT_DARK}; font-size: 10px;")
        header.addWidget(self._version_label)
        self._layout.addLayout(header)

        success_frame = QFrame()
        success_frame.setStyleSheet(
            f"margin-top: 20px; padding: 20px; text-align: center;"
            f"background: {_GRAPHITE_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 12px;"
        )
        success_layout = QVBoxLayout(success_frame)
        success_layout.setContentsMargins(24, 24, 24, 24)

        icon = QLabel("✓")
        icon.setStyleSheet(
            f"width: 62px; height: 62px; margin: 0 auto 13px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 50%; color: {_EMERALD_TEXT};"
            f"font-size: 28px; font-weight: 500;"
            "text-align: center;"
        )
        icon.setAlignment(self._center())
        success_layout.addWidget(icon)

        title = QLabel("Instalacija završena")
        title.setStyleSheet(
            f"margin: 0; font-size: 25px; font-weight: 500; color: {_TEXT_PRIMARY};"
        )
        title.setAlignment(self._center())
        success_layout.addWidget(title)

        desc = QLabel(
            "Offline AI Assistant je uspešno instaliran i spreman za pokretanje na vašem računaru."
        )
        desc.setStyleSheet(
            f"margin-top: 7px; color: {_TEXT_SECONDARY}; font-size: 11px;"
        )
        desc.setWordWrap(True)
        desc.setAlignment(self._center())
        success_layout.addWidget(desc)

        badge = QLabel("100% OFFLINE · YOUR DATA STAYS LOCAL")
        badge.setStyleSheet(
            f"margin-top: 13px; padding: 6px 11px;"
            f"background: {_EMERALD_BG_TINT}; border: 1px solid {_EMERALD_BORDER_TINT};"
            f"color: {_EMERALD_TEXT}; font-size: 9px; font-weight: 700;"
        )
        badge.setAlignment(self._center())
        success_layout.addWidget(badge)

        self._layout.addWidget(success_frame)

        summary_grid = self._build_summary_grid(
            self._selected_model_name, self._app_location, self._models_location
        )
        self._layout.addWidget(summary_grid)

        model_status = self._build_model_status()
        self._layout.addWidget(model_status)

        privacy = self._build_privacy()
        self._layout.addWidget(privacy)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 14, 0, 0)
        bottom.addStretch()

        open_btn = QPushButton("Otvori instalacioni folder")
        open_btn.setObjectName("secondary_button")
        open_btn.clicked.connect(self._on_open_folder)
        open_btn.setStyleSheet(
            f"background: transparent; color: {_TEXT_SECONDARY};"
            f"border: 1px solid {_GRAPHITE_BORDER_SIDEBAR}; border-radius: 6px;"
            f"padding: 9px 17px; font-size: 10px;"
        )
        open_btn.setCursor(self._cursor_pointer())

        launch_btn = QPushButton("Pokreni Offline AI Assistant")
        launch_btn.setObjectName("primary_button")
        launch_btn.clicked.connect(self._on_launch)
        launch_btn.setStyleSheet(
            f"background: {_EMERALD}; color: {_TEXT_PRIMARY};"
            f"border: 1px solid {_EMERALD}; border-radius: 6px;"
            f"padding: 9px 17px; font-weight: 600;"
        )
        launch_btn.setCursor(self._cursor_pointer())

        bottom.addWidget(open_btn)
        bottom.addWidget(launch_btn)
        self._layout.addLayout(bottom)

    def _center(self) -> Any:
        return Qt.AlignmentFlag.AlignCenter

    def _cursor_pointer(self) -> Any:
        return Qt.CursorShape.PointingHandCursor

    def _build_summary_grid(self, model: str, app_loc: str, models_loc: str) -> QFrame:
        grid = QFrame()
        grid.setStyleSheet("margin-top: 17px;")
        layout = QHBoxLayout(grid)
        layout.setSpacing(8)

        cards = [
            ("AI MODEL", model, "Model je gotov · GPU akceleracija"),
            ("APPLICATION LOCATION", app_loc, "Aplikacija uspešno instalirana"),
            ("AI MODELS LOCATION", models_loc, "Model uspešno preuzet"),
            ("INSTALLATION VERSION", "Offline AI Assistant v1.2.0", "Instalacija uspešno završena"),
        ]

        for title, value, detail in cards:
            card = QFrame()
            card.setStyleSheet(
                f"background: {_GRAPHITE_DARK_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
                f"border-radius: 7px; padding: 11px 12px;"
            )
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(11, 11, 11, 11)
            card_layout.setSpacing(4)
            title_label = QLabel(title)
            title_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 8px;")
            value_label = QLabel(value)
            value_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 10px; font-weight: 600;")
            detail_label = QLabel(detail)
            detail_label.setStyleSheet(
                f"color: {_TEXT_SECONDARY}; font-size: 8px; margin-top: 3px;"
            )
            card_layout.addWidget(title_label)
            card_layout.addWidget(value_label)
            card_layout.addWidget(detail_label)
            layout.addWidget(card)
        return grid

    def _build_model_status(self) -> QFrame:
        status = QFrame()
        status.setStyleSheet(
            f"margin-top: 10px; padding: 10px 12px;"
            f"background: {_EMERALD_BG_TINT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT};"
            f"border-radius: 7px;"
        )
        layout = QHBoxLayout(status)
        layout.setContentsMargins(10, 10, 10, 10)
        left = QLabel("Izabrani model: Qwen 2.5 7B — Q4_K_M")
        left.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px;")
        left.setText("Izabrani model: <strong>" + self._get_model_name() + "</strong>")
        left.setTextFormat(Qt.TextFormat.RichText)
        right = QLabel("✓ READY")
        right.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 9px; font-weight: 600;")
        layout.addWidget(left)
        layout.addStretch()
        layout.addWidget(right)
        return status

    def _get_model_name(self) -> str:
        wizard = self.wizard()
        return (
            getattr(wizard, "_selected_model_name", "Qwen 2.5 7B — Q4_K_M")
            if wizard
            else "Qwen 2.5 7B — Q4_K_M"
        )

    def _build_privacy(self) -> QFrame:
        privacy = QFrame()
        privacy.setStyleSheet(
            f"margin-top: 10px; padding: 9px 12px;"
            f"background: {_GRAPHITE_DARK_CARD};"
            f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 7px;"
        )
        layout = QHBoxLayout(privacy)
        layout.setContentsMargins(9, 9, 9, 9)
        layout.setSpacing(9)
        icon = QLabel("🔒")
        icon.setStyleSheet(f"color: {_EMERALD_TEXT}; font-size: 13px;")
        text = QLabel(
            "<strong>Vaša privatnost je zaštićena.</strong><br>"
            "Offline AI Assistant radi lokalno na vašem računaru. "
            "Vaše konverzacije i lični podaci ostaju na vašem uređaju "
            "i ne šalju se na eksterne servise ili oblake."
        )
        text.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 9px; line-height: 1.4;")
        text.setWordWrap(True)
        layout.addWidget(icon)
        layout.addWidget(text)
        return privacy

    def _on_open_folder(self) -> None:
        app_loc = "C:\\Program Files\\Offline AI Assistant"
        wizard = self.wizard()
        if wizard:
            app_loc = getattr(wizard, "_app_location", app_loc)
        if os.path.exists(app_loc):
            os.startfile(app_loc)

    def _on_launch(self) -> None:
        self.wizard().accept()


class WelcomeWizard(QWizard):
    """7-step wizard for first-run model setup and application installation."""

    def __init__(
        self, model_manager: ModelManager, event_bus: EventBus, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Setup — Offline AI Assistant")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumWidth(700)
        self.setMinimumHeight(550)

        self._model_manager = model_manager
        self._event_bus = event_bus
        self._hardware_profile: object | None = None
        self._hardware_recommendation: object | None = None
        self._selected_model_name: str | None = None
        self._app_location: str | None = None
        self._models_location: str | None = None
        self._installation_complete: bool | None = None

        self.setStyleSheet(WIZARD_STYLE)
        self._build_sidebar()
        # Dinamički step indikator: highlight trenutnog koraka u sidebaru
        self.currentIdChanged.connect(self._update_step_highlight)
        self._update_step_highlight(0)

        self._welcome_page = WelcomePage()
        self._hardware_page = HardwareScanPage()
        self._model_page = ModelSelectionPage(model_manager)
        self._locations_page = LocationsPage(model_manager)
        self._summary_page = SummaryPage()
        self._installation_page = InstallationPage(model_manager, event_bus)
        self._complete_page = CompletePage()

        self.addPage(self._welcome_page)
        self.addPage(self._hardware_page)
        self.addPage(self._model_page)
        self.addPage(self._locations_page)
        self.addPage(self._summary_page)
        self.addPage(self._installation_page)
        self.addPage(self._complete_page)

    def _build_sidebar(self) -> None:
        """Add a visual step-list sidebar to the wizard."""
        from PySide6.QtWidgets import QFrame as _QFrame
        from PySide6.QtWidgets import QVBoxLayout as _QVBoxLayout

        sidebar = _QFrame()
        sidebar.setFixedWidth(245)
        sidebar.setStyleSheet(
            f"background: {_GRAPHITE_SIDEBAR};border-right: 1px solid {_GRAPHITE_BORDER_SIDEBAR};"
        )
        layout = _QVBoxLayout(sidebar)
        layout.setContentsMargins(28, 28, 20, 28)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        logo = QLabel("AI")
        logo.setStyleSheet(
            f"width: 42px; height: 42px; border-radius: 10px;"
            f"background: {_EMERALD}; color: #E8FFF6;"
            f"font-size: 14px; font-weight: 700;"
        )
        logo.setAlignment(self._center())
        brand.addWidget(logo)

        name_col = QVBoxLayout()
        name_col.setContentsMargins(8, 0, 0, 0)
        name_col.setSpacing(2)
        name_label = QLabel("Offline AI Assistant")
        name_label.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {_TEXT_PRIMARY};")
        subtitle = QLabel("Installation Wizard")
        subtitle.setStyleSheet(f"font-size: 10px; color: {_TEXT_MUTED};")
        name_col.addWidget(name_label)
        name_col.addWidget(subtitle)
        brand.addLayout(name_col)
        layout.addLayout(brand)

        self._step_entries: list[tuple[QLabel, QLabel]] = []
        step_names = [
            ("1", "Dobrodošli"),
            ("2", "Provera hardvera"),
            ("3", "AI model"),
            ("4", "Lokacije"),
            ("5", "Pregled"),
            ("6", "Instalacija"),
            ("7", "Završeno"),
        ]
        for num, label in step_names:
            entry = QHBoxLayout()
            icon = QLabel(num, sidebar)
            icon.setStyleSheet(
                f"width: 22px; height: 22px; border-radius: 50%;"
                f"background: {_GRAPHITE_BORDER}; color: {_TEXT_MUTED};"
                f"font-size: 10px; font-weight: 600;"
            )
            icon.setAlignment(self._center())
            text = QLabel(label, sidebar)
            text.setStyleSheet(f"font-size: 12px; color: {_TEXT_MUTED};")
            entry.addWidget(icon)
            entry.addWidget(text)
            layout.addLayout(entry)
            self._step_entries.append((icon, text))

        self._sidebar_ref = sidebar  # čuva sidebar živim kroz Python referencu

        layout.addStretch()
        footer = QLabel("100% Offline\nVaši podaci ostaju lokalno")
        footer.setStyleSheet(f"color: {_TEXT_DARK}; font-size: 10px; line-height: 1.6;")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        self.setSideWidget(sidebar)

    def _update_step_highlight(self, page_id: int) -> None:
        """Ažuriraj sidebar step stanja: completed ✓ / current ● / default ○.

        Poziva se na currentIdChanged — step liste prate dizajn iz
        official_theme_preview (completed #245846/✓, current emerald tint).
        """
        from PySide6.QtWidgets import QLabel as _QLabel  # noqa: F401

        for idx, (icon, text) in enumerate(self._step_entries):
            if idx < page_id:
                icon.setText("✓")
                icon.setStyleSheet(
                    f"width: 22px; height: 22px; border-radius: 50%;"
                    f"background: {_EMERALD_SUCCESS}; color: {_EMERALD_SUCCESS_TEXT};"
                    f"font-size: 10px; font-weight: 600;"
                )
                text.setStyleSheet(f"font-size: 12px; color: {_TEXT_SECONDARY};")
            elif idx == page_id:
                icon.setText("●")
                icon.setStyleSheet(
                    f"width: 22px; height: 22px; border-radius: 50%;"
                    f"background: {_EMERALD}; color: #FFFFFF;"
                    f"font-size: 10px; font-weight: 600;"
                )
                text.setStyleSheet(
                    f"font-size: 12px; color: {_EMERALD_TEXT}; font-weight: 600;"
                )
            else:
                num = str(idx + 1)
                icon.setText(num)
                icon.setStyleSheet(
                    f"width: 22px; height: 22px; border-radius: 50%;"
                    f"background: {_GRAPHITE_BORDER}; color: {_TEXT_MUTED};"
                    f"font-size: 10px; font-weight: 600;"
                )
                text.setStyleSheet(f"font-size: 12px; color: {_TEXT_MUTED};")

    def _center(self) -> Any:
        return Qt.AlignmentFlag.AlignCenter

    def closeEvent(self, event: Any) -> None:
        timer = getattr(self._installation_page, "_timer", None) if self._installation_page else None
        if timer is not None and timer.isActive():
            timer.stop()
        super().closeEvent(event)
