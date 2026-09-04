"""Text-to-speech providers with a stub fallback."""

from __future__ import annotations

from core.logger import get_logger
from voice.base import TTSProvider

logger = get_logger("voice.tts")


class StubTTS(TTSProvider):
    name = "stub"

    @property
    def is_ready(self) -> bool:
        return True

    def speak(self, text: str) -> None:
        from core.logger import get_logger

        get_logger("voice").info("TTS(stub): %s", text)

    def stop(self) -> None:
        pass


def _pyttsx3_available() -> bool:
    try:
        import pyttsx3  # noqa: F401
        return True
    except (ImportError, RuntimeError):
        return False


class Pyttsx3TTS(TTSProvider):
    name = "pyttsx3"

    def __init__(self) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()

    @property
    def is_ready(self) -> bool:
        return self._engine is not None

    @property
    def voices(self) -> list[str]:
        try:
            return [v.id for v in self._engine.getProperty("voices")]
        except Exception:
            return []

    def set_voice(self, voice_id: str) -> None:
        if voice_id:
            self._engine.setProperty("voice", voice_id)

    def set_rate(self, rate: int) -> None:
        self._engine.setProperty("rate", rate)

    def set_volume(self, volume: float) -> None:
        self._engine.setProperty("volume", max(0.0, min(1.0, volume)))

    def speak(self, text: str) -> None:
        self._engine.say(text)
        self._engine.runAndWait()

    def stop(self) -> None:
        try:
            self._engine.stop()
        except Exception:
            logger.debug("TTS engine stop failed", exc_info=True)


def create_tts(preferred: str = "pyttsx3") -> TTSProvider:
    import logging

    log = logging.getLogger("voice")
    log.info("TTS provider requested: %s", preferred)
    if preferred == "pyttsx3":
        try:
            return Pyttsx3TTS()
        except Exception:
            log.info("pyttsx3 unavailable, using stub TTS")
    return StubTTS()
