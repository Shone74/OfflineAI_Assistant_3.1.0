"""Generation and Memory settings tabs."""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.event_bus import EventBus


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