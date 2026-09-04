"""Settings stranica za AppShell (Faza 4.9).

Wrapper po workspace dizajnu — brze postavke (tema, jezik) + dugme koje
otvara puni SettingsDialog za sve ostale postavke. Dialog ostaje izvor
sve napredne konfiguracije.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.design.components import Card, make_primary_button, make_section_title


class SettingsPage(QWidget):
    """Glavna Settings stranica u AppShell navigaciji."""

    def __init__(
        self,
        config: Any = None,
        event_bus: Any = None,
        assistant: Any = None,
        plugin_manager: Any = None,
        model_manager: Any = None,
        voice_manager: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._assistant = assistant
        self._plugin_manager = plugin_manager
        self._model_manager = model_manager
        self._voice_manager = voice_manager

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(16)

        title = QLabel("Settings")
        title.setObjectName("page_title")
        subtitle = QLabel("Quick settings — sve napredne opcije su u Advanced Settings.")
        subtitle.setObjectName("page_subtitle")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Quick settings kartica
        quick_card = Card()
        quick_card.card_layout.addWidget(make_section_title("Quick Settings"))

        form = QFormLayout()
        form.setSpacing(10)

        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["grey_emerald", "installer"])
        current_theme = self._get_config("ui.theme", "grey_emerald")
        self._theme_combo.setCurrentText(current_theme)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        form.addRow(QLabel("Theme"), self._theme_combo)

        self._language_combo = QComboBox()
        self._language_combo.addItems(["en", "sr"])
        current_lang = self._get_config("app.language", "en")
        self._language_combo.setCurrentText(current_lang)
        self._language_combo.currentTextChanged.connect(self._on_language_changed)
        form.addRow(QLabel("Language"), self._language_combo)

        quick_card.card_layout.addLayout(form)
        layout.addWidget(quick_card)

        # Advanced dugme — otvara puni SettingsDialog
        advanced_card = Card()
        advanced_card.card_layout.addWidget(make_section_title("Advanced Settings"))
        desc = QLabel(
            "Model, Memory, Voice, Privacy & Data, Filesystem, Storage, "
            "Logging, Plugins — sve u jednom dijalogu."
        )
        desc.setObjectName("card_detail")
        desc.setWordWrap(True)
        advanced_card.card_layout.addWidget(desc)

        self._advanced_btn = make_primary_button("Open Advanced Settings")
        self._advanced_btn.clicked.connect(self._open_advanced)
        advanced_card.card_layout.addWidget(self._advanced_btn)
        advanced_card.add_stretch()
        layout.addWidget(advanced_card)

        layout.addStretch()

    # ------------------------------------------------------------------

    def _get_config(self, key: str, default):
        if self._config is not None:
            try:
                return self._config.get(key, default)
            except Exception:
                return default
        return default

    def _on_theme_changed(self, theme: str) -> None:
        if self._config is None:
            return
        try:
            self._config.set("ui.theme", theme)
            self._config.save()
        except Exception:
            pass
        if self._event_bus is not None:
            try:
                self._event_bus.publish("CONFIG_CHANGED", data={"key": "ui.theme", "value": theme})
            except Exception:
                pass

    def _on_language_changed(self, language: str) -> None:
        if self._config is None:
            return
        try:
            self._config.set("app.language", language)
            self._config.save()
        except Exception:
            pass
        if self._event_bus is not None:
            try:
                self._event_bus.publish("CONFIG_CHANGED", data={"key": "app.language", "value": language})
            except Exception:
                pass

    def _open_advanced(self) -> None:
        from ui.settings import SettingsDialog

        dialog = SettingsDialog(
            config=self._config,
            event_bus=self._event_bus,
            assistant=self._assistant,
            plugin_manager=self._plugin_manager,
            model_manager=self._model_manager,
            voice_manager=self._voice_manager,
        )
        dialog.exec()
