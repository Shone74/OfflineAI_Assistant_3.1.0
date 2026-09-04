"""Voice package - Phase 7: STT / TTS / wake-word (stub-backed by default)."""

from voice.audio import AudioConfig, AudioManager, StubAudioManager, create_audio
from voice.base import STTProvider, TTSProvider, WakeWordProvider
from voice.manager import VoiceManager

__all__ = [
    "AudioConfig",
    "AudioManager",
    "STTProvider",
    "StubAudioManager",
    "TTSProvider",
    "VoiceManager",
    "WakeWordProvider",
    "create_audio",
]
