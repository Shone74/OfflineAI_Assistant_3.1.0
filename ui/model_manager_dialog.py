"""Model manager dialog — download, delete, and activate .gguf models."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.models.model_loader import ModelInfo
from ai.models.model_manager import ModelManager
from core.event_bus import EventBus
from core.logger import get_logger
from installer.hardware import detect_hardware, recommend_model
from ui.models_page import ModelLoadWorker

logger = get_logger("model_manager_dialog")


class DownloadWorker(QThread):
    """Background worker for model download with progress."""

    progress = Signal(int, str)
    finished = Signal(bool, str, str)

    def __init__(self, manager: ModelManager, url: str, filename: str, expected_checksum: str | None = None) -> None:
        super().__init__()
        self._manager = manager
        self._url = url
        self._filename = filename
        self._expected_checksum = expected_checksum

    def run(self) -> None:
        try:
            self.progress.emit(0, "Starting download...")
            model = self._manager.download_model(self._url, self._filename, self._expected_checksum)
            self.progress.emit(100, "Download complete")
            self.finished.emit(True, str(model.path), "")
        except Exception as exc:
            logger.error("Download failed: %s", exc)
            self.finished.emit(False, "", str(exc))


class ModelManagerDialog(QDialog):
    """Modal dialog for managing local AI models."""

    def __init__(self, model_manager: ModelManager, event_bus: EventBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = model_manager
        self._event_bus = event_bus
        self._selected_model: ModelInfo | None = None
        self._download_worker: DownloadWorker | None = None
        self._load_worker: ModelLoadWorker | None = None
        self._is_loading = False

        self.setWindowTitle("Model Manager")
        self.resize(700, 500)

        self._build_ui()
        self._refresh_model_list()
        self._update_recommendation()

    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Hardware recommendation
        self._rec_group = QGroupBox("Hardware Recommendation")
        rec_layout = QFormLayout(self._rec_group)
        self._rec_label = QLabel("Detecting...")
        self._rec_label.setWordWrap(True)
        rec_layout.addRow(self._rec_label)
        layout.addWidget(self._rec_group)

        # Model list
        self._model_list = QListWidget()
        self._model_list.itemSelectionChanged.connect(self._on_model_selected)
        layout.addWidget(QLabel("<b>Available Models</b>"))
        layout.addWidget(self._model_list)

        # Model details
        self._details_group = QGroupBox("Model Details")
        details_layout = QFormLayout(self._details_group)
        self._detail_name = QLabel("—")
        self._detail_size = QLabel("—")
        self._detail_caps = QLabel("—")
        details_layout.addRow("Name:", self._detail_name)
        details_layout.addRow("Size:", self._detail_size)
        details_layout.addRow("Capabilities:", self._detail_caps)
        layout.addWidget(self._details_group)

        # Download section
        download_group = QGroupBox("Download Model")
        download_layout = QFormLayout(download_group)
        self._download_url = QTextEdit()
        self._download_url.setPlaceholderText("https://example.com/model.gguf")
        self._download_url.setFixedHeight(40)
        self._download_url.setAccessibleName("Model download URL")
        download_layout.addRow("URL:", self._download_url)

        self._download_filename = QTextEdit()
        self._download_filename.setPlaceholderText("model.gguf")
        self._download_filename.setFixedHeight(40)
        self._download_filename.setAccessibleName("Model filename")
        download_layout.addRow("Filename:", self._download_filename)

        self._download_progress = QProgressBar()
        self._download_progress.setVisible(False)
        download_layout.addRow("Progress:", self._download_progress)

        self._download_status = QLabel("")
        download_layout.addRow("Status:", self._download_status)

        btn_layout = QHBoxLayout()
        self._btn_download = QPushButton("Download")
        self._btn_download.clicked.connect(self._on_download_clicked)
        self._btn_download.setAccessibleName("Download model")
        btn_layout.addWidget(self._btn_download)
        download_layout.addRow("", btn_layout)

        layout.addWidget(download_group)

        # Action buttons
        action_layout = QHBoxLayout()
        self._btn_activate = QPushButton("Activate")
        self._btn_activate.clicked.connect(self._on_activate_clicked)
        self._btn_activate.setEnabled(False)
        self._btn_activate.setAccessibleName("Activate selected model")
        action_layout.addWidget(self._btn_activate)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.clicked.connect(self._on_delete_clicked)
        self._btn_delete.setEnabled(False)
        self._btn_delete.setAccessibleName("Delete selected model")
        action_layout.addWidget(self._btn_delete)

        action_layout.addStretch()
        self._btn_close = QPushButton("Close")
        self._btn_close.clicked.connect(self.accept)
        action_layout.addWidget(self._btn_close)

        layout.addLayout(action_layout)

    # ------------------------------------------------------------------ #
    def _refresh_model_list(self) -> None:
        self._model_list.clear()
        models = self._manager.list_models()
        if not models:
            item = QListWidgetItem("No models found. Download one below.")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self._model_list.addItem(item)
            return

        for model in models:
            item = QListWidgetItem(f"{model.name} ({model.size_human})")
            item.setData(1000, model)
            if model.active:
                item.setText(f"✓ {model.name} ({model.size_human})")
            self._model_list.addItem(item)

    def _update_recommendation(self) -> None:
        try:
            profile = detect_hardware()
            rec = recommend_model(profile)
            self._rec_label.setText(
                f"<b>{rec.label}</b><br>{rec.reason}<br>"
                f"RAM: {profile.ram_total_gb:.0f} GB | "
                f"VRAM: {profile.gpu_vram_gb or 'N/A'} GB | "
                f"CPU: {profile.cpu_cores} cores"
            )
        except Exception as exc:
            logger.debug("Hardware detection failed: %s", exc)
            self._rec_label.setText("Hardware detection unavailable")

    def _on_model_selected(self) -> None:
        item = self._model_list.currentItem()
        if item is None:
            return
        model = item.data(1000)
        if not isinstance(model, ModelInfo):
            self._btn_activate.setEnabled(False)
            self._btn_delete.setEnabled(False)
            return

        self._selected_model = model
        self._btn_activate.setEnabled(True)
        self._btn_delete.setEnabled(not model.active)
        self._detail_name.setText(model.name)
        self._detail_size.setText(f"{model.size_mb:.0f} MB ({model.size_human})")
        caps = model.capabilities
        caps_list = [k for k, v in caps.to_dict().items() if v]
        self._detail_caps.setText(", ".join(caps_list) if caps_list else "Basic")

    def _on_activate_clicked(self) -> None:
        if self._selected_model is None:
            return
        if self._is_loading:
            return

        self._is_loading = True
        self._btn_activate.setEnabled(False)
        QApplication.processEvents()

        self._load_worker = ModelLoadWorker(self._manager, self._selected_model.name)
        self._load_worker.finished.connect(self._on_model_load_finished)
        self._load_worker.start()

    def _on_model_load_finished(self, model_name: str, error: str) -> None:
        self._is_loading = False
        self._btn_activate.setEnabled(True)
        self._load_worker = None

        if error:
            logger.error("Model activation failed: %s", error)
            QMessageBox.critical(self, "Error", f"Failed to activate model: {error}")
            return

        self._event_bus.publish("MODEL_LOADED", data={"model": model_name})
        QMessageBox.information(self, "Model Activated", f"Model '{model_name}' is now active.")
        self._refresh_model_list()

    def _on_delete_clicked(self) -> None:
        if self._selected_model is None or self._selected_model.active:
            return
        reply = QMessageBox.question(
            self,
            "Delete Model",
            f"Delete '{self._selected_model.name}' from disk?",
            QMessageBox.Yes | QMessageBox.No,  # type: ignore[attr-defined]
        )
        if reply == QMessageBox.Yes:  # type: ignore[attr-defined]
            if self._manager.delete_model(self._selected_model.name):
                self._selected_model = None
                self._refresh_model_list()
                self._detail_name.setText("—")
                self._detail_size.setText("—")
                self._detail_caps.setText("—")
                self._btn_activate.setEnabled(False)
                self._btn_delete.setEnabled(False)
            else:
                QMessageBox.critical(self, "Error", "Failed to delete model.")

    def _on_download_clicked(self) -> None:
        url = self._download_url.toPlainText().strip()
        filename = self._download_filename.toPlainText().strip()
        if not url or not filename:
            QMessageBox.warning(self, "Input Error", "Please enter both URL and filename.")
            return

        self._btn_download.setEnabled(False)
        self._download_progress.setVisible(True)
        self._download_progress.setRange(0, 0)
        self._download_status.setText("Downloading...")

        self._download_worker = DownloadWorker(self._manager, url, filename)
        self._download_worker.progress.connect(self._on_download_progress)
        self._download_worker.finished.connect(self._on_download_finished)
        self._download_worker.start()

    def _on_download_progress(self, value: int, status: str) -> None:
        self._download_status.setText(status)
        if value > 0:
            self._download_progress.setRange(0, 100)
            self._download_progress.setValue(value)

    def _on_download_finished(self, success: bool, path: str, error: str) -> None:
        self._btn_download.setEnabled(True)
        self._download_progress.setVisible(False)
        if success:
            self._download_status.setText(f"Downloaded: {Path(path).name}")
            self._refresh_model_list()
            QMessageBox.information(self, "Download Complete", f"Model saved to:\n{path}")
        else:
            self._download_status.setText(f"Failed: {error}")
            QMessageBox.critical(self, "Download Failed", f"Error: {error}")

    def closeEvent(self, event: Any) -> None:
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.terminate()
            self._download_worker.wait()
        super().closeEvent(event)
