"""Models page — browse, select, and manage local AI models."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.models.model_loader import ModelInfo, ModelStatus
from ai.models.model_manager import ModelManager
from core.logger import get_logger

logger = get_logger("ui.models_page")


class ModelLoadWorker(QThread):
    """Background worker for blocking GGUF model loading (Llama() constructor).

    Only the *activation* (which calls ``Llama()``) runs in the worker thread.
    Engine configuration and event publishing happen on the main thread after
    the worker finishes.
    """

    finished = Signal(str, str)

    def __init__(self, model_manager: ModelManager, model_name: str) -> None:
        super().__init__()
        self._model_manager = model_manager
        self._model_name = model_name

    def run(self) -> None:
        try:
            model = self._model_manager.activate_model(self._model_name)
            self.finished.emit(model.name, "")
        except Exception as exc:
            logger.error("Model load worker failed: %s", exc)
            self.finished.emit("", str(exc))


class ModelsPage(QWidget):
    """Dedicated page for model management.

    Receives references to ``ModelManager`` and ``Assistant`` via
    dependency injection (never via ``self._parent()`` lookups which
    are fragile and break when widgets are added to layout managers).
    """

    def __init__(
        self,
        model_manager: Any | None = None,
        assistant: Any | None = None,
        event_bus: Any | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model_manager = model_manager
        self._assistant = assistant
        self._event_bus = event_bus
        self._models: list[ModelInfo] = []
        self._selected_model: ModelInfo | None = None
        self._is_loading = False
        self._load_worker: ModelLoadWorker | None = None
        self._status_label = QLabel("Status: Not loaded")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self._model_list = QListWidget()
        self._model_list.itemClicked.connect(self._on_model_selected)
        left.addWidget(QLabel("Models"))
        left.addWidget(self._model_list)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_select_folder = QPushButton("Select Models Folder")
        btn_layout.addWidget(self._btn_refresh)
        btn_layout.addWidget(self._btn_select_folder)
        left.addLayout(btn_layout)

        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_select_folder.clicked.connect(self._on_select_folder)

        left.addWidget(self._status_label)

        layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        right.addWidget(QLabel("Details"))
        right.addWidget(self._details)

        btn_action_layout = QHBoxLayout()
        btn_action_layout.addStretch()
        self._btn_activate = QPushButton("Activate")
        self._btn_unload = QPushButton("Unload")
        self._btn_download = QPushButton("Download Model")
        btn_action_layout.addWidget(self._btn_activate)
        btn_action_layout.addWidget(self._btn_unload)
        btn_action_layout.addWidget(self._btn_download)
        right.addLayout(btn_action_layout)

        self._btn_activate.clicked.connect(self._on_activate)
        self._btn_unload.clicked.connect(self._on_unload)
        self._btn_download.clicked.connect(self._on_download)

        self._update_unload_button()

        layout.addLayout(right, stretch=2)

    def set_models(self, models: list[ModelInfo]) -> None:
        self._models = models
        self._model_list.clear()
        for model in models:
            source_tag = model.source.display_name if model.source else ""
            display = f"{model.name} [{source_tag}]" if source_tag else model.name
            if model.active:
                display = f"{display} (active)"
            item = QListWidgetItem(display)
            item.setData(1000, model.name)
            self._model_list.addItem(item)

    def set_active_model(self, model_name: str) -> None:
        for i in range(self._model_list.count()):
            item = self._model_list.item(i)
            if item.data(1000) == model_name:
                item.setSelected(True)
                self._model_list.setCurrentItem(item)
                break

    def set_model_manager(self, model_manager: Any) -> None:
        """Inject or replace the model manager reference."""
        self._model_manager = model_manager

    def set_model_status(self, status: ModelStatus, message: str = "") -> None:
        """Update the status label with a model load state."""
        from ui.design import WORKSPACE as palette

        display = status.description
        if message:
            display = f"{display} — {message}"
        self._status_label.setText(f"Status: {display}")
        if status == ModelStatus.MODEL_AVAILABLE:
            self._status_label.setStyleSheet(
                f"QLabel {{ color: {palette.emerald_text}; font-weight: bold; }}"
            )
        elif status in (ModelStatus.LOAD_FAILED, ModelStatus.RUNTIME_UNAVAILABLE):
            self._status_label.setStyleSheet(
                f"QLabel {{ color: {palette.error}; font-weight: bold; }}"
            )
        elif status == ModelStatus.LOADING:
            self._status_label.setStyleSheet(
                f"QLabel {{ color: {palette.warning}; font-weight: bold; }}"
            )
        else:
            self._status_label.setStyleSheet(
                f"QLabel {{ color: {palette.text_secondary}; }}"
            )

    def _on_model_selected(self, item: QListWidgetItem) -> None:
        model_name = item.data(1000)
        self._selected_model = next((m for m in self._models if m.name == model_name), None)
        if self._selected_model:
            self._details.setText(self._format_model_details(self._selected_model))

    def _format_model_details(self, model: ModelInfo) -> str:
        source_display = model.source.display_name if model.source else "Unknown"
        lines = [
            f"<b>Name:</b> {model.name}",
            f"<b>Source:</b> {source_display}",
            f"<b>Type:</b> {model.model_type.display_name if model.model_type else 'Unknown'}",
            f"<b>Format:</b> {model.model_format}",
            f"<b>Path:</b> {model.path}",
            f"<b>Size:</b> {model.size_bytes / 1024 / 1024:.1f} MB" if model.size_bytes else "<b>Size:</b> N/A",
            f"<b>Active:</b> {'Yes' if model.active else 'No'}",
        ]
        if model.architecture:
            lines.append(f"<b>Architecture:</b> {model.architecture}")
        if model.parameters:
            lines.append(f"<b>Parameters:</b> {model.parameters}")
        if model.quantization:
            lines.append(f"<b>Quantization:</b> {model.quantization}")
        if model.context_length:
            lines.append(f"<b>Context Length:</b> {model.context_length}")
        caps_list = [k for k, v in model.capabilities.to_dict().items() if v]
        if caps_list:
            lines.append(f"<b>Capabilities:</b> {', '.join(caps_list)}")
        return "<br>".join(lines)

    def _on_refresh(self) -> None:
        if self._model_manager is not None:
            self._model_manager.rescan()
            self.set_models(self._model_manager.list_models())
            self._update_status()

    def _on_select_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self,
            "Select Models Folder",
            str(self._model_manager.models_dir if self._model_manager else "."),
        )
        if directory and self._model_manager is not None:
            from pathlib import Path

            self._model_manager.set_models_dir(Path(directory))
            self._on_refresh()
            if self._assistant is not None and hasattr(self._assistant, "_engine"):
                engine = self._assistant._engine
                if engine is not None and hasattr(engine, "configure"):
                    try:
                        engine.configure(self._model_manager)
                    except Exception as exc:
                        logger.warning("Engine reconfiguration after folder change failed: %s", exc)
            self._details.setText(
                f"<b>Models Folder:</b> {directory}<br>"
                f"<b>Discovered:</b> {len(self._models)} model(s)"
            )

    def _on_activate(self) -> None:
        if self._selected_model is None:
            return
        if self._is_loading:
            return

        # Reject if a different model is already active — this check comes
        # before the assistant check so users get a clear message even if
        # the assistant is unavailable.
        if (
            self._model_manager is not None
            and self._model_manager.get_active_model() is not None
            and self._model_manager.get_active_model().name != self._selected_model.name
        ):
            active = self._model_manager.get_active_model()
            self._details.setText(
                f"<b>Cannot activate model.</b><br>"
                f"<b>Active model:</b> {active.name if active else 'Unknown'}<br><br>"
                f"Unload the currently active model first before activating a different model."
            )
            self.set_model_status(
                ModelStatus.LOAD_FAILED,
                "Another model is active — unload first",
            )
            return

        if self._assistant is None:
            self._details.setText("<b>Error:</b> Assistant not available")
            return

        self._is_loading = True
        self._btn_activate.setEnabled(False)
        self.set_model_status(ModelStatus.LOADING, f"Loading {self._selected_model.name}")

        # Force UI update so the LOADING state is visible before the blocking
        # model operation starts in the worker thread.
        QApplication.processEvents()

        if self._model_manager is None:
            self._is_loading = False
            self._btn_activate.setEnabled(True)
            return

        self._load_worker = ModelLoadWorker(
            self._model_manager, self._selected_model.name
        )
        self._load_worker.finished.connect(self._on_model_load_finished)
        self._load_worker.start()

    def _on_unload(self) -> None:
        """Unload the currently active model."""
        if self._model_manager is None:
            return

        active = self._model_manager.get_active_model()
        active_name = active.name if active else ""

        self._model_manager.unload()

        # Sync engine state
        if self._assistant is not None and hasattr(self._assistant, "_engine"):
            engine = self._assistant._engine
            if engine is not None and hasattr(engine, "unload"):
                engine.unload()

        # Refresh model list (clears active flags)
        if self._model_manager is not None:
            self.set_models(self._model_manager.list_models())

        self._update_unload_button()

        if self._selected_model is not None:
            self._details.setText(
                f"<b>Model unloaded.</b><br>"
                f"<b>Formerly active:</b> {active_name}"
                if active_name
                else "<b>No model was active.</b>"
            )
        self.set_model_status(ModelStatus.NO_MODEL_AVAILABLE)

        # Publish MODEL_UNLOADED so MainWindow and other listeners can update
        if self._assistant is not None and hasattr(self._assistant, "event_bus"):
            self._assistant.event_bus.publish(
                "MODEL_UNLOADED",
                data={"model": active_name},
            )

        logger.info("Model unloaded: %s", active_name or "(none)")

    def _on_model_load_finished(self, model_name: str, error: str) -> None:
        self._is_loading = False
        self._btn_activate.setEnabled(True)
        self._load_worker = None

        if error:
            self._details.setText(
                f"<b>Model detected, but it could not be loaded.</b><br>"
                f"<b>Error:</b> {error}<br><br>"
                f"Ensure llama-cpp-python is installed: pip install llama-cpp-python"
            )
            self.set_model_status(ModelStatus.LOAD_FAILED, error)
            return

        # Configure engine on the main thread (Qt objects must stay on GUI thread)
        if self._assistant is not None and hasattr(self._assistant, "_engine"):
            engine = self._assistant._engine
            if engine is not None and hasattr(engine, "configure"):
                try:
                    engine.configure(self._model_manager)
                except Exception as exc:
                    logger.error("Engine configuration after model load failed: %s", exc)

        # Publish MODEL_LOADED so MainWindow._on_model_loaded can update
        # status bar and combo box (same event switch_model used to fire).
        if self._assistant is not None and hasattr(self._assistant, "event_bus"):
            self._assistant.event_bus.publish(
                "MODEL_LOADED",
                data={
                    "model": model_name,
                    "path": str(self._selected_model.path) if self._selected_model else "",
                },
            )

        if self._selected_model is not None:
            self._details.setText(self._format_model_details(self._selected_model))
        self.set_model_status(ModelStatus.MODEL_AVAILABLE, model_name)
        self._update_unload_button()

    def _on_download(self) -> None:
        from ui.model_manager_dialog import ModelManagerDialog

        dialog = ModelManagerDialog(
            model_manager=self._model_manager,
            event_bus=self._event_bus,
            parent=self,
        )
        dialog.exec()

    def _update_unload_button(self) -> None:
        """Enable Unload only when a model is actively loaded."""
        has_active = (
            self._model_manager is not None
            and self._model_manager.get_active_model() is not None
        )
        self._btn_unload.setEnabled(has_active)
        self._btn_unload.setVisible(True)

    def _update_status(self) -> None:
        if self._model_manager is None:
            self.set_model_status(ModelStatus.NO_MODEL_AVAILABLE)
            self._update_unload_button()
            return
        if not self._model_manager.runtime_available:
            self.set_model_status(ModelStatus.RUNTIME_UNAVAILABLE)
            self._update_unload_button()
            return
        if self._model_manager.is_ready:
            self.set_model_status(ModelStatus.MODEL_AVAILABLE, self._model_manager.get_active_model().name)
        elif self._models:
            self.set_model_status(ModelStatus.NO_MODEL_AVAILABLE)
        else:
            self.set_model_status(ModelStatus.NO_MODEL_AVAILABLE)
        self._update_unload_button()