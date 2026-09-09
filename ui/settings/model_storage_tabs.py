"""Model and storage settings tabs."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from core.config_manager import ConfigManager
from core.paths import CONFIG_DIR, DATA_DIR, LLM_DIR, LOGS_DIR


class ModelStatusTab(QWidget):
    """Tab showing model status information with management button."""

    def __init__(
        self,
        model_manager: Any | None = None,
        event_bus: Any | None = None,
        config: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
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

            # PHASE 8: the user picks the models ROOT; the manager scans
            # the llm CATEGORY dir under it — the exact derivation that
            # set_models_root() persists, so in-session behavior and the
            # post-restart resolution agree (Phase 3 contract).
            scan_dir = Path(directory) / "llm"

            class ScanThread(QThread):
                finished = Signal()

                def __init__(self, manager, directory):
                    super().__init__()
                    self._manager = manager
                    self._directory = Path(directory)

                def run(self) -> None:
                    self._manager.set_models_dir(self._directory)

            thread = ScanThread(self._model_manager, scan_dir)
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
            # PHASE 3: persist through the canonical models-root contract so
            # wizard, settings, and runtime share one source of truth.  The
            # directory the user picked becomes the models ROOT; category
            # dirs (llm, embedding, stt) derive under it.  Legacy
            # ai.models_dir / search paths are mirrored by set_models_root.
            try:
                from core.paths import set_models_root

                set_models_root(directory, config=self._config)
            except (ValueError, OSError):
                # Fall back to the legacy key when the value is unusable.
                self._config.set("ai.models_dir", directory)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                data={"key": "models.storage_root", "value": directory},
            )
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