"""Settings dialog — model, appearance, profile customization.

Persists changes through the :class:`ConfigManager` and publishes a
``CONFIG_CHANGED`` event so the rest of the app can react.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.assistant import Assistant
from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.paths import CONFIG_DIR, DATA_DIR, LLM_DIR, LOGS_DIR
from plugins.manager import PluginManager
from ui.translations import Language


class ProfileTab(QWidget):
    """Tab for editing identity section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._name_edit = QLineEdit()
        layout.addRow(QLabel("<b>Name</b> (optional)"), self._name_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("Short assistant description...")
        self._desc_edit.setFixedHeight(80)
        layout.addRow(QLabel("<b>Description</b>"), self._desc_edit)

    def load_profile(self, profile: dict) -> None:
        identity = profile.get("identity", {})
        self._name_edit.setText(identity.get("name") or "")
        self._desc_edit.setPlainText(identity.get("description") or "")

    def get_identity(self) -> dict:
        name = self._name_edit.text().strip() or None
        return {
            "name": name,
            "description": self._desc_edit.toPlainText().strip(),
        }


class CommunicationTab(QWidget):
    """Tab for editing communication section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._language_combo = QComboBox()
        self._language_combo.addItems(["auto", "Serbian", "English", "Spanish", "French"])
        layout.addRow(QLabel("<b>Language</b>"), self._language_combo)

        self._tone_combo = QComboBox()
        self._tone_combo.addItems(["neutral", "friendly", "professional", "casual", "humorous", "formal"])
        layout.addRow(QLabel("<b>Tone</b>"), self._tone_combo)

        self._formality_combo = QComboBox()
        self._formality_combo.addItems(["neutral", "informal", "formal"])
        layout.addRow(QLabel("<b>Formality</b>"), self._formality_combo)

        self._response_style_combo = QComboBox()
        self._response_style_combo.addItems(["balanced", "concise", "verbose", "technical", "casual"])
        layout.addRow(QLabel("<b>Response Style</b>"), self._response_style_combo)

    def load_profile(self, profile: dict) -> None:
        comm = profile.get("communication", {})
        self._language_combo.setCurrentText(comm.get("language", "auto"))
        self._tone_combo.setCurrentText(comm.get("tone", "neutral"))
        self._formality_combo.setCurrentText(comm.get("formality", "neutral"))
        self._response_style_combo.setCurrentText(comm.get("response_style", "balanced"))

    def get_communication(self) -> dict:
        return {
            "language": self._language_combo.currentText(),
            "tone": self._tone_combo.currentText(),
            "formality": self._formality_combo.currentText(),
            "response_style": self._response_style_combo.currentText(),
        }


class PersonalityTab(QWidget):
    """Tab for editing personality section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._humor_slider = QSlider(Qt.Horizontal)
        self._humor_slider.setRange(0, 100)
        self._humor_label = QLabel("0.5")
        humor_layout = QHBoxLayout()
        humor_layout.addWidget(self._humor_slider)
        humor_layout.addWidget(self._humor_label)
        layout.addRow(QLabel("<b>Humor</b>"), humor_layout)

        self._proactivity_slider = QSlider(Qt.Horizontal)
        self._proactivity_slider.setRange(0, 100)
        self._proactivity_label = QLabel("0.5")
        proact_layout = QHBoxLayout()
        proact_layout.addWidget(self._proactivity_slider)
        proact_layout.addWidget(self._proactivity_label)
        layout.addRow(QLabel("<b>Proaktivnost</b>"), proact_layout)

        self._traits_edit = QLineEdit()
        self._traits_edit.setPlaceholderText("npr: slobalan, strucan, empaticki")
        layout.addRow(QLabel("<b>Osobine (odvojene zarezom)</b>"), self._traits_edit)

        self._humor_slider.valueChanged.connect(self._on_humor_changed)
        self._proactivity_slider.valueChanged.connect(self._on_proactivity_changed)

    def _on_humor_changed(self, val: int) -> None:
        self._humor_label.setText(f"{val / 100:.2f}")

    def _on_proactivity_changed(self, val: int) -> None:
        self._proactivity_label.setText(f"{val / 100:.2f}")

    def load_profile(self, profile: dict) -> None:
        personality = profile.get("personality", {})
        humor = personality.get("humor", 0.5)
        self._humor_slider.setValue(int(humor * 100))
        self._humor_label.setText(f"{humor:.2f}")

        proact = personality.get("proactivity", 0.3)
        self._proactivity_slider.setValue(int(proact * 100))
        self._proactivity_label.setText(f"{proact:.2f}")

        traits = personality.get("traits", [])
        self._traits_edit.setText(", ".join(traits))

    def get_personality(self) -> dict:
        traits_text = self._traits_edit.text().strip()
        traits = [t.strip() for t in traits_text.split(",") if t.strip()]
        return {
            "humor": self._humor_slider.value() / 100,
            "proactivity": self._proactivity_slider.value() / 100,
            "traits": traits,
        }


class ExpertiseTab(QWidget):
    """Tab for editing expertise section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._areas_edit = QLineEdit()
        self._areas_edit.setPlaceholderText("npr: programiranje, medicina, finansije")
        layout.addRow(QLabel("<b>Obsahruto podrska</b> (odvojene zarezom)"), self._areas_edit)

    def load_profile(self, profile: dict) -> None:
        expertise = profile.get("expertise", {})
        areas = expertise.get("areas", [])
        self._areas_edit.setText(", ".join(areas))

    def get_expertise(self) -> dict:
        areas_text = self._areas_edit.text().strip()
        areas = [a.strip() for a in areas_text.split(",") if a.strip()]
        return {"areas": areas}


class BehaviorTab(QWidget):
    """Tab for editing behavior section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._approach_combo = QComboBox()
        self._approach_combo.addItems(["direct", "educational", "collaborative"])
        layout.addRow(QLabel("<b>Pristup</b>"), self._approach_combo)

        self._uncertainty_combo = QComboBox()
        self._uncertainty_combo.addItems(["ask_clarify", "guess", "hedge"])
        layout.addRow(QLabel("<b>Rukovanje nesigurnoscima</b>"), self._uncertainty_combo)

        self._question_combo = QComboBox()
        self._question_combo.addItems(["open_ended", "closed", "optional"])
        layout.addRow(QLabel("<b>Vrsta pitanja</b>"), self._question_combo)

    def load_profile(self, profile: dict) -> None:
        behavior = profile.get("behavior", {})
        self._approach_combo.setCurrentText(behavior.get("response_approach", "direct"))
        self._uncertainty_combo.setCurrentText(behavior.get("uncertainty_handling", "ask_clarify"))
        self._question_combo.setCurrentText(behavior.get("question_style", "open_ended"))

    def get_behavior(self) -> dict:
        return {
            "response_approach": self._approach_combo.currentText(),
            "uncertainty_handling": self._uncertainty_combo.currentText(),
            "question_style": self._question_combo.currentText(),
        }


class BoundariesTab(QWidget):
    """Tab for editing boundaries section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._custom_instructions = QTextEdit()
        self._custom_instructions.setPlaceholderText("Dodatna ograniczenja ili uputstva...")
        self._custom_instructions.setFixedHeight(100)
        layout.addRow(QLabel("<b>Dodata uputstva</b>"), self._custom_instructions)

    def load_profile(self, profile: dict) -> None:
        boundaries = profile.get("boundaries", {})
        self._custom_instructions.setPlainText(boundaries.get("custom_instructions", ""))

    def get_boundaries(self) -> dict:
        return {
            "custom_instructions": self._custom_instructions.toPlainText().strip(),
        }


class LanguageTab(QWidget):
    """Tab for selecting application language."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["English", "Serbian"])
        layout.addRow(QLabel("<b>Language</b>"), self._lang_combo)

    def load_settings(self, config: ConfigManager) -> None:
        lang_code = config.get("app.language", "en")
        try:
            lang = Language.from_string(lang_code)
        except ValueError:
            lang = Language.ENGLISH
        
        index = self._lang_combo.findText(lang.value.title() if lang.value == "en" else 
                                           ("English" if lang.value == "sr" else "Serbian"))
        if index >= 0:
            self._lang_combo.setCurrentIndex(index)

    def get_language(self) -> str:
        text = self._lang_combo.currentText()
        if text == "English":
            return "en"
        if text == "Serbian":
            return "sr"
        return "en"


class ModelStatusTab(QWidget):
    """Tab showing model status information with management button."""

    def __init__(self, model_manager: Any | None = None, event_bus: Any | None = None, config: Any | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model_manager = model_manager
        self._event_bus = event_bus
        self._config = config
        self._scan_thread: Any = None
        layout = QFormLayout(self)

        self._model_name = QLabel("N/A")
        self._model_status = QLabel("Unknown")
        self._model_path = QLabel(str(LLM_DIR))

        layout.addRow(QLabel("<b>Active Model</b>"), self._model_name)
        layout.addRow(QLabel("<b>Status</b>"), self._model_status)
        layout.addRow(QLabel("<b>Models Folder</b>"), self._model_path)

        self._btn_manage = QPushButton("Select Models Folder")
        self._btn_manage.clicked.connect(self._select_models_folder)
        self._btn_manage.setAccessibleName("Select models folder")
        layout.addRow("", self._btn_manage)

    def load_settings(self, config: ConfigManager) -> None:
        model_name = config.get("ai.model_name", "N/A")
        self._model_name.setText(model_name)
        has_llama = True
        try:
            import llama_cpp  # noqa: F401
        except (ImportError, RuntimeError):
            has_llama = False

        if has_llama:
            self._model_status.setText("Ready" if model_name != "N/A" else "Not loaded")
        else:
            self._model_status.setText("Runtime unavailable (llama-cpp-python not installed)")
            self._model_status.setStyleSheet("QLabel { color: #D96565; }")

        if self._model_manager is not None:
            self._model_path.setText(str(self._model_manager.models_dir))
            models = self._model_manager.list_models()
            if models:
                self._model_status.setText(f"{len(models)} model(s) found")
            self._update_model_name_from_manager()

    def _update_model_name_from_manager(self) -> None:
        if self._model_manager is None:
            return
        active = self._model_manager.get_active_model()
        if active is not None:
            self._model_name.setText(active.name)

    def _select_models_folder(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Models Folder",
            str(self._model_manager.models_dir if self._model_manager else "."),
        )
        if directory and self._model_manager is not None:
            from pathlib import Path

            self._model_path.setText("Scanning...")
            self._btn_manage.setEnabled(False)
            QApplication.processEvents()

            class ScanThread(QThread):
                finished = Signal()

                def __init__(self, manager, directory):
                    super().__init__()
                    self._manager = manager
                    self._directory = Path(directory)

                def run(self) -> None:
                    self._manager.set_models_dir(self._directory)

            thread = ScanThread(self._model_manager, directory)
            thread.finished.connect(
                lambda: self._on_models_scanned(directory, thread)
            )
            thread.start()
            self._scan_thread = thread

    def _on_models_scanned(self, directory: str, thread) -> None:
        if self._model_manager is not None:
            self._model_path.setText(str(self._model_manager.models_dir))
            self._model_path.updateGeometry()
        self._btn_manage.setEnabled(True)
        if self._config is not None:
            self._config.set("ai.models_dir", directory)
        if self._event_bus is not None:
            self._event_bus.publish("CONFIG_CHANGED", data={"key": "ai.models_dir", "value": directory})
        if self._model_manager is not None:
            models = self._model_manager.list_models()
            self._model_status.setText(
                f"{len(models)} model(s) found" if models else "No models found"
            )
        self._scan_thread = None


class StorageTab(QWidget):
    """Tab showing storage paths information."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._data_path = QLabel(str(DATA_DIR))
        self._config_path = QLabel(str(CONFIG_DIR))
        self._logs_path = QLabel(str(LOGS_DIR))

        layout.addRow(QLabel("<b>Data Folder</b>"), self._data_path)
        layout.addRow(QLabel("<b>Config Location</b>"), self._config_path)
        layout.addRow(QLabel("<b>Logs Location</b>"), self._logs_path)

    def load_settings(self, config: ConfigManager) -> None:
        """Load storage settings from config."""


class FilesystemSecurityTab(QWidget):
    """Tab for managing filesystem access policy (read/write roots).

    Allows the user to:
      * view current read and write roots
      * add new read/write roots via folder dialogs
      * remove existing roots
      * toggle symlink following
      * reset to safe defaults

    Changes are persisted to the ConfigManager's ``filesystem`` section
    and published as ``CONFIG_CHANGED`` events.
    """

    _GRAPHITE_CARD = "#1C2221"
    _GRAPHITE_BORDER = "#29302E"
    _TEXT_PRIMARY = "#EDF3F0"
    _EMERALD = "#1D8A68"
    _RED = "#C0392B"

    def __init__(
        self,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config: ConfigManager | None = None
        self._event_bus = event_bus

        main_layout = QVBoxLayout(self)

        # Enable/disable toggle
        self._enabled_checkbox = QCheckBox("Enable filesystem security")
        self._enabled_checkbox.setChecked(True)
        self._enabled_checkbox.stateChanged.connect(self._on_enabled_changed)
        main_layout.addWidget(self._enabled_checkbox)

        # Symlink toggle
        self._symlink_checkbox = QCheckBox("Follow symlinks")
        self._symlink_checkbox.setChecked(True)
        self._symlink_checkbox.stateChanged.connect(self._on_symlink_changed)
        main_layout.addWidget(self._symlink_checkbox)

        # Read roots section
        main_layout.addWidget(QLabel("<b>READ ACCESS</b>"))
        self._read_list = QListWidget()
        main_layout.addWidget(self._read_list)
        read_btns = QHBoxLayout()
        self._btn_add_read = QPushButton("+ Add Read Folder")
        self._btn_add_read.clicked.connect(self._on_add_read)
        self._btn_remove_read = QPushButton("− Remove")
        self._btn_remove_read.clicked.connect(self._on_remove_read)
        read_btns.addWidget(self._btn_add_read)
        read_btns.addWidget(self._btn_remove_read)
        main_layout.addLayout(read_btns)

        # Write roots section
        main_layout.addWidget(QLabel("<b>WRITE ACCESS</b>"))
        self._write_list = QListWidget()
        main_layout.addWidget(self._write_list)
        write_btns = QHBoxLayout()
        self._btn_add_write = QPushButton("+ Add Write Folder")
        self._btn_add_write.clicked.connect(self._on_add_write)
        self._btn_remove_write = QPushButton("− Remove")
        self._btn_remove_write.clicked.connect(self._on_remove_write)
        write_btns.addWidget(self._btn_add_write)
        write_btns.addWidget(self._btn_remove_write)
        main_layout.addLayout(write_btns)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8C9692; font-size: 11px;")
        main_layout.addWidget(self._status_label)

        # Reset button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._on_reset)
        main_layout.addWidget(reset_btn)

        main_layout.addStretch()

    def load_settings(self, config: ConfigManager) -> None:
        """Load filesystem policy from config into the UI."""
        self._config = config
        self._enabled_checkbox.setChecked(config.get("filesystem.enabled", True))
        self._symlink_checkbox.setChecked(config.get("filesystem.follow_symlinks", True))

        self._read_list.clear()
        for root in config.get("filesystem.read_roots", []) or []:
            self._read_list.addItem(root)

        self._write_list.clear()
        for root in config.get("filesystem.write_roots", []) or []:
            self._write_list.addItem(root)

        self._update_status()

    def save_settings(self, config: ConfigManager) -> None:
        """Persist current UI state to config."""
        enabled = self._enabled_checkbox.isChecked()
        follow_symlinks = self._symlink_checkbox.isChecked()
        read_roots = [
            self._read_list.item(i).text() for i in range(self._read_list.count())
        ]
        write_roots = [
            self._write_list.item(i).text() for i in range(self._write_list.count())
        ]

        config.set("filesystem.enabled", enabled)
        config.set("filesystem.follow_symlinks", follow_symlinks)
        config.set("filesystem.read_roots", read_roots)
        config.set("filesystem.write_roots", write_roots)

        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.enabled", "value": enabled},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.follow_symlinks", "value": follow_symlinks},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.read_roots", "value": read_roots},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.write_roots", "value": write_roots},
            )

        self._update_status()

    def _update_status(self) -> None:
        if not self._config:
            return
        enabled = self._config.get("filesystem.enabled", True)
        read_roots = self._config.get("filesystem.read_roots", [])
        write_roots = self._config.get("filesystem.write_roots", [])
        if not isinstance(read_roots, list):
            read_roots = []
        if not isinstance(write_roots, list):
            write_roots = []
        read_count = len(read_roots)
        write_count = len(write_roots)
        if not enabled:
            self._status_label.setText("Filesystem security: <b>DISABLED</b> (all paths allowed)")
        elif not write_count:
            self._status_label.setText(
                f"Filesystem security: <b>enabled</b> — "
                f"{read_count} read root(s), {write_count} write root(s). "
                f"Writes are <font color='{self._RED}'>denied</font> until a write root is configured."
            )
        else:
            self._status_label.setText(
                f"Filesystem security: <b>enabled</b> — "
                f"{read_count} read root(s), {write_count} write root(s). "
                f"All operations restricted to configured roots."
            )

    def _on_enabled_changed(self, state: int) -> None:
        if self._config:
            self._config.set("filesystem.enabled", bool(state))
            self._update_status()
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.enabled", "value": bool(state)},
                )

    def _on_symlink_changed(self, state: int) -> None:
        if self._config:
            self._config.set("filesystem.follow_symlinks", bool(state))
            self._update_status()
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.follow_symlinks", "value": bool(state)},
                )

    def _reconfigure_validator(self) -> None:
        if self._config is not None:
            from tools.file_security import configure_default_validator_from_config

            configure_default_validator_from_config(self._config)

    def _on_add_read(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Read Folder", "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._read_list.addItem(folder)
            if self._config:
                read_roots = [
                    self._read_list.item(i).text()
                    for i in range(self._read_list.count())
                ]
                self._config.set("filesystem.read_roots", read_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.read_roots", "value": read_roots},
                    )
            self._update_status()

    def _on_remove_read(self) -> None:
        current = self._read_list.currentRow()
        if current >= 0:
            self._read_list.takeItem(current)
            if self._config:
                read_roots = [
                    self._read_list.item(i).text()
                    for i in range(self._read_list.count())
                ]
                self._config.set("filesystem.read_roots", read_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.read_roots", "value": read_roots},
                    )
            self._update_status()

    def _on_add_write(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Write Folder", "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._write_list.addItem(folder)
            if self._config:
                write_roots = [
                    self._write_list.item(i).text()
                    for i in range(self._write_list.count())
                ]
                self._config.set("filesystem.write_roots", write_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.write_roots", "value": write_roots},
                    )
            self._update_status()

    def _on_remove_write(self) -> None:
        current = self._write_list.currentRow()
        if current >= 0:
            self._write_list.takeItem(current)
            if self._config:
                write_roots = [
                    self._write_list.item(i).text()
                    for i in range(self._write_list.count())
                ]
                self._config.set("filesystem.write_roots", write_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.write_roots", "value": write_roots},
                    )
            self._update_status()

    def _on_reset(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Reset")
        msg.setText("Reset filesystem security to defaults?\n\nThis will clear all configured roots.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._do_reset()

    def _do_reset(self) -> None:
        """Perform the actual reset (separate from confirmation dialog for testing)."""
        if self._config is not None:
            self._config.set("filesystem.enabled", True)
            self._config.set("filesystem.read_roots", [])
            self._config.set("filesystem.write_roots", [])
            self._config.set("filesystem.follow_symlinks", True)
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.enabled", "value": True},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.read_roots", "value": []},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.write_roots", "value": []},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.follow_symlinks", "value": True},
                )
        self._read_list.clear()
        self._write_list.clear()
        self._enabled_checkbox.setChecked(True)
        self._symlink_checkbox.setChecked(True)
        self._update_status()


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


class PluginTab(QWidget):
    """Tab for managing plugins via PluginManager."""

    def __init__(self, plugin_manager: PluginManager | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self._event_bus = plugin_manager.event_bus if plugin_manager is not None else None

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        layout.addWidget(self._list)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setFixedHeight(80)
        layout.addWidget(self._details)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_enable = QPushButton("Enable")
        self._btn_disable = QPushButton("Disable")
        self._btn_unload = QPushButton("Unload")
        btn_layout.addWidget(self._btn_enable)
        btn_layout.addWidget(self._btn_disable)
        btn_layout.addWidget(self._btn_unload)
        layout.addLayout(btn_layout)

        self._btn_enable.clicked.connect(self._on_enable)
        self._btn_disable.clicked.connect(self._on_disable)
        self._btn_unload.clicked.connect(self._on_unload)
        self._list.currentItemChanged.connect(self._on_selection_changed)

        if self._event_bus is not None:
            self._event_bus.subscribe("PLUGIN_ENABLED", self._refresh)
            self._event_bus.subscribe("PLUGIN_DISABLED", self._refresh)
            self._event_bus.subscribe("PLUGIN_LOADED", self._refresh)
            self._event_bus.subscribe("PLUGIN_LOAD_FAILED", self._refresh)
            self._event_bus.subscribe("PLUGIN_ERROR", self._refresh)
            self._event_bus.subscribe("PLUGIN_UNLOADED", self._refresh)

        self._refresh()

    def _refresh(self, *_: Any) -> None:
        self._list.clear()
        if self._plugin_manager is None:
            return
        for pid in sorted(self._plugin_manager.list_plugin_ids()):
            state = self._plugin_manager.get_state(pid)
            metadata = self._plugin_manager.get_metadata(pid)
            name = metadata.name if metadata else pid
            item = QListWidgetItem(f"{name} ({state.value if state is not None else 'unknown'})")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self._list.addItem(item)
        self._update_details()

    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        self._update_details()

    def _update_details(self) -> None:
        item = self._list.currentItem()
        if item is None or self._plugin_manager is None:
            self._details.clear()
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        metadata = self._plugin_manager.get_metadata(pid)
        state = self._plugin_manager.get_state(pid)
        if metadata is None:
            self._details.clear()
            return
        lines = [
            f"<b>ID:</b> {metadata.id}",
            f"<b>Name:</b> {metadata.name}",
            f"<b>Version:</b> {metadata.version}",
            f"<b>Author:</b> {metadata.author or 'N/A'}",
            f"<b>State:</b> {state.value if state is not None else 'unknown'}",
            f"<b>Description:</b> {metadata.description or 'N/A'}",
        ]
        if metadata.dependencies:
            lines.append(f"<b>Dependencies:</b> {', '.join(metadata.dependencies)}")
        self._details.setText("<br>".join(lines))

    def _on_enable(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.enable(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _on_disable(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.disable(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _on_unload(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.unload(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _current_pid(self) -> str | None:
        item = self._list.currentItem()
        if item is not None:
            return item.data(Qt.ItemDataRole.UserRole)
        if self._list.count() > 0:
            return self._list.item(0).data(Qt.ItemDataRole.UserRole)
        return None


class _AudioTestWorker(QThread):
    """Background worker for the Test Microphone feature.

    Records for ``duration`` seconds, then plays back the captured audio
    through the selected output device.  Status is communicated to the GUI
    via Qt signals (queued to the main thread) so widgets are never touched
    from the worker thread.
    """

    status_changed = Signal(str)
    finished = Signal()

    def __init__(self, audio_manager: Any, duration: float = 3.0) -> None:
        super().__init__()
        self._audio = audio_manager
        self._duration = duration

    def run(self) -> None:
        try:
            self.status_changed.emit("Recording...")
            if not self._audio.is_available():
                self.status_changed.emit("Audio test failed: audio backend unavailable")
                self.finished.emit()
                return
            self._audio.start_recording()
            self.msleep(int(self._duration * 1000))
            pcm, sr = self._audio.stop_recording()
            self.status_changed.emit("Playing...")
            if pcm:
                out_dev = self._audio.resolve_output_device()
                if out_dev is not None:
                    self._audio._output_device_index = out_dev
                self._audio.play_audio(pcm, sr)
                self.msleep(int(len(pcm) / (sr * 2) * 1000) + 50)
            self.status_changed.emit("Test complete")
        except OSError as exc:
            self.status_changed.emit(f"Audio test failed: {exc}")
        except RuntimeError as exc:
            self.status_changed.emit(f"Audio test failed: {exc}")
        finally:
            self.finished.emit()


class AudioSettingsTab(QWidget):
    """Tab for audio device selection, WASAPI preferences, and microphone test."""

    _SYSTEM_DEFAULT = "<System Default>"

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        voice_manager: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._voice_manager = voice_manager
        self._audio_manager: Any = None
        self._test_worker: Any = None
        self._selected_input_device: dict[str, Any] | None = None
        self._selected_output_device: dict[str, Any] | None = None
        self._input_devices: list[dict[str, Any]] = []
        self._output_devices: list[dict[str, Any]] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # --- Input device ---
        input_group = QGroupBox("Input Device")
        input_layout = QFormLayout(input_group)
        self._input_combo = QComboBox()
        self._input_combo.currentIndexChanged.connect(self._on_input_device_changed)
        input_layout.addRow(QLabel("Microphone"), self._input_combo)
        main_layout.addWidget(input_group)

        # --- Output device ---
        output_group = QGroupBox("Output Device")
        output_layout = QFormLayout(output_group)
        self._output_combo = QComboBox()
        self._output_combo.currentIndexChanged.connect(self._on_output_device_changed)
        output_layout.addRow(QLabel("Output Device"), self._output_combo)
        main_layout.addWidget(output_group)

        # --- WASAPI preferences ---
        wasapi_group = QGroupBox("WASAPI Capture")
        wasapi_layout = QVBoxLayout(wasapi_group)
        self._prefer_wasapi_chk = QCheckBox("Prefer WASAPI")
        self._prefer_wasapi_chk.setChecked(True)
        self._prefer_wasapi_chk.stateChanged.connect(
            lambda state: self._on_wasapi_preference_changed(bool(state))
        )
        wasapi_layout.addWidget(self._prefer_wasapi_chk)

        self._fallback_chk = QCheckBox("Allow WASAPI fallback to MME")
        self._fallback_chk.setChecked(True)
        self._fallback_chk.stateChanged.connect(
            lambda state: self._on_fallback_changed(bool(state))
        )
        wasapi_layout.addWidget(self._fallback_chk)
        main_layout.addWidget(wasapi_group)

        # --- Test Microphone ---
        test_group = QGroupBox("Microphone Test")
        test_layout = QVBoxLayout(test_group)
        btn_row = QHBoxLayout()
        self._btn_test = QPushButton("Test Microphone")
        self._btn_test.clicked.connect(self._on_test_microphone)
        btn_row.addWidget(self._btn_test)
        self._btn_refresh = QPushButton("Refresh Devices")
        self._btn_refresh.clicked.connect(self._on_refresh_devices)
        btn_row.addWidget(self._btn_refresh)
        test_layout.addLayout(btn_row)
        self._test_status = QLabel("Ready")
        self._test_status.setStyleSheet("color: #8C9692;")
        test_layout.addWidget(self._test_status)
        main_layout.addWidget(test_group)

        # --- Device information ---
        info_group = QGroupBox("Selected Device Information")
        info_layout = QFormLayout(info_group)
        self._info_name = QLabel("—")
        self._info_hostapi = QLabel("—")
        self._info_samplerate = QLabel("—")
        self._info_channels = QLabel("—")
        self._info_index = QLabel("—")
        info_layout.addRow(QLabel("Device name"), self._info_name)
        info_layout.addRow(QLabel("Host API"), self._info_hostapi)
        info_layout.addRow(QLabel("Native sample rate"), self._info_samplerate)
        info_layout.addRow(QLabel("Channels"), self._info_channels)
        info_layout.addRow(QLabel("Runtime index"), self._info_index)
        main_layout.addWidget(info_group)

        main_layout.addStretch()

    def load_settings(self, config: ConfigManager) -> None:
        self._populate_devices()
        input_name = config.get("audio.input_device_name", "")
        input_hostapi = config.get("audio.input_device_hostapi", "")
        self._select_combo_device(self._input_combo, input_name, input_hostapi)

        output_name = config.get("audio.output_device_name", "")
        output_hostapi = config.get("audio.output_device_hostapi", "")
        self._select_combo_device(self._output_combo, output_name, output_hostapi)

        self._prefer_wasapi_chk.setChecked(config.get("audio.prefer_wasapi", True))
        self._fallback_chk.setChecked(config.get("audio.wasapi_fallback_to_mme", True))

    def save_settings(self, config: ConfigManager) -> None:
        selected = self._combo_device_data(self._input_combo)
        if selected is None:
            config.set("audio.input_device_index", None)
            config.set("audio.input_device_name", "")
            config.set("audio.input_device_hostapi", "")
        else:
            config.set("audio.input_device_index", selected.get("index"))
            config.set("audio.input_device_name", selected.get("name", ""))
            config.set("audio.input_device_hostapi", selected.get("hostapi_name", ""))

        selected_out = self._combo_device_data(self._output_combo)
        if selected_out is None:
            config.set("audio.output_device_index", None)
            config.set("audio.output_device_name", "")
            config.set("audio.output_device_hostapi", "")
        else:
            config.set("audio.output_device_index", selected_out.get("index"))
            config.set("audio.output_device_name", selected_out.get("name", ""))
            config.set("audio.output_device_hostapi", selected_out.get("hostapi_name", ""))

        config.set("audio.prefer_wasapi", self._prefer_wasapi_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.prefer_wasapi", "value": self._prefer_wasapi_chk.isChecked()}
            )
        config.set("audio.wasapi_fallback_to_mme", self._fallback_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.wasapi_fallback_to_mme", "value": self._fallback_chk.isChecked()}
            )
        # Notify VoiceManager to rebuild audio managers with updated device config
        input_name = config.get("audio.input_device_name", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.input", "value": input_name}
            )
        output_name = config.get("audio.output_device_name", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.output", "value": output_name}
            )

    def _get_audio_manager(self) -> Any:
        """Return the SoundDeviceAudioManager from VoiceManager, or None."""
        if self._audio_manager is not None:
            return self._audio_manager
        if self._voice_manager is not None:
            am = getattr(self._voice_manager, "_audio", None)
            if am is not None and am.is_available():
                self._audio_manager = am
        return self._audio_manager

    def _populate_devices(self) -> None:
        am = self._get_audio_manager()
        if am is None or not am.is_available():
            self._input_combo.blockSignals(True)
            self._input_combo.clear()
            self._input_combo.addItem(self._SYSTEM_DEFAULT)
            self._input_combo.setItemData(0, {"system_default": True})
            self._input_combo.setCurrentIndex(0)
            self._input_combo.blockSignals(False)

            self._output_combo.blockSignals(True)
            self._output_combo.clear()
            self._output_combo.addItem(self._SYSTEM_DEFAULT)
            self._output_combo.setItemData(0, {"system_default": True})
            self._output_combo.setCurrentIndex(0)
            self._output_combo.blockSignals(False)
            return
        if not hasattr(am, "list_devices") or not callable(am.list_devices):
            return

        # --- Input devices ---
        saved_input_name = self._config.get("audio.input_device_name", "")
        saved_input_hostapi = self._config.get("audio.input_device_hostapi", "")
        self._input_devices = am.list_devices()
        self._input_combo.blockSignals(True)
        self._build_device_combo(self._input_combo, self._input_devices, "input")
        self._restore_combo_selection(
            self._input_combo, self._input_devices, "input",
            saved_input_name, saved_input_hostapi,
        )
        self._input_combo.blockSignals(False)

        # --- Output devices ---
        saved_output_name = self._config.get("audio.output_device_name", "")
        saved_output_hostapi = self._config.get("audio.output_device_hostapi", "")
        self._output_devices = (
            am.list_output_devices()
            if hasattr(am, "list_output_devices") and callable(am.list_output_devices)
            else []
        )
        self._output_combo.blockSignals(True)
        self._build_device_combo(self._output_combo, self._output_devices, "output")
        self._restore_combo_selection(
            self._output_combo, self._output_devices, "output",
            saved_output_name, saved_output_hostapi,
        )
        self._output_combo.blockSignals(False)

        # Update device info for the restored selection
        self._update_device_info(
            self._combo_device_data(self._input_combo), "input"
        )
        self._update_device_info(
            self._combo_device_data(self._output_combo), "output"
        )

    def _host_api_name(self, devices: list[dict[str, Any]], device: dict[str, Any]) -> str:
        """Resolve the human-readable host API name for a device."""
        import sounddevice as sd

        ha_idx = device.get("hostapi", -1)
        if ha_idx >= 0:
            try:
                apis = sd.query_hostapis()
                return apis[ha_idx]["name"]
            except Exception:
                logger.debug("host API name lookup failed", exc_info=True)
        return "Unknown"

    def _format_device_label(
        self, device: dict[str, Any], hostapi_name: str, kind: str
    ) -> str:
        name = device.get("name", "Unknown")
        sr = device.get("default_samplerate", 0)
        if kind == "input":
            ch = device.get("max_input_channels", 0)
        else:
            ch = device.get("max_output_channels", 0)
        sr_str = f"{int(sr)} Hz" if sr else "?"
        return f"{name} — {hostapi_name} — {sr_str} — {ch} ch"

    def _build_device_combo(
        self, combo: QComboBox, devices: list[dict[str, Any]], kind: str
    ) -> None:
        """Populate *combo* with System Default + device items.

        Signals remain blocked — the caller (``_populate_devices``) is
        responsible for unblocking after restoring the persisted selection,
        so that ``_on_input_device_changed`` does not fire during initialization.
        """
        combo.clear()
        combo.addItem(self._SYSTEM_DEFAULT)
        combo.setItemData(0, {"system_default": True})
        for dev in devices:
            ha_name = self._host_api_name(devices, dev)
            label = self._format_device_label(dev, ha_name, kind)
            data = {
                "system_default": False,
                "index": dev.get("index"),
                "name": dev.get("name", ""),
                "hostapi_name": ha_name,
                "hostapi_index": dev.get("hostapi", -1),
                "sample_rate": dev.get("default_samplerate", 0),
                "channels": dev.get("max_input_channels" if kind == "input" else "max_output_channels", 0),
            }
            combo.addItem(label)
            combo.setItemData(combo.count() - 1, data)

    def _restore_combo_selection(
        self,
        combo: QComboBox,
        devices: list[dict[str, Any]],
        kind: str,
        saved_name: str,
        saved_hostapi: str,
    ) -> None:
        if not saved_name:
            combo.setCurrentIndex(0)
            return
        found = False
        for i in range(combo.count()):
            data = combo.itemData(i)
            if (
                data
                and not data.get("system_default")
                and saved_name in data.get("name", "")
                and (
                    not saved_hostapi
                    or saved_hostapi in data.get("hostapi_name", "")
                )
            ):
                combo.setCurrentIndex(i)
                found = True
                break
        if not found:
            combo.setCurrentIndex(0)
            # Mark unavailable
            self._set_device_unavailable(combo)

    def _select_combo_device(
        self, combo: QComboBox, name: str, hostapi: str
    ) -> None:
        if not name:
            combo.setCurrentIndex(0)
            return
        for i in range(combo.count()):
            data = combo.itemData(i)
            if (
                data
                and not data.get("system_default")
                and name in data.get("name", "")
                and (
                    not hostapi
                    or hostapi in data.get("hostapi_name", "")
                )
            ):
                    combo.setCurrentIndex(i)
                    return
        combo.setCurrentIndex(0)

    def _combo_device_data(self, combo: QComboBox) -> dict[str, Any] | None:
        data = combo.itemData(combo.currentIndex())
        if data and data.get("system_default"):
            return None
        return data if data else None

    def _set_device_unavailable(self, combo: QComboBox) -> None:
        label = combo.itemText(combo.currentIndex())
        if self._SYSTEM_DEFAULT not in label:
            combo.setItemText(combo.currentIndex(), f"⚠ {label} (unavailable)")

    def _on_input_device_changed(self, index: int) -> None:
        data = self._combo_device_data(self._input_combo)
        if data is None:
            self._update_device_info(None, "input")
            self._clear_audio_config(self._config)
            return
        self._update_device_info(data, "input")
        self._persist_input_device(data)

    def _on_output_device_changed(self, index: int) -> None:
        data = self._combo_device_data(self._output_combo)
        if data is None:
            self._update_device_info(None, "output")
            self._clear_audio_output_config(self._config)
            return
        self._update_device_info(data, "output")
        self._persist_output_device(data)

    def _persist_input_device(self, data: dict[str, Any]) -> None:
        self._config.set("audio.input_device_index", data.get("index"))
        self._config.set("audio.input_device_name", data.get("name", ""))
        self._config.set("audio.input_device_hostapi", data.get("hostapi_name", ""))
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.input", "value": data.get("name", "")},
            )

    def _clear_audio_config(self, config: ConfigManager) -> None:
        config.set("audio.input_device_index", None)
        config.set("audio.input_device_name", "")
        config.set("audio.input_device_hostapi", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.input", "value": ""},
            )

    def _persist_output_device(self, data: dict[str, Any]) -> None:
        self._config.set("audio.output_device_index", data.get("index"))
        self._config.set("audio.output_device_name", data.get("name", ""))
        self._config.set("audio.output_device_hostapi", data.get("hostapi_name", ""))
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.output", "value": data.get("name", "")},
            )

    def _clear_audio_output_config(self, config: ConfigManager) -> None:
        config.set("audio.output_device_index", None)
        config.set("audio.output_device_name", "")
        config.set("audio.output_device_hostapi", "")
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "audio.output", "value": ""},
            )

    def _on_wasapi_preference_changed(self, checked: bool) -> None:
        self._config.set("audio.prefer_wasapi", checked)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.prefer_wasapi", "value": checked}
            )

    def _on_fallback_changed(self, checked: bool) -> None:
        self._config.set("audio.wasapi_fallback_to_mme", checked)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "audio.wasapi_fallback_to_mme", "value": checked}
            )

    def _on_refresh_devices(self) -> None:
        self._populate_devices()

    def _on_test_microphone(self) -> None:
        am = self._get_audio_manager()
        if am is None or not am.is_available():
            self._test_status.setText("Audio test failed: audio backend unavailable")
            return
        self._btn_test.setEnabled(False)
        self._btn_refresh.setEnabled(False)
        self._test_worker = _AudioTestWorker(am)
        self._test_worker.status_changed.connect(self._on_test_status_changed)
        self._test_worker.finished.connect(self._on_test_finished)
        self._test_worker.start()

    def _on_test_status_changed(self, status: str) -> None:
        self._test_status.setText(status)

    def _on_test_finished(self) -> None:
        self._btn_test.setEnabled(True)
        self._btn_refresh.setEnabled(True)
        self._test_worker = None

    def _update_device_info(self, data: dict[str, Any] | None, kind: str) -> None:
        if data is None:
            self._info_name.setText("—")
            self._info_hostapi.setText("—")
            self._info_samplerate.setText("—")
            self._info_channels.setText("—")
            self._info_index.setText("—")
            return
        self._info_name.setText(data.get("name", "—"))
        self._info_hostapi.setText(data.get("hostapi_name", "—"))
        sr = data.get("sample_rate", 0)
        self._info_samplerate.setText(f"{int(sr)} Hz" if sr else "—")
        ch = data.get("channels", 0)
        self._info_channels.setText(str(ch) if ch else "—")
        self._info_index.setText(str(data.get("index", "—")))


class VoiceSettingsTab(QWidget):
    """Tab for voice/STT/TTS configuration.

    Exposes controls for the STT subsystem (fully functional) and TTS
    subsystem (with stub fallback).  A master "Voice Enabled" checkbox
    controls ``voice.enabled``.
    """

    _LANG_DISPLAY: ClassVar[dict[str, str]] = {"auto": "Auto", "sr": "Serbian", "en": "English"}
    _LANG_VALUES: ClassVar[dict[str, str]] = {"Auto": "auto", "Serbian": "sr", "English": "en"}
    _TTS_PROVIDERS: ClassVar[list[str]] = ["pyttsx3", "stub"]

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        voice_manager: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._voice_manager = voice_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # --- Voice Enabled master switch ---
        self._enabled_chk = QCheckBox("Enable voice input and output")
        self._enabled_chk.setToolTip("When unchecked, voice input (wake-word, STT) and TTS output are disabled")
        self._enabled_chk.stateChanged.connect(self._on_voice_enabled_changed)
        main_layout.addWidget(self._enabled_chk)

        # --- STT / Speech Recognition section ---
        stt_group = QGroupBox("Speech Recognition (STT)")
        stt_layout = QFormLayout(stt_group)

        self._provider_combo = QComboBox()
        self._provider_combo.setToolTip("STT provider: faster-whisper (local) or stub")
        stt_layout.addRow(QLabel("<b>Provider</b>"), self._provider_combo)

        self._model_combo = QComboBox()
        self._model_combo.setToolTip("Whisper model directory under models/voice/stt/")
        stt_layout.addRow(QLabel("<b>Model</b>"), self._model_combo)

        self._device_combo = QComboBox()
        self._device_combo.setToolTip("Computation device for Whisper inference")
        stt_layout.addRow(QLabel("<b>Device</b>"), self._device_combo)

        self._language_combo = QComboBox()
        self._language_combo.setToolTip("Speech recognition language")
        stt_layout.addRow(QLabel("<b>Language</b>"), self._language_combo)

        main_layout.addWidget(stt_group)

        # --- TTS / Speech Synthesis section ---
        tts_group = QGroupBox("Speech Synthesis (TTS)")
        tts_layout = QFormLayout(tts_group)

        self._tts_provider_combo = QComboBox()
        self._tts_provider_combo.setToolTip("TTS provider: pyttsx3 (if installed) or stub")
        tts_layout.addRow(QLabel("<b>Provider</b>"), self._tts_provider_combo)

        self._tts_voice_combo = QComboBox()
        self._tts_voice_combo.setToolTip("Voice to use for speech output (pyttsx3 only)")
        tts_layout.addRow(QLabel("<b>Voice</b>"), self._tts_voice_combo)

        self._tts_rate_slider = QSlider()
        self._tts_rate_slider.setOrientation(Qt.Orientation.Horizontal)
        self._tts_rate_slider.setRange(50, 400)
        self._tts_rate_slider.setSingleStep(10)
        self._tts_rate_slider.setToolTip("Speech rate (words per minute, pyttsx3 only)")
        tts_layout.addRow(QLabel("<b>Rate</b>"), self._tts_rate_slider)

        self._tts_rate_value = QLabel("200")
        tts_layout.addRow(QLabel(""), self._tts_rate_value)

        self._tts_volume_slider = QSlider()
        self._tts_volume_slider.setOrientation(Qt.Orientation.Horizontal)
        self._tts_volume_slider.setRange(0, 100)
        self._tts_volume_slider.setSingleStep(5)
        self._tts_volume_slider.setToolTip("Output volume (0-100%)")
        tts_layout.addRow(QLabel("<b>Volume</b>"), self._tts_volume_slider)

        self._tts_volume_value = QLabel("100%")
        tts_layout.addRow(QLabel(""), self._tts_volume_value)

        main_layout.addWidget(tts_group)

        # --- Status line ---
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8C9692; font-size: 11px;")
        main_layout.addWidget(self._status_label)

        main_layout.addStretch()

        # --- Signal connections (after all controls exist) ---
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        self._model_combo.currentTextChanged.connect(self._on_model_changed)
        self._device_combo.currentTextChanged.connect(self._on_device_changed)
        self._language_combo.currentTextChanged.connect(self._on_language_changed)

        self._tts_provider_combo.currentTextChanged.connect(self._on_tts_provider_changed)
        self._tts_voice_combo.currentTextChanged.connect(self._on_tts_voice_changed)
        self._tts_rate_slider.valueChanged.connect(self._on_tts_rate_changed)
        self._tts_volume_slider.valueChanged.connect(self._on_tts_volume_changed)

    # ------------------------------------------------------------------ #
    # SettingsDialog interface
    # ------------------------------------------------------------------ #
    def load_settings(self, config: ConfigManager) -> None:
        self._populate_providers()
        self._populate_models()
        self._populate_devices()
        self._populate_languages()
        self._populate_tts_providers()
        self._populate_tts_voices()

        stt_cfg = config.get("voice.stt", {})

        provider = stt_cfg.get("provider", "faster-whisper")
        self._provider_combo.setCurrentIndex(max(self._provider_combo.findText(provider), 0))

        model = stt_cfg.get("model", "tiny")
        self._select_combo_text(self._model_combo, model)

        device = stt_cfg.get("device", "auto")
        self._device_combo.setCurrentIndex(max(self._device_combo.findText(device), 0))

        language = config.get("voice.language", "auto")
        display = self._LANG_DISPLAY.get(language, "Auto")
        self._language_combo.setCurrentIndex(max(self._language_combo.findText(display), 0))

        self._enabled_chk.blockSignals(True)
        self._enabled_chk.setChecked(config.get("voice.enabled", True))
        self._enabled_chk.blockSignals(False)

        tts_cfg = config.get("voice.tts", {})
        self._tts_provider_combo.blockSignals(True)
        tts_provider = tts_cfg.get("provider", "pyttsx3")
        self._tts_provider_combo.setCurrentIndex(max(self._tts_provider_combo.findText(tts_provider), 0))
        self._tts_provider_combo.blockSignals(False)

        self._tts_voice_combo.blockSignals(True)
        voice_id = tts_cfg.get("voice", "")
        idx = self._tts_voice_combo.findData(voice_id) if voice_id else -1
        if idx >= 0:
            self._tts_voice_combo.setCurrentIndex(idx)
        elif self._tts_voice_combo.count() > 0:
            self._tts_voice_combo.setCurrentIndex(0)
        self._tts_voice_combo.blockSignals(False)

        self._tts_rate_slider.blockSignals(True)
        self._tts_rate_slider.setValue(tts_cfg.get("rate", 200))
        self._tts_rate_slider.blockSignals(False)
        self._tts_rate_value.setText(str(self._tts_rate_slider.value()))

        self._tts_volume_slider.blockSignals(True)
        self._tts_volume_slider.setValue(int(tts_cfg.get("volume", 1.0) * 100))
        self._tts_volume_slider.blockSignals(False)
        self._tts_volume_value.setText(f"{self._tts_volume_slider.value()}%")

        self._update_status()

    def save_settings(self, config: ConfigManager) -> None:
        config.set("voice.enabled", self._enabled_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.enabled", "value": self._enabled_chk.isChecked()}
            )
        config.set("voice.stt.provider", self._provider_combo.currentText())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.provider", "value": self._provider_combo.currentText()}
            )
        config.set("voice.stt.model", self._model_combo.currentText())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.model", "value": self._model_combo.currentText()}
            )
        config.set("voice.stt.device", self._device_combo.currentText())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.device", "value": self._device_combo.currentText()}
            )
        lang = self._LANG_VALUES.get(self._language_combo.currentText(), "auto")
        config.set("voice.language", lang)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.language", "value": lang}
            )

        config.set("voice.tts.provider", self._tts_provider_combo.currentText())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.provider", "value": self._tts_provider_combo.currentText()}
            )
        voice_id = self._tts_voice_combo.itemData(self._tts_voice_combo.currentIndex()) or ""
        config.set("voice.tts.voice", voice_id)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.voice", "value": voice_id}
            )
        rate = self._tts_rate_slider.value()
        config.set("voice.tts.rate", rate)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.rate", "value": rate}
            )
        volume = self._tts_volume_slider.value() / 100.0
        config.set("voice.tts.volume", volume)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.volume", "value": volume}
            )

    # ------------------------------------------------------------------ #
    # Population helpers
    # ------------------------------------------------------------------ #
    def _populate_providers(self) -> None:
        from voice.stt import _whisper_available

        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        if _whisper_available():
            self._provider_combo.addItem("faster-whisper")
        self._provider_combo.addItem("stub")
        self._provider_combo.blockSignals(False)

    def _populate_models(self) -> None:
        from core.paths import STT_DIR

        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        if STT_DIR.is_dir():
            for d in sorted(STT_DIR.iterdir()):
                if d.is_dir():
                    self._model_combo.addItem(d.name)
        if self._model_combo.count() == 0:
            self._model_combo.addItem("No models found")
            self._model_combo.setEnabled(False)
        else:
            self._model_combo.setEnabled(True)
        self._model_combo.blockSignals(False)

    def _populate_devices(self) -> None:
        from voice.stt import _cuda_available

        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        self._device_combo.addItems(["auto", "cpu", "cuda"])
        if not _cuda_available():
            # Grey out the "cuda" item so users don't select it blindly.
            model = self._device_combo.model()
            cuda_item = model.item(2)
            if cuda_item is not None:
                cuda_item.setEnabled(False)
        self._device_combo.blockSignals(False)

    def _populate_languages(self) -> None:
        self._language_combo.blockSignals(True)
        self._language_combo.clear()
        self._language_combo.addItems(["Auto", "Serbian", "English"])
        self._language_combo.blockSignals(False)

    def _populate_tts_providers(self) -> None:
        from voice.tts import _pyttsx3_available

        self._tts_provider_combo.blockSignals(True)
        self._tts_provider_combo.clear()
        if _pyttsx3_available():
            self._tts_provider_combo.addItem("pyttsx3")
        self._tts_provider_combo.addItem("stub")
        self._tts_provider_combo.blockSignals(False)
        self._populate_tts_voices()

    def _populate_tts_voices(self) -> None:
        from voice.tts import _pyttsx3_available

        self._tts_voice_combo.blockSignals(True)
        self._tts_voice_combo.clear()
        if self._tts_provider_combo.currentText() == "pyttsx3" and _pyttsx3_available():
            try:
                import pyttsx3

                engine = pyttsx3.init()
                for v in engine.getProperty("voices"):
                    engine.setProperty("voice", v.id)
                    self._tts_voice_combo.addItem(v.name, v.id)
                engine.stop()
            except Exception as exc:
                logger.debug("TTS voice enumeration failed: %s", exc)
        if self._tts_voice_combo.count() == 0:
            self._tts_voice_combo.addItem("None available")
            self._tts_voice_combo.setEnabled(False)
        else:
            self._tts_voice_combo.setEnabled(True)
        self._tts_voice_combo.blockSignals(False)

    def _select_combo_text(self, combo: QComboBox, text: str) -> None:
        idx = combo.findText(text)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        elif combo.count() > 0:
            combo.setCurrentIndex(0)

    def _update_status(self) -> None:
        provider = self._provider_combo.currentText()
        model = self._model_combo.currentText()
        device = self._device_combo.currentText()
        language = self._language_combo.currentText()
        tts_provider = self._tts_provider_combo.currentText()
        self._status_label.setText(
            f"Provider: {provider} | Model: {model} | Device: {device} | "
            f"Language: {language} | TTS: {tts_provider}"
        )

    # ------------------------------------------------------------------ #
    # Change handlers — persist + publish CONFIG_CHANGED immediately
    # ------------------------------------------------------------------ #
    def _on_provider_changed(self, value: str) -> None:
        self._config.set("voice.stt.provider", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.provider", "value": value}
            )

    def _on_model_changed(self, value: str) -> None:
        self._config.set("voice.stt.model", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.model", "value": value}
            )

    def _on_device_changed(self, value: str) -> None:
        self._config.set("voice.stt.device", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.stt.device", "value": value}
            )

    def _on_language_changed(self, value: str) -> None:
        lang = self._LANG_VALUES.get(value, "auto")
        self._config.set("voice.language", lang)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.language", "value": lang}
            )

    def _on_voice_enabled_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked
        self._config.set("voice.enabled", enabled)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.enabled", "value": enabled}
            )

    def _on_tts_provider_changed(self, value: str) -> None:
        self._config.set("voice.tts.provider", value)
        self._populate_tts_voices()
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.provider", "value": value}
            )

    def _on_tts_voice_changed(self, value: str) -> None:
        voice_id = self._tts_voice_combo.itemData(self._tts_voice_combo.currentIndex()) or ""
        self._config.set("voice.tts.voice", voice_id)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.voice", "value": voice_id}
            )

    def _on_tts_rate_changed(self, value: int) -> None:
        self._tts_rate_value.setText(str(value))
        self._config.set("voice.tts.rate", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.rate", "value": value}
            )

    def _on_tts_volume_changed(self, value: int) -> None:
        self._tts_volume_value.setText(f"{value}%")
        self._config.set("voice.tts.volume", value / 100.0)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.tts.volume", "value": value / 100.0}
            )


class GenerationSettingsTab(QWidget):
    """Tab for LLM generation parameter configuration.

    Exposes six controls: max_tokens, temperature, top_p, top_k, min_p,
    repeat_penalty.  Changes are persisted immediately through ConfigManager
    and a CONFIG_CHANGED event is published for each changed key.

    The verifier's own generation settings (max_tokens=256, temperature=0.1)
    are intentionally NOT exposed — they are managed internally by AgentVerifier.
    """

    _GEN_KEYS: ClassVar[dict[str, str]] = {
        "max_tokens": "ai.max_tokens",
        "temperature": "ai.temperature",
        "top_p": "ai.top_p",
        "top_k": "ai.top_k",
        "min_p": "ai.min_p",
        "repeat_penalty": "ai.repeat_penalty",
    }

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        gen_group = QGroupBox("Generation Parameters")
        layout = QFormLayout(gen_group)

        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(1, 4096)
        self._max_tokens_spin.setSingleStep(1)
        layout.addRow(QLabel("Max Tokens"), self._max_tokens_spin)

        self._temperature_spin = QDoubleSpinBox()
        self._temperature_spin.setRange(0.0, 2.0)
        self._temperature_spin.setSingleStep(0.1)
        self._temperature_spin.setDecimals(2)
        layout.addRow(QLabel("Temperature"), self._temperature_spin)

        self._top_p_spin = QDoubleSpinBox()
        self._top_p_spin.setRange(0.01, 1.0)
        self._top_p_spin.setSingleStep(0.05)
        self._top_p_spin.setDecimals(2)
        layout.addRow(QLabel("Top P"), self._top_p_spin)

        self._top_k_spin = QSpinBox()
        self._top_k_spin.setRange(0, 200)
        self._top_k_spin.setSingleStep(1)
        layout.addRow(QLabel("Top K"), self._top_k_spin)

        self._min_p_spin = QDoubleSpinBox()
        self._min_p_spin.setRange(0.0, 1.0)
        self._min_p_spin.setSingleStep(0.01)
        self._min_p_spin.setDecimals(2)
        layout.addRow(QLabel("Min P"), self._min_p_spin)

        self._repeat_penalty_spin = QDoubleSpinBox()
        self._repeat_penalty_spin.setRange(1.0, 2.0)
        self._repeat_penalty_spin.setSingleStep(0.05)
        self._repeat_penalty_spin.setDecimals(2)
        layout.addRow(QLabel("Repeat Penalty"), self._repeat_penalty_spin)

        main_layout.addWidget(gen_group)

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset_clicked)
        main_layout.addWidget(btn_reset)

        self._warning_label = QLabel("")
        self._warning_label.setStyleSheet("color: #d35400; font-size: 11px;")
        main_layout.addWidget(self._warning_label)

        main_layout.addStretch()

        self._max_tokens_spin.valueChanged.connect(self._on_max_tokens_changed)
        self._temperature_spin.valueChanged.connect(self._on_temperature_changed)
        self._top_p_spin.valueChanged.connect(self._on_top_p_changed)
        self._top_k_spin.valueChanged.connect(self._on_top_k_changed)
        self._min_p_spin.valueChanged.connect(self._on_min_p_changed)
        self._repeat_penalty_spin.valueChanged.connect(self._on_repeat_penalty_changed)

    def load_settings(self, config: ConfigManager) -> None:
        n_ctx = config.get("ai.n_ctx", 4096)
        max_tokens = config.get("ai.max_tokens", 512)

        self._max_tokens_spin.blockSignals(True)
        self._max_tokens_spin.setRange(1, n_ctx)
        self._max_tokens_spin.setValue(min(max_tokens, n_ctx - 1) if n_ctx > 1 else max_tokens)
        self._max_tokens_spin.blockSignals(False)

        self._temperature_spin.blockSignals(True)
        self._temperature_spin.setValue(config.get("ai.temperature", 0.7))
        self._temperature_spin.blockSignals(False)

        self._top_p_spin.blockSignals(True)
        self._top_p_spin.setValue(config.get("ai.top_p", 0.9))
        self._top_p_spin.blockSignals(False)

        self._top_k_spin.blockSignals(True)
        self._top_k_spin.setValue(config.get("ai.top_k", 40))
        self._top_k_spin.blockSignals(False)

        self._min_p_spin.blockSignals(True)
        self._min_p_spin.setValue(config.get("ai.min_p", 0.05))
        self._min_p_spin.blockSignals(False)

        self._repeat_penalty_spin.blockSignals(True)
        self._repeat_penalty_spin.setValue(config.get("ai.repeat_penalty", 1.1))
        self._repeat_penalty_spin.blockSignals(False)

        self._update_warning()

    def save_settings(self, config: ConfigManager) -> None:
        config.set("ai.max_tokens", self._max_tokens_spin.value())
        config.set("ai.temperature", self._temperature_spin.value())
        config.set("ai.top_p", self._top_p_spin.value())
        config.set("ai.top_k", self._top_k_spin.value())
        config.set("ai.min_p", self._min_p_spin.value())
        config.set("ai.repeat_penalty", self._repeat_penalty_spin.value())

    def _update_warning(self) -> None:
        n_ctx = self._config.get("ai.n_ctx", 4096)
        max_tokens = self._max_tokens_spin.value()
        if max_tokens >= n_ctx:
            self._warning_label.setText(
                f"Warning: max_tokens ({max_tokens}) >= n_ctx ({n_ctx}). "
                f"Clamped to n_ctx-1 at runtime."
            )
        else:
            self._warning_label.setText("")

    def _on_max_tokens_changed(self, value: int) -> None:
        self._config.set("ai.max_tokens", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.max_tokens", "value": value}
            )
        self._update_warning()

    def _on_temperature_changed(self, value: float) -> None:
        self._config.set("ai.temperature", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.temperature", "value": value}
            )

    def _on_top_p_changed(self, value: float) -> None:
        self._config.set("ai.top_p", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.top_p", "value": value}
            )

    def _on_top_k_changed(self, value: int) -> None:
        self._config.set("ai.top_k", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.top_k", "value": value}
            )

    def _on_min_p_changed(self, value: float) -> None:
        self._config.set("ai.min_p", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.min_p", "value": value}
            )

    def _on_repeat_penalty_changed(self, value: float) -> None:
        self._config.set("ai.repeat_penalty", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "ai.repeat_penalty", "value": value}
            )

    def _on_reset_clicked(self) -> None:
        defaults = {
            "ai.max_tokens": 512,
            "ai.temperature": 0.7,
            "ai.top_p": 0.9,
            "ai.top_k": 40,
            "ai.min_p": 0.05,
            "ai.repeat_penalty": 1.1,
        }
        for key, val in defaults.items():
            self._config.set(key, val)
            if self._event_bus is not None:
                self._event_bus.publish("CONFIG_CHANGED", {"key": key, "value": val})
        self.load_settings(self._config)


class MemorySettingsTab(QWidget):
    """Tab for Memory subsystem configuration.

    Exposes four controls:
    - Enable Memory (QCheckBox) → memory.enabled
    - Short-Term Window (QSpinBox) → memory.short_term_window
    - Max Context Memories (QSpinBox) → memory.max_context_memories
    - Embedding Backend (QComboBox) → memory.embedding_model

    Changes are persisted immediately through ConfigManager and a CONFIG_CHANGED
    event is published for each changed key.

    The embedding backend controls how MemoryManager selects its EmbeddingModel
    at startup.  Changing it at runtime does NOT reload the embedding model —
    a restart is required.
    """

    _EMBEDDING_BACKENDS: ClassVar[list[str]] = ["stub", "sentence-transformers", "mxbai-gguf"]

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        assistant: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._assistant = assistant
        self._setup_ui()

    def update_runtime_status(
        self,
        is_real_model_available: bool = True,
        fallback_reason: str | None = None,
    ) -> None:
        """Update the status label based on actual runtime state.

        This method allows the application to inform users when the selected
        embedding backend is NOT available at runtime, causing semantic retrieval
        to be disabled (keyword-only mode).

        Args:
            is_real_model_available: True if semantic retrieval is active
            fallback_reason: Optional reason for fallback (e.g., "model file not found")
        """
        if is_real_model_available:
            self._status_label.setText(
                "Semantic retrieval active"
            )
            self._status_label.setStyleSheet("color: #228B22; font-size: 11px;")
        else:
            reason_text = f" — {fallback_reason}" if fallback_reason else ""
            self._status_label.setText(
                f"Keyword-only mode{reason_text}"
            )
            self._status_label.setStyleSheet("color: #8C9692; font-size: 11px; font-style: italic;")

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        mem_group = QGroupBox("Memory Settings")
        layout = QFormLayout(mem_group)

        self._enable_checkbox = QCheckBox("Enable Memory")
        self._enable_checkbox.setToolTip(
            "Enable or disable long-term memory. Existing memories are preserved when disabled."
        )
        layout.addRow(self._enable_checkbox)

        self._window_spin = QSpinBox()
        self._window_spin.setRange(2, 50)
        self._window_spin.setSingleStep(1)
        layout.addRow(QLabel("Short-Term Window"), self._window_spin)

        self._max_memories_spin = QSpinBox()
        self._max_memories_spin.setRange(1, 20)
        self._max_memories_spin.setSingleStep(1)
        layout.addRow(QLabel("Max Context Memories"), self._max_memories_spin)

        self._embedding_combo = QComboBox()
        self._embedding_combo.addItems(self._EMBEDDING_BACKENDS)
        self._embedding_combo.setToolTip(
            "Embedding backend for semantic memory search. 'stub' is the default; "
            "'sentence-transformers' and 'mxbai-gguf' require optional dependencies. "
            "Changing this requires an application restart."
        )
        layout.addRow(QLabel("Embedding Backend"), self._embedding_combo)

        main_layout.addWidget(mem_group)

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._on_reset_clicked)
        main_layout.addWidget(btn_reset)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8C9692; font-size: 11px;")
        main_layout.addWidget(self._status_label)

        main_layout.addStretch()

        self._enable_checkbox.toggled.connect(self._on_enable_toggled)
        self._window_spin.valueChanged.connect(self._on_window_changed)
        self._max_memories_spin.valueChanged.connect(self._on_max_memories_changed)
        self._embedding_combo.currentTextChanged.connect(self._on_embedding_changed)

    def load_settings(self, config: ConfigManager) -> None:
        self._enable_checkbox.blockSignals(True)
        self._enable_checkbox.setChecked(bool(config.get("memory.enabled", True)))
        self._enable_checkbox.blockSignals(False)

        self._window_spin.blockSignals(True)
        self._window_spin.setValue(config.get("memory.short_term_window", 10))
        self._window_spin.blockSignals(False)

        self._max_memories_spin.blockSignals(True)
        self._max_memories_spin.setValue(config.get("memory.max_context_memories", 5))
        self._max_memories_spin.blockSignals(False)

        self._embedding_combo.blockSignals(True)
        backend = config.get("memory.embedding_model", "stub")
        idx = self._embedding_combo.findText(backend)
        if idx >= 0:
            self._embedding_combo.setCurrentIndex(idx)
        else:
            self._embedding_combo.setCurrentIndex(0)
        self._embedding_combo.blockSignals(False)

        self._update_status()
        self._refresh_runtime_status()

    def _refresh_runtime_status(self) -> None:
        """Check actual embedding model availability and update UI status.

        This method queries the MemoryManager to see if semantic retrieval
        is actually working, and updates the status label accordingly.
        """
        if self._assistant is None or self._assistant.memory is None:
            return

        memory = self._assistant.memory
        try:
            info = memory.get_embedding_model_info()
            if info["is_stub"]:
                intended = info.get("intended_name")
                if intended and intended != "stub":
                    self.update_runtime_status(
                        is_real_model_available=False,
                        fallback_reason=f"{intended} unavailable"
                    )
                else:
                    self.update_runtime_status(
                        is_real_model_available=False,
                        fallback_reason=None
                    )
            else:
                self.update_runtime_status(
                    is_real_model_available=True,
                    fallback_reason=None
                )
        except Exception as exc:
            logger.debug("Failed to refresh runtime status: %s", exc)

    def save_settings(self, config: ConfigManager) -> None:
        config.set("memory.enabled", self._enable_checkbox.isChecked())
        config.set("memory.short_term_window", self._window_spin.value())
        config.set("memory.max_context_memories", self._max_memories_spin.value())
        config.set("memory.embedding_model", self._embedding_combo.currentText())

    def _update_status(self) -> None:
        backend = self._embedding_combo.currentText()
        if backend == "stub":
            self._status_label.setText(
                "Stub backend (keyword-only retrieval, semantic search disabled)"
            )
            self._status_label.setStyleSheet("color: #8C9692; font-size: 11px; font-style: italic;")
        else:
            self._status_label.setText(
                f"Configured: {backend} — restart required for changes to take effect"
            )
            self._status_label.setStyleSheet("color: #666666; font-size: 11px;")

    def _on_enable_toggled(self, checked: bool) -> None:
        self._config.set("memory.enabled", checked)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "memory.enabled", "value": checked}
            )

    def _on_window_changed(self, value: int) -> None:
        self._config.set("memory.short_term_window", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "memory.short_term_window", "value": value}
            )

    def _on_max_memories_changed(self, value: int) -> None:
        self._config.set("memory.max_context_memories", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "memory.max_context_memories", "value": value}
            )

    def _on_embedding_changed(self, value: str) -> None:
        self._config.set("memory.embedding_model", value)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "memory.embedding_model", "value": value}
            )

    def _on_reset_clicked(self) -> None:
        defaults = {
            "memory.enabled": True,
            "memory.short_term_window": 10,
            "memory.max_context_memories": 5,
            "memory.embedding_model": "stub",
        }
        for key, val in defaults.items():
            self._config.set(key, val)
            if self._event_bus is not None:
                self._event_bus.publish("CONFIG_CHANGED", {"key": key, "value": val})
        self.load_settings(self._config)


class SettingsDialog(QDialog):
    """Modal settings window with model, theme, and profile tabs."""

    profile_updated = Signal(dict)

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        assistant: Assistant | None = None,
        plugin_manager: PluginManager | None = None,
        model_manager: Any | None = None,
        parent: QWidget | None = None,
        voice_manager: Any | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Postavke")
        self.resize(560, 520)
        self._config = config
        self._event_bus = event_bus
        self._assistant = assistant
        self._plugin_manager = plugin_manager
        self._model_manager = model_manager
        self._voice_manager = voice_manager
        self._scan_thread = None

        main_layout = QVBoxLayout(self)

        self._tab_widget = QTabWidget()
        self._tab_widget.setAccessibleName("Settings categories")
        self._setup_tabs()
        main_layout.addWidget(self._tab_widget)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_save = QPushButton("Save")
        self._btn_save.setAccessibleName("Save settings")
        self._btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self._btn_save)
        self._btn_close = QPushButton("Zatvori")
        self._btn_close.setAccessibleName("Close settings")
        self._btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self._btn_close)
        main_layout.addLayout(btn_layout)

        self._load_current_settings()

    def _setup_tabs(self) -> None:
        self._general_tab = self._create_general_tab()
        self._tab_widget.addTab(self._general_tab, "General")
        self._language_tab = self._create_language_tab()
        self._tab_widget.addTab(self._language_tab, "Language")
        self._model_tab = self._create_model_tab()
        self._tab_widget.addTab(self._model_tab, "Model")
        self._storage_tab = self._create_storage_tab()
        self._tab_widget.addTab(self._storage_tab, "Storage")
        self._filesystem_tab = self._create_filesystem_tab()
        self._tab_widget.addTab(self._filesystem_tab, "Filesystem Security")
        self._logging_tab = self._create_logging_tab()
        self._tab_widget.addTab(self._logging_tab, "Logging")
        self._plugin_tab = self._create_plugin_tab()
        self._tab_widget.addTab(self._plugin_tab, "Plugins")
        self._audio_tab = self._create_audio_tab()
        self._tab_widget.addTab(self._audio_tab, "Audio")
        self._voice_tab = self._create_voice_tab()
        self._tab_widget.addTab(self._voice_tab, "Voice")
        self._generation_tab = self._create_generation_tab()
        self._tab_widget.addTab(self._generation_tab, "Generation")
        self._memory_tab = self._create_memory_tab()
        self._tab_widget.addTab(self._memory_tab, "Memory")
        self._profile_tab = self._create_profile_tab()
        self._tab_widget.addTab(self._profile_tab, "Profile")

    def _create_voice_tab(self) -> VoiceSettingsTab:
        return VoiceSettingsTab(
            config=self._config,
            event_bus=self._event_bus,
            voice_manager=self._voice_manager,
        )

    def _create_generation_tab(self) -> GenerationSettingsTab:
        return GenerationSettingsTab(
            config=self._config,
            event_bus=self._event_bus,
        )

    def _create_memory_tab(self) -> MemorySettingsTab:
        return MemorySettingsTab(
            config=self._config,
            event_bus=self._event_bus,
            assistant=self._assistant,
        )

    def _create_general_tab(self) -> QWidget:
        tab = QWidget()
        layout = QFormLayout(tab)

        layout.addWidget(QLabel("<b>Theme</b>"))
        self._theme_combo = QComboBox()
        self._theme_combo.addItems(["grey_emerald", "installer"])
        self._theme_combo.setCurrentText(self._config.get("ui.theme", "grey_emerald"))
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addRow(self._theme_combo)

        return tab

    def _create_language_tab(self) -> LanguageTab:
        return LanguageTab()

    def _create_model_tab(self) -> ModelStatusTab:
        return ModelStatusTab(
            model_manager=self._model_manager,
            event_bus=self._event_bus,
            config=self._config,
        )

    def _create_storage_tab(self) -> StorageTab:
        return StorageTab()

    def _create_filesystem_tab(self) -> FilesystemSecurityTab:
        return FilesystemSecurityTab(event_bus=self._event_bus)

    def _create_logging_tab(self) -> LoggingTab:
        return LoggingTab(event_bus=self._event_bus)

    def _create_plugin_tab(self) -> PluginTab:
        return PluginTab(plugin_manager=self._plugin_manager)

    def _create_audio_tab(self) -> AudioSettingsTab:
        return AudioSettingsTab(
            config=self._config,
            event_bus=self._event_bus,
            voice_manager=self._voice_manager,
        )

    def _create_profile_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self._tab_widget_inner = QTabWidget()

        self._identity_tab = ProfileTab()
        self._communication_tab = CommunicationTab()
        self._personality_tab = PersonalityTab()
        self._expertise_tab = ExpertiseTab()
        self._behavior_tab = BehaviorTab()
        self._boundaries_tab = BoundariesTab()

        self._tab_widget_inner.addTab(self._identity_tab, "Identity")
        self._tab_widget_inner.addTab(self._communication_tab, "Communication")
        self._tab_widget_inner.addTab(self._personality_tab, "Personality")
        self._tab_widget_inner.addTab(self._expertise_tab, "Expertise")
        self._tab_widget_inner.addTab(self._behavior_tab, "Behavior")
        self._tab_widget_inner.addTab(self._boundaries_tab, "Boundaries")

        layout.addWidget(self._tab_widget_inner)
        return tab

    def _load_current_settings(self) -> None:
        if self._language_tab is not None:
            self._language_tab.load_settings(self._config)
        if self._model_tab is not None:
            self._model_tab.load_settings(self._config)
        if self._storage_tab is not None:
            self._storage_tab.load_settings(self._config)
        if self._filesystem_tab is not None:
            self._filesystem_tab.load_settings(self._config)
        if self._logging_tab is not None:
            self._logging_tab.load_settings(self._config)
        if self._audio_tab is not None:
            self._audio_tab.load_settings(self._config)
        if self._voice_tab is not None:
            self._voice_tab.load_settings(self._config)
        if self._generation_tab is not None:
            self._generation_tab.load_settings(self._config)
        if self._memory_tab is not None:
            self._memory_tab.load_settings(self._config)

        if self._assistant is not None:
            profile = self._assistant.get_assistant_profile()
            self._identity_tab.load_profile(profile)
            self._communication_tab.load_profile(profile)
            self._personality_tab.load_profile(profile)
            self._expertise_tab.load_profile(profile)
            self._behavior_tab.load_profile(profile)
            self._boundaries_tab.load_profile(profile)

    def _on_theme_changed(self, value: str) -> None:
        self._config.set("ui.theme", value)
        self._event_bus.publish("CONFIG_CHANGED", data={"key": "ui.theme", "value": value})

    def _on_save(self) -> None:
        try:
            profile_updates: dict[str, Any] = {}

            if self._assistant is not None:
                profile_updates["identity"] = self._identity_tab.get_identity()
                profile_updates["communication"] = self._communication_tab.get_communication()
                profile_updates["personality"] = self._personality_tab.get_personality()
                profile_updates["expertise"] = self._expertise_tab.get_expertise()
                profile_updates["behavior"] = self._behavior_tab.get_behavior()
                profile_updates["boundaries"] = self._boundaries_tab.get_boundaries()
                self._assistant.update_assistant_profile(profile_updates)

            if self._config is not None and self._filesystem_tab is not None:
                self._filesystem_tab.save_settings(self._config)
                from tools.file_security import configure_default_validator_from_config
                configure_default_validator_from_config(self._config)

            if self._config is not None and self._audio_tab is not None:
                self._audio_tab.save_settings(self._config)

            if self._config is not None and self._voice_tab is not None:
                self._voice_tab.save_settings(self._config)

            if self._config is not None and self._generation_tab is not None:
                self._generation_tab.save_settings(self._config)

            if self._config is not None and self._memory_tab is not None:
                self._memory_tab.save_settings(self._config)

            if self._config is not None and self._logging_tab is not None:
                self._logging_tab.save_settings(self._config)

            if self._config is not None and self._language_tab is not None:
                lang_code = self._language_tab.get_language()
                self._config.set("app.language", lang_code)
                try:
                    from ui.translations import Language, TranslationManager
                    language = Language.from_string(lang_code)
                    TranslationManager.set_language(language)
                except Exception:
                    logger.debug("Language switch failed", exc_info=True)

            self.profile_updated.emit(profile_updates)
            # PROFILE_UPDATED is already published inside update_assistant_profile()
            # (core/assistant.py:959) to avoid duplicate event delivery.
            self.accept()
        except Exception as exc:
            QMessageBox.critical(
                self, "Save Error",
                f"Failed to save settings:\n{exc}\n\n"
                "Your changes may not have been persisted.",
            )
            logger.exception("Settings save failed")