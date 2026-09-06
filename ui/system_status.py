"""System status bar — lightweight CPU/RAM/GPU display + model status."""

from __future__ import annotations

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QStatusBar

from ai.models.model_loader import ModelStatus

_REFRESH_MS = 2000


class SystemStatusWidget(QStatusBar):
    """Status bar that polls system metrics periodically."""

    def __init__(self, model_name: str = "N/A") -> None:
        super().__init__()
        self._cpu_label = QLabel()
        self._ram_label = QLabel()
        self._gpu_label = QLabel()
        self._model_label = QLabel()
        self._model_status_label = QLabel()

        self.addWidget(self._cpu_label)
        self.addWidget(self._ram_label)
        self.addWidget(self._gpu_label)
        self.addPermanentWidget(self._model_label)
        self.addPermanentWidget(self._model_status_label)

        self.set_model(model_name)
        self._refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(_REFRESH_MS)

    def set_model(self, name: str) -> None:
        if name and name not in ("N/A", "stub", "unavailable", "No model loaded"):
            self._model_label.setText(f"Model: {name}")
        else:
            self._model_label.setText("Model: N/A — open Models page to load a model")

    def set_model_status_text(self, text: str) -> None:
        """Set the model status label text and color."""
        self._model_status_label.setText(text)
        if "ready" in text.lower() or "loaded" in text.lower():
            self._model_status_label.setStyleSheet("QLabel { color: #1D8A68; font-weight: bold; }")
        elif "fail" in text.lower() or "error" in text.lower():
            self._model_status_label.setStyleSheet("QLabel { color: #D96565; font-weight: bold; }")
        elif "loading" in text.lower():
            self._model_status_label.setStyleSheet("QLabel { color: #D6A24A; font-weight: bold; }")
        elif "unavailable" in text.lower():
            self._model_status_label.setStyleSheet("QLabel { color: #D96565; font-weight: bold; }")
        else:
            self._model_status_label.setStyleSheet("QLabel { color: #8C9692; }")

    def set_model_status(self, status: ModelStatus, model_name: str = "") -> None:
        """Set model status from a ModelStatus enum value."""
        if status == ModelStatus.STUB_MODE:
            self.set_model_status_text("Stub (TEST MODE)")
        elif status == ModelStatus.MODEL_AVAILABLE:
            self.set_model_status_text(f"{model_name} (ready)" if model_name else "Ready")
        elif status == ModelStatus.RUNTIME_UNAVAILABLE:
            self.set_model_status_text("Runtime unavailable")
        elif status == ModelStatus.LOAD_FAILED:
            self.set_model_status_text("Load failed")
        elif status == ModelStatus.LOADING:
            self.set_model_status_text("Loading...")
        elif status == ModelStatus.NO_MODEL_AVAILABLE:
            self.set_model_status_text("No model")
        else:
            self.set_model_status_text(status.description)

    def _refresh(self) -> None:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        self._cpu_label.setText(f"CPU {cpu:.0f}%")
        self._ram_label.setText(f"RAM {ram:.0f}%")
        self._gpu_label.setText("GPU —")
