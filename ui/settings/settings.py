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
from ui.settings.profile_tabs import (
    BehaviorTab,
    BoundariesTab,
    CommunicationTab,
    ExpertiseTab,
    PersonalityTab,
    ProfileTab,
)
from ui.settings.model_storage_tabs import (
    ModelStatusTab,
    StorageTab,
)
from ui.settings.logging_language_tabs import (
    LoggingTab,
    LanguageTab,
)
from ui.settings.plugin_tab import (
    PluginTab,
)
from ui.settings.generation_memory_tabs import (
    GenerationSettingsTab,
    MemorySettingsTab,
)
from ui.settings.filesystem_tab import (
    FilesystemSecurityTab,
)
from ui.settings.audio_tab import (
    _AudioTestWorker,
    AudioSettingsTab,
)


class VoiceSettingsTab(QWidget):
    """Tab for voice/STT/TTS configuration.

    Exposes controls for the STT subsystem (fully functional) and TTS
    subsystem (with stub fallback), with independent input/output switches.
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

        # --- Independent voice directions ---
        self._input_enabled_chk = QCheckBox("Enable voice input")
        self._input_enabled_chk.setToolTip("Allow microphone recording, speech recognition, and wake-word input")
        self._input_enabled_chk.stateChanged.connect(self._on_voice_input_enabled_changed)
        self._output_enabled_chk = QCheckBox("Enable voice output")
        self._output_enabled_chk.setToolTip("Allow the assistant to read responses aloud")
        self._output_enabled_chk.stateChanged.connect(self._on_voice_output_enabled_changed)
        main_layout.addWidget(self._input_enabled_chk)
        main_layout.addWidget(self._output_enabled_chk)
        self._enabled_chk = self._input_enabled_chk

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

        # --- Wake Word section (Phase 7) ---
        wake_group = QGroupBox("Wake Word")
        wake_layout = QFormLayout(wake_group)

        self._wake_enabled_chk = QCheckBox("Enable wake-word detection (\"Hey Jarvis\")")
        self._wake_enabled_chk.setToolTip(
            "When enabled, the assistant listens for the wake phrase and starts a voice interaction"
        )
        self._wake_enabled_chk.stateChanged.connect(self._on_wake_enabled_changed)
        wake_layout.addRow(self._wake_enabled_chk)

        self._wake_hotword_edit = QLineEdit()
        self._wake_hotword_edit.setToolTip(
            "Wake phrase (openwakeword label, e.g. 'hey_jarvis')"
        )
        self._wake_hotword_edit.editingFinished.connect(self._on_wake_hotword_changed)
        wake_layout.addRow(QLabel("<b>Phrase</b>"), self._wake_hotword_edit)

        main_layout.addWidget(wake_group)

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
        if self._provider_combo.findText(provider) < 0:
            # Saved provider is unavailable — recommendation: the first offered
            # (faster-whisper if installed, otherwise stub).
            provider = self._provider_combo.itemText(0)
        self._provider_combo.setCurrentIndex(max(self._provider_combo.findText(provider), 0))

        # Model: the recommended value is the saved model if it exists locally,
        # otherwise the first available local model (order = sorted by name).
        model = stt_cfg.get("model", "")
        recommended_fallback = False
        if not model or self._model_combo.findText(model) < 0:
            first = self._model_combo.itemText(0) if self._model_combo.count() else ""
            if first and first != "No models found":
                model = first
                recommended_fallback = True
        self._select_combo_text(self._model_combo, model)

        device = stt_cfg.get("device", "auto")
        if self._device_combo.findText(device) < 0:
            device = "auto"
        self._device_combo.setCurrentIndex(max(self._device_combo.findText(device), 0))

        language = config.get("voice.language", "auto")
        display = self._LANG_DISPLAY.get(language, "Auto")
        self._language_combo.setCurrentIndex(max(self._language_combo.findText(display), 0))

        legacy_enabled = config.get("voice.enabled", True)
        self._input_enabled_chk.blockSignals(True)
        self._input_enabled_chk.setChecked(config.get("voice.input_enabled", legacy_enabled))
        self._input_enabled_chk.blockSignals(False)
        self._output_enabled_chk.blockSignals(True)
        self._output_enabled_chk.setChecked(config.get("voice.output_enabled", legacy_enabled))
        self._output_enabled_chk.blockSignals(False)

        tts_cfg = config.get("voice.tts", {})
        self._tts_provider_combo.blockSignals(True)
        tts_provider = tts_cfg.get("provider", "pyttsx3")
        if self._tts_provider_combo.findText(tts_provider) < 0:
            tts_provider = self._tts_provider_combo.itemText(0)
        self._tts_provider_combo.setCurrentIndex(max(self._tts_provider_combo.findText(tts_provider), 0))
        self._tts_provider_combo.blockSignals(False)

        self._tts_voice_combo.blockSignals(True)
        voice_id = tts_cfg.get("voice", "")
        idx = self._tts_voice_combo.findData(voice_id) if voice_id else -1
        if idx >= 0:
            self._tts_voice_combo.setCurrentIndex(idx)
        elif self._tts_voice_combo.count() > 0:
            # Recommended value: the first (default) system voice
            self._tts_voice_combo.setCurrentIndex(0)
        self._tts_voice_combo.blockSignals(False)

        # Recommended values: rate 200 wpm, volume 100%
        self._tts_rate_slider.blockSignals(True)
        self._tts_rate_slider.setValue(tts_cfg.get("rate", 200))
        self._tts_rate_slider.blockSignals(False)
        self._tts_rate_value.setText(str(self._tts_rate_slider.value()))

        self._tts_volume_slider.blockSignals(True)
        self._tts_volume_slider.setValue(int(tts_cfg.get("volume", 1.0) * 100))
        self._tts_volume_slider.blockSignals(False)
        self._tts_volume_value.setText(f"{self._tts_volume_slider.value()}%")

        # Wake word (Phase 7) — recommended phrase: hey_jarvis
        wake_cfg = config.get("voice.wake_word", {})
        self._wake_enabled_chk.blockSignals(True)
        self._wake_enabled_chk.setChecked(bool(wake_cfg.get("enabled", True)))
        self._wake_enabled_chk.blockSignals(False)
        self._wake_hotword_edit.blockSignals(True)
        self._wake_hotword_edit.setText(str(wake_cfg.get("hotword", "hey_jarvis")))
        self._wake_hotword_edit.blockSignals(False)

        if recommended_fallback:
            self._persist_recommended_stt(config, provider=provider, model=model)

        self._update_status()

    def _persist_recommended_stt(self, config: ConfigManager, provider: str, model: str) -> None:
        """Persist the recommended STT values so the next STT build uses them."""
        try:
            config.set("voice.stt.provider", provider)
            config.set("voice.stt.model", model)
            config.set("voice.stt.device", "auto")
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "voice.stt.model", "value": model},
                )
        except Exception:
            logger.debug("Persisting recommended STT values failed", exc_info=True)

    def save_settings(self, config: ConfigManager) -> None:
        input_enabled = self._input_enabled_chk.isChecked()
        output_enabled = self._output_enabled_chk.isChecked()
        config.set("voice.input_enabled", input_enabled)
        config.set("voice.output_enabled", output_enabled)
        config.set("voice.enabled", input_enabled or output_enabled)
        if self._event_bus is not None:
            self._event_bus.publish("CONFIG_CHANGED", {"key": "voice.input_enabled", "value": input_enabled})
            self._event_bus.publish("CONFIG_CHANGED", {"key": "voice.output_enabled", "value": output_enabled})
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
        from core.paths import get_model_category_dir

        stt_dir = get_model_category_dir("stt")
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        if stt_dir.is_dir():
            for d in sorted(stt_dir.iterdir()):
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

    def _on_voice_input_enabled_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked
        self._config.set("voice.input_enabled", enabled)
        if self._event_bus is not None:
            self._event_bus.publish("CONFIG_CHANGED", {"key": "voice.input_enabled", "value": enabled})

    def _on_voice_output_enabled_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked
        self._config.set("voice.output_enabled", enabled)
        if self._event_bus is not None:
            self._event_bus.publish("CONFIG_CHANGED", {"key": "voice.output_enabled", "value": enabled})

    def _on_voice_enabled_changed(self, state: int) -> None:
        """Compatibility alias for integrations using the former master switch."""
        self._on_voice_input_enabled_changed(state)

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

    # --- Wake Word handlers (Phase 7) ---
    def _on_wake_enabled_changed(self, state: int) -> None:
        enabled = state == Qt.CheckState.Checked
        self._config.set("voice.wake_word.enabled", enabled)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.wake_word.enabled", "value": enabled}
            )
        # Apply immediately to the live VoiceManager
        if self._voice_manager is not None:
            try:
                if enabled:
                    self._voice_manager.start_wake_word()
                else:
                    self._voice_manager.stop_wake_word()
            except Exception:
                pass

    def _on_wake_hotword_changed(self) -> None:
        hotword = self._wake_hotword_edit.text().strip() or "hey_jarvis"
        self._config.set("voice.wake_word.hotword", hotword)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "voice.wake_word.hotword", "value": hotword}
            )
        # Note: changing the phrase requires a VoiceManager restart so the
        # provider is recreated with the new label (documented limitation).
        self._status_label.setText(
            "Wake phrase saved — it will be applied after the application is restarted"
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


class APISettingsTab(QWidget):
    """Tab for the opt-in Online API — multiple providers, one key each.

    The application is offline-first: the API is disabled by default and
    every key is stored only in ``settings.json`` (under
    ``api.providers.<id>.api_key``).  Built-in presets cover OpenRouter,
    Groq, Google AI Studio, Mistral, Cerebras, and Together; custom
    OpenAI-compatible endpoints can be registered too.

    Agents opt in per model with ``<provider>:<model>`` model names —
    e.g. ``groq:llama-3.3-70b-versatile`` or ``openrouter:z-ai/glm-5.2:free``.
    """

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._event_bus = event_bus
        self._current_provider = ""
        self._catalogue: list[dict] = []
        self._setup_ui()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        from ai.engine.api_engine import PROVIDER_PRESETS

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        notice = QLabel(
            "Online API is optional and disabled by default. Each provider "
            "uses its own personal key, stored only in local settings. "
            "Agents opt in per model with '<provider>:<model>' model names."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("color: #8C9692; font-size: 11px;")
        layout.addWidget(notice)

        top_row = QHBoxLayout()
        self._enabled_chk = QCheckBox("Enable Online API")
        self._enabled_chk.stateChanged.connect(self._on_enabled_changed)
        top_row.addWidget(self._enabled_chk)
        top_row.addStretch()
        layout.addLayout(top_row)

        # --- Provider selector ---
        provider_form = QFormLayout()
        self._provider_combo = QComboBox()
        for pid, meta in PROVIDER_PRESETS.items():
            label = meta["label"]
            self._provider_combo.addItem(f"{label} ({pid})", pid)
        # Custom providers registered by the user
        custom = self._config.get("api.custom_providers", {}) or {}
        for pid, meta in sorted(custom.items()):
            label = str(meta.get("label", pid))
            self._provider_combo.addItem(f"{label} ({pid}) — custom", pid)
        self._provider_combo.currentIndexChanged.connect(self._on_provider_selected)
        provider_form.addRow(QLabel("<b>Provider</b>"), self._provider_combo)
        layout.addLayout(provider_form)

        # --- Selected provider form ---
        form = QFormLayout()

        self._key_link = QLabel("")
        self._key_link.setStyleSheet("color: #8C9692; font-size: 10px;")
        self._key_link.setOpenExternalLinks(True)
        form.addRow(self._key_link)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_edit.setPlaceholderText("paste your personal key here")
        self._api_key_edit.setToolTip(
            "Your personal API key for this provider. Stored only in the "
            "local settings.json and never logged or committed."
        )
        form.addRow(QLabel("<b>API key</b>"), self._api_key_edit)

        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText("https://... (from the preset)")
        form.addRow(QLabel("<b>Base URL</b>"), self._base_url_edit)

        self._default_model_edit = QLineEdit()
        self._default_model_edit.setPlaceholderText("default model id for this provider")
        form.addRow(QLabel("<b>Default model</b>"), self._default_model_edit)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.setEditText("")
        self._model_combo.setToolTip(
            "Type any model id, or pick one. 'Fetch models' loads the "
            "provider's live catalogue using your key."
        )
        self._model_combo.currentTextChanged.connect(self._on_model_picked)
        form.addRow(QLabel("<b>Models</b>"), self._model_combo)

        self._timeout_spin = QSpinBox()
        self._timeout_spin.setRange(10, 600)
        self._timeout_spin.setSingleStep(10)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.setToolTip("Per-request timeout (free models can queue)")
        form.addRow(QLabel("<b>Request timeout</b>"), self._timeout_spin)

        layout.addLayout(form)

        # --- Custom provider row ---
        custom_row = QHBoxLayout()
        self._custom_id_edit = QLineEdit()
        self._custom_id_edit.setPlaceholderText("custom-id (e.g. myllm)")
        self._custom_url_edit = QLineEdit()
        self._custom_url_edit.setPlaceholderText("https://my-endpoint/v1")
        self._btn_add_custom = QPushButton("Add custom provider")
        self._btn_add_custom.clicked.connect(self._on_add_custom)
        custom_row.addWidget(self._custom_id_edit)
        custom_row.addWidget(self._custom_url_edit, stretch=1)
        custom_row.addWidget(self._btn_add_custom)
        layout.addLayout(custom_row)

        # --- Buttons ---
        btn_row = QHBoxLayout()
        self._btn_fetch = QPushButton("Fetch models")
        self._btn_fetch.clicked.connect(self._on_fetch_models)
        btn_row.addWidget(self._btn_fetch)
        self._btn_test = QPushButton("Test connection")
        self._btn_test.clicked.connect(self._on_test_clicked)
        btn_row.addWidget(self._btn_test)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # --- Fetched-models selection list (appears after Fetch models) ---
        self._models_group = QGroupBox("Fetched models — select the free ones agents may use")
        self._models_group.setVisible(False)
        models_layout = QVBoxLayout(self._models_group)

        sel_row = QHBoxLayout()
        self._btn_select_free = QPushButton("Select all free")
        self._btn_select_free.setToolTip(
            "Check every zero-cost model in the catalogue below."
        )
        self._btn_select_free.clicked.connect(self._on_select_all_free)
        self._btn_clear_selection = QPushButton("Clear selection")
        self._btn_clear_selection.clicked.connect(self._on_clear_model_selection)
        sel_row.addWidget(self._btn_select_free)
        sel_row.addWidget(self._btn_clear_selection)
        sel_row.addStretch()
        models_layout.addLayout(sel_row)

        self._btn_auto_free = QCheckBox(
            "Auto-select free models for agents by task"
        )
        self._btn_auto_free.setToolTip(
            "When enabled, agents without an explicit model are routed to a "
            "free online model chosen from your selection below — coding "
            "tasks get coder models, reasoning tasks get thinking models, "
            "vision tasks get vision models."
        )
        self._btn_auto_free.stateChanged.connect(self._on_auto_free_toggled)
        models_layout.addWidget(self._btn_auto_free)

        self._models_list = QListWidget()
        self._models_list.setMaximumHeight(220)
        self._models_list.setToolTip(
            "Tick the models you want available to agents. Free models "
            "are marked with [FREE]."
        )
        self._models_list.itemChanged.connect(self._on_model_item_changed)
        models_layout.addWidget(self._models_list)
        layout.addWidget(self._models_group)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8C9692; font-size: 11px;")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        layout.addStretch()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _selected_provider(self) -> str:
        idx = self._provider_combo.currentIndex()
        data = self._provider_combo.itemData(idx)
        return str(data or "openrouter")

    def _preset_for(self, pid: str) -> dict[str, str]:
        from ai.engine.api_engine import PROVIDER_PRESETS

        if pid in PROVIDER_PRESETS:
            return PROVIDER_PRESETS[pid]
        custom = self._config.get("api.custom_providers", {}) or {}
        meta = custom.get(pid, {})
        return {
            "label": str(meta.get("label", pid)),
            "base_url": str(meta.get("base_url", "")),
            "key_hint": "",
            "key_url": "",
        }

    # ------------------------------------------------------------------ #
    # Load / save
    # ------------------------------------------------------------------ #
    def load_settings(self, config: ConfigManager) -> None:
        self._config = config
        self._enabled_chk.blockSignals(True)
        self._enabled_chk.setChecked(bool(config.get("api.enabled", False)))
        self._enabled_chk.blockSignals(False)
        self._load_current_provider()

    def save_settings(self, config: ConfigManager) -> None:
        self._persist_current_provider()
        if self._models_list.count() > 0:
            self._persist_selection()
        config.set("api.enabled", self._enabled_chk.isChecked())
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "api.enabled", "value": self._enabled_chk.isChecked()},
            )

    def _load_current_provider(self) -> None:
        from ai.engine.api_engine import get_provider_config

        pid = self._selected_provider()
        self._current_provider = pid
        meta = self._preset_for(pid)
        if meta.get("key_url"):
            self._key_link.setText(
                f'Get a key: <a href="{meta["key_url"]}">{meta["key_url"]}</a>'
            )
        else:
            self._key_link.setText("")
        self._base_url_edit.setPlaceholderText(meta.get("base_url", "https://..."))

        entry = get_provider_config(self._config, pid) or {}
        self._api_key_edit.setText(str(entry.get("api_key", "") or ""))
        self._base_url_edit.setText(str(entry.get("base_url", "") or ""))
        self._default_model_edit.setText(str(entry.get("model", "") or ""))
        self._timeout_spin.setValue(int(entry.get("timeout") or 120))

        # Curated suggestions per provider
        self._model_combo.blockSignals(True)
        self._model_combo.clear()
        suggestions = self._curated_models(pid)
        if suggestions:
            self._model_combo.addItems(suggestions)
        self._model_combo.setEditText("")
        self._model_combo.blockSignals(False)

        key_present = bool(entry.get("api_key"))
        self._status_label.setText(
            f"{meta['label']}: key configured ✔" if key_present
            else f"{meta['label']}: no key yet — paste one above when ready."
        )
        self._load_saved_selection(pid)

    def _persist_current_provider(self) -> None:
        """Persist the form fields under ``self._current_provider``."""
        from ai.engine.api_engine import set_provider_config

        pid = self._current_provider or self._selected_provider()
        if not pid:
            return
        meta = self._preset_for(pid)
        set_provider_config(
            self._config,
            pid,
            api_key=self._api_key_edit.text(),
            base_url=self._base_url_edit.text().strip() or meta.get("base_url", ""),
            model=self._default_model_edit.text().strip(),
            timeout=self._timeout_spin.value(),
        )

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    def _on_enabled_changed(self, _state: int) -> None:
        enabled = self._enabled_chk.isChecked()
        self._config.set("api.enabled", enabled)
        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED", {"key": "api.enabled", "value": enabled}
            )
        self._status_label.setText(
            "Online API enabled — agents with '<provider>:<model>' will use it."
            if enabled else "Online API disabled."
        )

    def _on_provider_selected(self, _idx: int) -> None:
        # Save the previously shown provider's form before switching.
        if self._current_provider and self._current_provider != self._selected_provider():
            try:
                self._persist_current_provider()
                if self._models_list.count() > 0:
                    self._persist_selection()
            except Exception:
                logger.debug("Provider switch persist failed", exc_info=True)
        self._catalogue = []
        self._models_list.clear()
        self._models_group.setVisible(False)
        self._load_current_provider()

    def _on_model_picked(self, text: str) -> None:
        if text:
            self._default_model_edit.setText(text)

    def _on_add_custom(self) -> None:
        from ai.engine.api_engine import register_custom_provider

        pid = self._custom_id_edit.text().strip().lower()
        url = self._custom_url_edit.text().strip()
        if not pid or not url:
            self._status_label.setText(
                "Custom provider needs an id and a base URL."
            )
            return
        register_custom_provider(self._config, pid, url)
        # Add to the combo and select it
        self._provider_combo.addItem(f"{pid} — custom", pid)
        idx = self._provider_combo.findData(pid)
        if idx >= 0:
            self._provider_combo.setCurrentIndex(idx)
        self._custom_id_edit.clear()
        self._custom_url_edit.clear()
        self._status_label.setText(
            f"Custom provider '{pid}' added — paste its API key above."
        )

    def _on_fetch_models(self) -> None:
        """Live-fetch the provider's model catalogue using the entered key.

        Fills the Models dropdown *and* reveals the checkable list below
        the button, where the user picks the free models agents may use.
        """
        from ai.engine.api_engine import (
            fetch_provider_model_details,
            set_provider_config,
        )

        pid = self._selected_provider()
        meta = self._preset_for(pid)
        # Persist the just-typed key first so fetch_provider_config sees it.
        set_provider_config(
            self._config, pid,
            api_key=self._api_key_edit.text(),
            base_url=self._base_url_edit.text().strip() or meta.get("base_url", ""),
            model=self._default_model_edit.text().strip(),
            timeout=self._timeout_spin.value(),
        )
        self._status_label.setText("Fetching model catalogue…")
        QApplication.processEvents()
        self._catalogue = fetch_provider_model_details(self._config, pid)
        if self._catalogue:
            self._model_combo.blockSignals(True)
            self._model_combo.clear()
            self._model_combo.addItems([m["id"] for m in self._catalogue])
            self._model_combo.setEditText("")
            self._model_combo.blockSignals(False)

            self._models_group.setVisible(True)
            self._rebuild_models_list()
            free_count = sum(1 for m in self._catalogue if m["free"])
            self._status_label.setText(
                f"{len(self._catalogue)} model(s) fetched "
                f"({free_count} free) — tick the ones agents may use, or "
                "'Select all free'."
            )
        else:
            self._status_label.setText(
                "Could not fetch the catalogue (missing key or network issue) "
                "— curated suggestions remain available."
            )

    # ------------------------------------------------------------------ #
    # Free-model selection list
    # ------------------------------------------------------------------ #
    def _full_spec(self, model_id: str) -> str:
        return f"{self._selected_provider()}:{model_id}"

    def _saved_specs(self, pid: str) -> list[str]:
        raw = self._config.get("api.selected_free_models", []) or []
        return [
            str(s) for s in raw
            if isinstance(s, str) and s.startswith(f"{pid}:")
        ]

    def _load_saved_selection(self, pid: str) -> None:
        """Restore the auto-free checkbox and (if a catalogue exists) ticks."""
        self._btn_auto_free.blockSignals(True)
        self._btn_auto_free.setChecked(
            bool(self._config.get("api.auto_free_models", False))
        )
        self._btn_auto_free.blockSignals(False)
        saved = set(self._saved_specs(pid))
        if self._catalogue:
            self._rebuild_models_list(checked=saved)

    def _rebuild_models_list(self, checked: set[str] | None = None) -> None:
        """(Re)build the checkable fetched-models list."""
        from PySide6.QtCore import Qt as _Qt

        checked = checked if checked is not None else self._current_specs()
        self._models_list.blockSignals(True)
        self._models_list.clear()
        for m in self._catalogue:
            spec = self._full_spec(m["id"])
            label = f"{'[FREE]  ' if m['free'] else ''}{m['id']}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | _Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                _Qt.CheckState.Checked if spec in checked
                else _Qt.CheckState.Unchecked
            )
            item.setData(_Qt.ItemDataRole.UserRole, spec)
            self._models_list.addItem(item)
        self._models_list.blockSignals(False)

    def _current_specs(self) -> set[str]:
        """The set of checked specs currently in the list."""
        from PySide6.QtCore import Qt as _Qt

        specs: set[str] = set()
        for i in range(self._models_list.count()):
            item = self._models_list.item(i)
            if (
                item is not None
                and item.checkState() == _Qt.CheckState.Checked
            ):
                spec = str(item.data(_Qt.ItemDataRole.UserRole) or "")
                if spec:
                    specs.add(spec)
        return specs

    def _persist_selection(self) -> None:
        """Persist all checked models across providers into the config."""
        pid = self._current_provider or self._selected_provider()
        saved = [s for s in self._saved_specs(pid)]
        new_specs = sorted(self._current_specs())
        merged = sorted(
            set(
                [s for s in saved if s not in new_specs
                 and s not in self._current_specs()]
                + [s for s in new_specs]
            )
        )
        # Keep specs for other providers untouched.
        other = [
            str(s) for s in (self._config.get("api.selected_free_models", []) or [])
            if isinstance(s, str) and not s.startswith(f"{pid}:")
        ]
        self._config.set("api.selected_free_models", sorted(set(other + merged)))
        self._publish_config("api.selected_free_models", self._config.get(
            "api.selected_free_models", []
        ))

    def _on_select_all_free(self) -> None:
        """Tick every free model in the fetched catalogue."""
        from PySide6.QtCore import Qt as _Qt

        if not self._catalogue:
            return
        self._models_list.blockSignals(True)
        for i in range(self._models_list.count()):
            item = self._models_list.item(i)
            if item is None:
                continue
            mid = str(item.data(_Qt.ItemDataRole.UserRole) or "").split(":", 1)[-1]
            is_free = next(
                (m["free"] for m in self._catalogue if m["id"] == mid), False
            )
            item.setCheckState(
                _Qt.CheckState.Checked if is_free else _Qt.CheckState.Unchecked
            )
        self._models_list.blockSignals(False)
        self._persist_selection()
        free_count = sum(1 for m in self._catalogue if m["free"])
        self._status_label.setText(
            f"Selected all {free_count} free model(s) — agents can use them."
        )

    def _on_clear_model_selection(self) -> None:
        from PySide6.QtCore import Qt as _Qt

        self._models_list.blockSignals(True)
        for i in range(self._models_list.count()):
            item = self._models_list.item(i)
            if item is not None:
                item.setCheckState(_Qt.CheckState.Unchecked)
        self._models_list.blockSignals(False)
        self._persist_selection()
        self._status_label.setText("Selection cleared.")

    def _on_auto_free_toggled(self, _state: int) -> None:
        enabled = self._btn_auto_free.isChecked()
        self._config.set("api.auto_free_models", enabled)
        self._publish_config("api.auto_free_models", enabled)
        self._status_label.setText(
            "Agents without an explicit model will use a selected free "
            "online model picked by task type."
            if enabled else "Auto free-model selection disabled."
        )

    def _publish_config(self, key: str, value: Any) -> None:
        if self._event_bus is not None:
            try:
                self._event_bus.publish("CONFIG_CHANGED", {"key": key, "value": value})
            except Exception:
                logger.debug("CONFIG_CHANGED publish failed", exc_info=True)

    def _on_model_item_changed(self, _item: QListWidgetItem) -> None:
        """Persist the ticked free models whenever the user (un)checks one."""
        self._persist_selection()

    def _on_test_clicked(self) -> None:
        """Send a 1-token test request to verify key + model."""
        from ai.engine.api_engine import OpenAICompatibleEngine

        self._status_label.setText("Testing…")
        pid = self._selected_provider()
        meta = self._preset_for(pid)
        key = self._api_key_edit.text().strip()
        url = self._base_url_edit.text().strip() or meta.get("base_url", "")
        model = (
            self._default_model_edit.text().strip()
            or self._model_combo.currentText().strip()
        )
        if not key or not model:
            self._status_label.setText("API key and model are required for the test.")
            return
        try:
            engine = OpenAICompatibleEngine(
                api_key=key, base_url=url, model=model,
                timeout=float(self._timeout_spin.value()),
            )
            reply = engine.generate_chat(
                [{"role": "user", "content": "Reply with the single word: ready"}],
                config=None,
            )
            self._status_label.setText(f"Connection OK — model replied: {reply[:60]!r}")
        except Exception as exc:
            self._status_label.setText(f"Connection failed: {exc}")

    # ------------------------------------------------------------------ #
    # Curated suggestions
    # ------------------------------------------------------------------ #
    def _curated_models(self, pid: str) -> list[str]:
        from ai.engine.api_engine import FREE_OPENROUTER_MODELS

        if pid == "openrouter":
            return list(FREE_OPENROUTER_MODELS)
        if pid == "groq":
            return [
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
                "openai/gpt-oss-20b",
                "openai/gpt-oss-120b",
                "qwen/qwen3-32b",
                "moonshotai/kimi-k2-instruct",
            ]
        if pid == "google":
            return [
                "gemini-2.0-flash",
                "gemini-2.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.5-pro",
            ]
        if pid == "mistral":
            return [
                "mistral-small-latest",
                "mistral-large-latest",
                "open-mistral-nemo",
            ]
        if pid == "cerebras":
            return [
                "llama-3.3-70b",
                "llama3.1-8b",
                "qwen-3-32b",
            ]
        if pid == "together":
            return [
                "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                "meta-llama/Llama-3.1-8B-Instruct-Turbo",
                "Qwen/Qwen2.5-72B-Instruct-Turbo",
            ]
        return []


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
        self.setWindowTitle("Settings")
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
        self._btn_close = QPushButton("Close")
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
        self._api_tab = self._create_api_tab()
        self._tab_widget.addTab(self._api_tab, "Online API")
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

    def _create_api_tab(self) -> APISettingsTab:
        return APISettingsTab(config=self._config, event_bus=self._event_bus)

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

        if self._api_tab is not None:
            self._api_tab.load_settings(self._config)

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

            if self._config is not None and self._api_tab is not None:
                self._api_tab.save_settings(self._config)

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