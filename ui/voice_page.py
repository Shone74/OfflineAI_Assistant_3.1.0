"""Voice management page — STT, TTS, and audio device configuration."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from ui.settings import AudioSettingsTab, VoiceSettingsTab


class VoicePage(QWidget):
    """Page for voice system configuration (STT, audio devices, etc.)."""

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
        if self._event_bus is not None:
            self._event_bus.subscribe("STT_RECONFIGURED", self._on_stt_reconfigured)
            self._event_bus.subscribe("TTS_RECONFIGURED", self._on_tts_reconfigured)

    def _on_stt_reconfigured(self, event_type: str, data: dict[str, Any]) -> None:
        """Refresh voice settings status after runtime STT reconfiguration."""
        self._tab_voice._update_status()

    def _on_tts_reconfigured(self, event_type: str, data: dict[str, Any]) -> None:
        """Refresh voice settings status after runtime TTS reconfiguration."""
        self._tab_voice._update_status()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()

        self._tab_voice = VoiceSettingsTab(
            config=self._config,
            event_bus=self._event_bus,
            voice_manager=self._voice_manager,
        )
        self._tabs.addTab(self._tab_voice, "Voice")

        self._tab_audio = AudioSettingsTab(
            config=self._config,
            event_bus=self._event_bus,
            voice_manager=self._voice_manager,
        )
        self._tabs.addTab(self._tab_audio, "Audio")

        layout.addWidget(self._tabs)

        # Automatically populate the section with recommended values from the
        # configuration (provider = faster-whisper / pyttsx3 if available, model =
        # the first local STT model, device = auto, rate = 200, volume = 100%).
        # Without this, the page would stay empty until the user opens the
        # Advanced Settings dialog.
        try:
            self._tab_voice.load_settings(self._config)
        except Exception:
            pass
        try:
            self._tab_audio.load_settings(self._config)
        except Exception:
            pass

    def get_voice_settings(self) -> VoiceSettingsTab:
        return self._tab_voice

    def get_audio_settings(self) -> AudioSettingsTab:
        return self._tab_audio