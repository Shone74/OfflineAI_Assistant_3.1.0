"""Speech-to-text providers with a stub fallback.

Real backend: :class:`WhisperSTT`, backed by ``faster-whisper`` + ``ctranslate2``.
The Whisper model is resolved to a LOCAL directory under
``core.paths.STT_DIR`` (``models/voice/stt/<model>``). If the directory is
absent, transcription raises :class:`STTModelError` — the provider never
downloads a model automatically and never fabricates a transcript.

The model is loaded lazily on first transcription and cached on the instance, so
a microphone click does not reload it.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

from core.paths import STT_DIR
from voice.base import STTProvider

logger = logging.getLogger("voice")

_TARGET_SAMPLE_RATE = 16000


class STTModelError(Exception):
    """Controlled error for missing/invalid local Whisper model.

    VoiceManager converts this into a ``VOICE_ERROR`` EventBus event so no
    empty transcript ever reaches the Assistant.
    """


def _whisper_available() -> bool:
    """True only when the ``faster-whisper`` backend can be imported."""
    return importlib.util.find_spec("faster_whisper") is not None


def _cuda_available() -> bool:
    """True when a GPU-capable ``ctranslate2`` build can use CUDA."""
    try:
        import ctranslate2

        cuda = getattr(ctranslate2, "cuda", None)
        return cuda is not None and cuda.is_available()
    except Exception:  # noqa: BLE001
        return False


class StubSTT(STTProvider):
    """No-op provider — returns a canned transcript (testing / headless)."""

    name = "stub"

    def __init__(self, transcript: str = "") -> None:
        self._transcript = transcript

    def set_transcript(self, text: str) -> None:
        self._transcript = text

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str:
        return self._transcript


class WhisperSTT(STTProvider):
    """Real offline STT backed by ``faster-whisper``.

    Parameters
    ----------
    model_name:
        Local model folder name under ``stt_dir`` (e.g. ``"tiny"``).
    device:
        ``auto`` (CUDA when available else CPU), ``cuda``, or ``cpu``.
    language:
        ``auto`` (Whisper detects), ``sr`` (Serbian), ``en`` (English).
    stt_dir:
        Local directory holding model folders (defaults to ``STT_DIR``).
    """

    name = "whisper"

    def __init__(
        self,
        model_name: str = "tiny",
        device: str = "auto",
        language: str = "auto",
        stt_dir: str | Path = STT_DIR,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._language = language
        self._stt_dir = Path(stt_dir)
        self._model: Any = None
        self._resolved_device: str | None = None

    @property
    def device(self) -> str:
        if self._resolved_device is None:
            self._resolved_device = self._resolve_device(self._device)
        return self._resolved_device

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device == "auto":
            return "cuda" if _cuda_available() else "cpu"
        return device  # explicit cuda/cpu — never silently fall back (§6)

    def _load_model(self) -> None:
        """Lazily load the LOCAL Whisper model (cached on the instance)."""
        if self._model is not None:
            return
        if not _whisper_available():
            raise STTModelError("faster-whisper is not installed")

        model_path = self._stt_dir / self._model_name
        if not model_path.is_dir():
            raise STTModelError(
                f"Whisper model '{self._model_name}' not found in the local model "
                f"directory '{self._stt_dir}'. The application runs fully offline; "
                "faster-whisper will not download a model automatically."
            )

        from faster_whisper import WhisperModel

        device = self._resolve_device(self._device)
        # float16 is the standard GPU compute type and fits the RTX 3080 (10 GB)
        # for the small models targeted here; int8_float32 gives a good
        # CPU precision/performance balance.
        compute_type = "float16" if device == "cuda" else "int8_float32"
        try:
            self._model = WhisperModel(
                str(model_path), device=device, compute_type=compute_type
            )
        except Exception as exc:
            self._model = None
            raise STTModelError(
                f"failed to load Whisper model '{self._model_name}': {exc}"
            ) from exc

        self._resolved_device = device
        logger.info(
            "WhisperSTT ready (model=%s, device=%s, compute_type=%s, language=%s)",
            self._model_name,
            device,
            compute_type,
            self._language,
        )

    def transcribe(self, audio: bytes, sample_rate: int = 16000) -> str:
        """Transcribe PCM bytes (16 kHz mono int16) to text.

        Returns ``""`` for empty audio (never fabricates). Raises
        :class:`STTModelError` if the local model is missing/invalid.
        """
        if not audio:
            return ""
        self._load_model()

        import numpy as np

        if sample_rate != _TARGET_SAMPLE_RATE:
            logger.warning(
                "WhisperSTT.transcribe received sample_rate=%d but expects %d; "
                "audio may produce inaccurate results",
                sample_rate,
                _TARGET_SAMPLE_RATE,
            )
        arr = np.frombuffer(audio, dtype=np.int16)
        if arr.size == 0:
            return ""
        float_audio = arr.astype(np.float32) / 32768.0
        language = None if self._language == "auto" else self._language

        try:
            segments, _info = self._model.transcribe(float_audio, language=language)
        except Exception as exc:
            raise STTModelError(f"Whisper transcription failed: {exc}") from exc
        text = " ".join(seg.text for seg in segments).strip()
        return text

    def stop(self) -> None:
        """Release the underlying model (idempotent, safe)."""
        if self._model is not None:
            unload = getattr(self._model, "unload", None)
            if callable(unload):
                try:
                    unload()
                except Exception:
                    logger.debug("WhisperSTT unload failed", exc_info=True)
            self._model = None
            self._resolved_device = None


def create_stt(
    preferred: str = "whisper",
    *,
    model_name: str = "tiny",
    device: str = "auto",
    language: str = "auto",
    stt_dir: str | Path = STT_DIR,
) -> STTProvider:
    """Return the best available STT provider, falling back to :class:`StubSTT`.

    ``preferred="whisper"`` selects :class:`WhisperSTT` when ``faster-whisper``
    is importable. Construction is lazy (no model download, no model load), so a
    missing local model surfaces as a controlled :class:`STTModelError` at
    transcription time rather than crashing startup.
    """
    logger.info("STT provider requested: %s", preferred)
    if preferred == "whisper" and _whisper_available():
        try:
            return WhisperSTT(
                model_name=model_name,
                device=device,
                language=language,
                stt_dir=stt_dir,
            )
        except Exception:  # noqa: BLE001 — backend unusable, fall back to stub
            logger.info("WhisperSTT init failed, using stub STT")
    return StubSTT()
