"""Voice system base classes — STT, TTS, and wake-word providers.

All providers have a stub fallback so the application runs without the
optional native backends (whisper.cpp, pyttsx3, openwakeword).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from core.logger import get_logger

logger = get_logger("voice")


class STTProvider(ABC):
    """Speech-to-text provider."""

    name: str = "abstract"

    @abstractmethod
    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str:
        """Return the recognised text for *audio*."""


class TTSProvider(ABC):
    """Text-to-speech provider."""

    name: str = "abstract"

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        ...

    @abstractmethod
    def speak(self, text: str) -> None:
        """Speak *text* aloud."""

    def stop(self) -> None:
        """Stop any in-progress speech and release resources (optional override)."""


class WakeWordProvider(ABC):
    """Hot-word / wake-word detector."""

    name: str = "abstract"
    hotword: str = "hey"

    @property
    @abstractmethod
    def is_listening(self) -> bool:
        ...

    @abstractmethod
    def start(self, on_detected: Callable[[], Any]) -> None:
        """Start listening; *on_detected* is called when the hot-word fires."""

    @abstractmethod
    def stop(self) -> None:
        """Stop listening."""