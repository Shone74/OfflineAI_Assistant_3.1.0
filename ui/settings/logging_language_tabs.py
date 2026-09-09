"""Logging and Language settings tabs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QWidget,
)

from core.config_manager import ConfigManager
from core.event_bus import EventBus


class LoggingTab(QWidget):
    """Tab for logging level selection."""

    def __init__(
        self,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._event_bus = event_bus
        layout = QFormLayout(self)

        self._log_combo = QComboBox()
        self._log_combo.addItems(["Normal (INFO)", "Verbose (DEBUG)"])
        self._log_combo.currentIndexChanged.connect(self._on_log_level_changed)
        layout.addRow(QLabel("<b>Log Level</b>"), self._log_combo)

    def _on_log_level_changed(self, _index: int = 0) -> None:
        """Save log level immediately on change (consistent with other tabs)."""
        if not hasattr(self, "_config_ref") or self._config_ref is None:
            return
        level = self.get_log_level()
        self._config_ref.set("logging.level", level)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "logging.level", "value": level}
            )

    def load_settings(self, config: ConfigManager) -> None:
        self._config_ref = config
        level = config.get("logging.level", "INFO")
        self._log_combo.setCurrentIndex(1 if level == "DEBUG" else 0)

    def get_log_level(self) -> str:
        text = self._log_combo.currentText()
        if "DEBUG" in text:
            return "DEBUG"
        return "INFO"

    def save_settings(self, config: ConfigManager) -> None:
        """Persist log level and publish CONFIG_CHANGED.

        Unlike the change-handler path which requires ``load_settings`` to
        have been called first, this method unconditionally publishes
        ``CONFIG_CHANGED`` so that runtime subscribers (e.g.
        ``Assistant._on_config_changed``) always receive the update.
        """
        self._config_ref = config
        level = self.get_log_level()
        config.set("logging.level", level)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "logging.level", "value": level}
            )


class LanguageTab(QWidget):
    """Tab for selecting the application language (English only)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["English"])
        layout.addRow(QLabel("<b>Language</b>"), self._lang_combo)

    def load_settings(self, config: ConfigManager) -> None:
        index = self._lang_combo.findText("English")
        if index >= 0:
            self._lang_combo.setCurrentIndex(index)

    def get_language(self) -> str:
        return "en"