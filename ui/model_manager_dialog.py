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

from ai.hardware import HardwareSnapshot, detect_hardware_snapshot
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
        self._downloader = None

    def run(self) -> None:
        try:
            self.progress.emit(0, "Starting download...")

            def _factory(**kwargs):
                # Capture the downloader ModelManager creates so cancel()
                # reaches the ACTIVE operation (live forwarder, not a
                # start-time flag snapshot).
                from installer.downloader import ModelDownloader

                downloader = ModelDownloader(**kwargs)
                self._downloader = downloader
                return downloader

            model = self._manager.download_model(
                self._url,
                self._filename,
                self._expected_checksum,
                downloader_factory=_factory,
            )
            self.progress.emit(100, "Download complete")
            self.finished.emit(True, str(model.path), "")
        except Exception as exc:
            logger.error("Download failed: %s", exc)
            self.finished.emit(False, "", str(exc))
        finally:
            # No stale downloader reference beyond the operation.
            self._downloader = None

    def cancel(self) -> None:
        """Request clean cancellation of the active download (if any)."""
        if self._downloader is not None:
            self._downloader.cancel()


class CatalogDownloadWorker(QThread):
    """PHASE 7 background worker: curated catalog entry download.

    Runs :func:`ai.models.download_service.download_entry` OFF the GUI
    thread and reports chunk-level progress through Qt signals; the
    download itself streams to disk and never touches the UI thread.
    """

    progress = Signal(int, int, str)   # bytes_downloaded, total_bytes (0=unknown), filename
    finished = Signal(bool, str, str)  # success, path, error

    def __init__(self, entry, models_root=None) -> None:
        super().__init__()
        self._entry = entry
        self._models_root = models_root
        self._downloader = None

    def run(self) -> None:
        from ai.models.download_service import download_entry
        from installer.downloader import DownloadProgress, SecureModelDownloader

        def _on_progress(p: DownloadProgress) -> None:
            self.progress.emit(
                p.bytes_downloaded, p.total_bytes or 0, self._entry.filename
            )

        try:
            self.progress.emit(0, 0, self._entry.filename)

            def _factory(**kwargs):
                # The service hands us its canonical constructor kwargs
                # (category/install_dir/progress_callback/validator); we
                # build the REAL downloader here so the worker holds a
                # live reference and cancel() reaches the active
                # operation — primary AND companion downloads.
                downloader = SecureModelDownloader(**kwargs)
                self._downloader = downloader
                return downloader

            primary, _companions = download_entry(
                self._entry,
                progress_callback=_on_progress,
                downloader_factory=_factory,
            )
            if primary.success:
                self.progress.emit(
                    primary.size_bytes, primary.size_bytes, self._entry.filename
                )
                self.finished.emit(True, str(primary.dest), "")
            else:
                self.finished.emit(False, "", primary.error or "Download failed")
        except Exception as exc:
            logger.error("Catalog download failed: %s", exc)
            self.finished.emit(False, "", str(exc))
        finally:
            # Drop the reference when the operation ends so a later
            # cancel() can never affect a future operation.
            self._downloader = None

    def cancel(self) -> None:
        """Request clean cancellation (stops at the next chunk boundary)."""
        if self._downloader is not None:
            self._downloader.cancel()


class ModelManagerDialog(QDialog):
    """Modal dialog for managing local AI models."""

    def __init__(self, model_manager: ModelManager, event_bus: EventBus, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = model_manager
        self._event_bus = event_bus
        self._selected_model: ModelInfo | None = None
        self._download_worker: DownloadWorker | None = None
        self._catalog_worker: CatalogDownloadWorker | None = None
        self._load_worker: ModelLoadWorker | None = None
        self._is_loading = False
        self._hardware: HardwareSnapshot | None = None
        self._last_downloaded_entry = None  # PHASE 9: STT selection wiring

        self.setWindowTitle("Model Manager")
        self.resize(760, 620)

        self._build_ui()
        self._refresh_model_list()
        self._update_recommendation()
        self._refresh_catalog()

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

        # PHASE 7: curated downloadable catalog with advisory verdicts.
        catalog_group = QGroupBox("Downloadable Models")
        catalog_layout = QVBoxLayout(catalog_group)
        self._catalog_list = QListWidget()
        self._catalog_list.itemSelectionChanged.connect(self._on_catalog_selected)
        catalog_layout.addWidget(self._catalog_list)

        self._catalog_details = QLabel("")
        self._catalog_details.setWordWrap(True)
        catalog_layout.addWidget(self._catalog_details)

        catalog_btn_layout = QHBoxLayout()
        self._btn_catalog_download = QPushButton("Download Selected Model")
        self._btn_catalog_download.clicked.connect(self._on_catalog_download)
        self._btn_catalog_download.setEnabled(False)
        catalog_btn_layout.addWidget(self._btn_catalog_download)
        self._btn_catalog_cancel = QPushButton("Cancel Download")
        self._btn_catalog_cancel.clicked.connect(self._on_catalog_cancel)
        self._btn_catalog_cancel.setEnabled(False)
        catalog_btn_layout.addWidget(self._btn_catalog_cancel)
        catalog_btn_layout.addStretch()
        self._catalog_progress = QProgressBar()
        self._catalog_progress.setVisible(False)
        catalog_btn_layout.addWidget(self._catalog_progress)
        catalog_layout.addLayout(catalog_btn_layout)
        layout.addWidget(catalog_group)

        # Model list
        self._model_list = QListWidget()
        self._model_list.itemSelectionChanged.connect(self._on_model_selected)
        layout.addWidget(QLabel("<b>Installed Models</b>"))
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
            self._hardware = detect_hardware_snapshot()
            hw_lines = "<br>".join(self._hardware.to_summary_lines())
            self._rec_label.setText(
                f"<b>{rec.label}</b> — {rec.reason}<br>{hw_lines}"
            )
        except Exception as exc:
            logger.debug("Hardware detection failed: %s", exc)
            self._rec_label.setText("Hardware detection unavailable")

    # ------------------------------------------------------------------ #
    # PHASE 7: curated catalog
    # ------------------------------------------------------------------ #

    def _refresh_catalog(self) -> None:
        """Evaluate the curated catalog against detected hardware."""
        from ai.models.download_service import catalog_status
        from core.paths import get_models_root

        self._catalog_list.clear()
        try:
            gpu_mode = "auto"
            if self._hardware is None:
                self._hardware = detect_hardware_snapshot()
            statuses = catalog_status(self._hardware, gpu_mode=gpu_mode,
                                      models_root=get_models_root())
        except Exception as exc:
            logger.debug("Catalog evaluation failed: %s", exc)
            self._catalog_list.addItem("Catalog unavailable")
            return
        from ai.models.recommendation import ModelVerdict

        verdict_labels = {
            ModelVerdict.RECOMMENDED: "Recommended",
            ModelVerdict.POSSIBLE: "Possible (partial GPU)",
            ModelVerdict.CPU_RECOMMENDED: "CPU only",
            ModelVerdict.INSUFFICIENT_RESOURCES: "Too large for this machine",
            ModelVerdict.INSUFFICIENT_DISK: "Not enough disk space",
            ModelVerdict.UNKNOWN: "Cannot determine",
        }
        for status in statuses:
            entry = status.entry
            size_gb = entry.total_download_bytes / (1024**3)
            label = f"{entry.display_name} — ~{size_gb:.1f} GB"
            if status.installed:
                label = f"[installed] {label}"
            label = f"{label} · {verdict_labels[status.recommendation.verdict]}"
            item = QListWidgetItem(label)
            item.setData(1000, status)
            self._catalog_list.addItem(item)

    def _on_catalog_selected(self) -> None:
        item = self._catalog_list.currentItem()
        if item is None:
            self._btn_catalog_download.setEnabled(False)
            return
        status = item.data(1000)
        if not hasattr(status, "entry"):
            self._btn_catalog_download.setEnabled(False)
            return
        entry = status.entry
        rec = status.recommendation
        lines = [
            f"<b>{entry.display_name}</b>",
            entry.description or "",
            f"Category: {entry.category}",
            f"Download size: ~{entry.total_download_bytes / (1024**3):.1f} GB",
            f"Assessment: {rec.reason}",
        ]
        if entry.compatibility_notes:
            lines.append(f"Note: {entry.compatibility_notes}")
        if self._hardware is not None and self._hardware.disk_free_known:
            lines.append(
                f"Free space on models drive: "
                f"{self._hardware.disk_free_bytes / (1024**3):.0f} GB"
            )
        self._catalog_details.setText("<br>".join(lines))
        # Downloads are allowed for runnable verdicts; the user may
        # still choose a non-recommended entry explicitly (advisory,
        # not enforced), except clearly insufficient disk/resources.
        # PHASE 9: entries without verified integrity metadata (exact
        # size + SHA-256) are never downloadable — the download service
        # rejects them; reflect that in the button state and details.
        from ai.models.recommendation import ModelVerdict

        self._btn_catalog_download.setEnabled(
            rec.verdict
            not in (ModelVerdict.INSUFFICIENT_DISK, ModelVerdict.INSUFFICIENT_RESOURCES)
            and getattr(entry, "is_fully_curated", False)
        )
        if not getattr(entry, "is_fully_curated", False):
            self._catalog_details.setText(
                self._catalog_details.text()
                + "<br>Note: integrity metadata not yet verified for this "
                "entry — download disabled until the catalog entry is "
                "fully curated (see installer/catalog.py)."
            )

    def _on_catalog_download(self) -> None:
        item = self._catalog_list.currentItem()
        if item is None or self._catalog_worker is not None:
            return
        status = item.data(1000)
        if not hasattr(status, "entry"):
            return
        if status.installed:
            QMessageBox.information(
                self, "Already Installed",
                "This model is already present in your models folder.",
            )
            return
        entry = status.entry
        self._last_downloaded_entry = entry
        self._btn_catalog_download.setEnabled(False)
        self._btn_catalog_cancel.setEnabled(True)
        self._catalog_progress.setVisible(True)
        self._catalog_progress.setRange(0, 0)  # indeterminate until size known
        self._catalog_worker = CatalogDownloadWorker(entry)
        self._catalog_worker.progress.connect(self._on_catalog_progress)
        self._catalog_worker.finished.connect(self._on_catalog_finished)
        self._catalog_worker.start()

    def _on_catalog_cancel(self) -> None:
        if self._catalog_worker is not None:
            self._catalog_worker.cancel()
            self._catalog_worker.wait(3000)

    def _on_catalog_progress(self, downloaded: int, total: int, filename: str) -> None:
        if total > 0:
            self._catalog_progress.setRange(0, 100)
            self._catalog_progress.setValue(int(downloaded * 100 / total))
        gb = 1024**3
        total_txt = f"{total / gb:.1f} GB" if total else "unknown"
        self._catalog_progress.setFormat(f"{filename}: {downloaded / gb:.1f}/{total_txt} GB")

    def _on_catalog_finished(self, success: bool, path: str, error: str) -> None:
        self._catalog_worker = None
        self._btn_catalog_download.setEnabled(True)
        self._btn_catalog_cancel.setEnabled(False)
        self._catalog_progress.setVisible(False)
        if success:
            self._refresh_model_list()
            self._refresh_catalog()
            self._maybe_select_stt_model(path)
            QMessageBox.information(
                self, "Download Complete", f"Model saved to:\n{path}"
            )
        else:
            QMessageBox.critical(self, "Download Failed", f"Error: {error}")

    def _maybe_select_stt_model(self, installed_path: str) -> None:
        """Select a freshly installed STT catalog model (PHASE 9).

        faster-whisper models are named FOLDERS; after a successful STT
        catalog download the runtime model selection (``voice.stt.model``)
        is pointed at the installed folder through the existing
        configuration mechanism so the new model is immediately usable.
        The STT provider itself reconfigures lazily through the existing
        ``CONFIG_CHANGED`` → ``VoiceManager._reconfigure_stt`` flow — no
        default is changed, nothing is loaded eagerly, and the offline
        contract is untouched (this only runs after an explicit,
        successful user-initiated download).
        """
        entry = self._last_downloaded_entry
        if entry is None or entry.category != "stt":
            return
        runtime_name = entry.runtime_model_name
        if not runtime_name:
            return
        if not Path(installed_path).is_dir():
            return
        try:
            from core.config_manager import ConfigManager

            config = ConfigManager()
            config.set("voice.stt.model", runtime_name)
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    data={"key": "voice.stt.model", "value": runtime_name},
                )
            logger.info(
                "STT model selected after download: voice.stt.model=%s",
                runtime_name,
            )
        except (ValueError, OSError) as exc:
            logger.warning("Could not select downloaded STT model: %s", exc)

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
        # Both download workers shut down COOPERATIVELY (chunk-boundary
        # cancellation, bounded wait) — never terminate(): killing a
        # thread mid-write/mid-hash can corrupt state, and a cancelled
        # .part file stays resumable, a corrupted half-written file is not.
        if self._download_worker is not None and self._download_worker.isRunning():
            self._download_worker.cancel()
            self._download_worker.wait(5000)
        if self._catalog_worker is not None and self._catalog_worker.isRunning():
            # Clean cancellation (chunk boundary), never hard terminate
            # a model download — a .part file is resumable, a corrupted
            # half-renamed file is not.
            self._catalog_worker.cancel()
            self._catalog_worker.wait(5000)
        super().closeEvent(event)
