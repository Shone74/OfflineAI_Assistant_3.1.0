"""Wake-word detectors with a stub fallback.

Real backend: :class:`OpenWakeWord`, backed by the ``openwakeword`` library and
``sounddevice``.  Detection runs on a daemon thread so the GUI is never blocked.
When neither package is installed (or no microphone is available) the factory
falls back to :class:`StubWakeWord` — a safe no-op that never fires.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from core.logger import get_logger
from voice.base import WakeWordProvider

logger = get_logger("voice.wake_word")


class StubWakeWord(WakeWordProvider):
    """No-op detector — never fires (headless / CI safe)."""

    name = "stub"

    def __init__(self, hotword: str = "hey_jarvis") -> None:
        self.hotword = hotword
        self._callback: Callable[[], Any] | None = None

    @property
    def is_listening(self) -> bool:
        return False

    def start(self, on_detected: Callable[[], Any]) -> None:
        self._callback = on_detected

    def stop(self) -> None:
        self._callback = None  # type: ignore[assignment]


class OpenWakeWord(WakeWordProvider):
    """Detector backed by the OpenWakeWord library.

    Runs a background daemon thread that continuously captures audio from the
    default microphone and performs keyword-spotting inference via
    ``openwakeword.Model.predict``.  When the configured hot-word score exceeds
    *threshold* the *on_detected* callback is invoked (on the detection thread).

    Requires the ``openwakeword`` and ``sounddevice`` packages at run-time.
    When either is missing the factory (:func:`create_wake_word`) falls back to
    :class:`StubWakeWord`.
    """

    name = "openwakeword"

    #: Inference sample-rate for OpenWakeWord models.
    _SAMPLE_RATE: int = 16000
    _CHANNELS: int = 1
    #: Frames per detection block (~64 ms at 16 kHz).
    _BLOCK_FRAMES: int = 1024
    #: Default detection confidence threshold.
    _THRESHOLD: float = 0.5
    #: Maximum time (seconds) to wait for the detection thread to join.
    # L12: the detection loop checks the stop flag between ~64 ms stream
    # reads, so a cooperative stop completes within a couple of read
    # cycles; 0.5 s is comfortably above that while keeping the GUI-side
    # wait (stop() may run on the GUI thread) short.
    _JOIN_TIMEOUT: float = 0.5

    def __init__(self, hotword: str = "hey_jarvis", threshold: float | None = None) -> None:
        from openwakeword import Model

        self.hotword = hotword
        # Windows has no tflite-runtime wheels — use ONNX models
        # (the default downloads include "hey_jarvis").
        try:
            self._model = Model(inference_framework="onnx")
        except Exception:
            # Older versions / other OS — fall back to default init
            self._model = Model()
        # Validate that the model contains the requested label; if not — log, don't crash.
        try:
            labels = list(getattr(self._model, "models", {}).keys())
            if labels and hotword not in labels:
                logger.warning(
                    "Hotword %r not among models %s — using the first available one",
                    hotword,
                    labels,
                )
                if len(labels) == 1:
                    self.hotword = labels[0]
                else:
                    # "hey_jarvis" exists among the predefined ones; if the user
                    # requests a non-existent one, fall back to the default.
                    self.hotword = "hey_jarvis" if "hey_jarvis" in labels else labels[0]
        except Exception:
            pass
        self._threshold = threshold if threshold is not None else self._THRESHOLD
        self._running = False
        self._thread: threading.Thread | None = None
        self._callback: Callable[[], Any] | None = None

    @property
    def is_listening(self) -> bool:
        return self._running

    def start(self, on_detected: Callable[[], Any]) -> None:
        """Begin continuous wake-word detection on a daemon thread.

        Safe to call when already running (no-op).  When the wake-word is
        detected *on_detected* is invoked.
        """
        if self._running:
            return
        self._callback = on_detected
        self._running = True
        self._thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="openwakeword-listener"
        )
        self._thread.start()
        logger.info("OpenWakeWord detection started (hotword=%s)", self.hotword)

    def _listen_loop(self) -> None:
        """Capture audio and run inference until :meth:`stop` is called."""
        try:
            import numpy as np  # noqa: F401  — np used inside _detect
            import sounddevice as sd

            with sd.InputStream(
                samplerate=self._SAMPLE_RATE,
                channels=self._CHANNELS,
                dtype="float32",
                blocksize=self._BLOCK_FRAMES,
            ) as stream:
                while self._running:
                    chunk, _ = stream.read(self._BLOCK_FRAMES)
                    self._detect(chunk)
        except ImportError:
            logger.warning("sounddevice not available — wake-word detection disabled")
        except Exception:  # never let detection-loop crash propagate
            logger.debug("OpenWakeWord detection loop error", exc_info=True)
        finally:
            self._running = False

    def _detect(self, audio_chunk: Any) -> None:
        """Run inference on a single audio chunk; fire callback if matched."""
        if not self._running:
            return
        callback = self._callback
        if callback is None:
            return
        try:
            import numpy as np

            audio = np.asarray(audio_chunk).flatten()
            if audio.size == 0:
                return
            result = self._model.predict(audio)
            if not result:
                return
            score = result.get(self.hotword, 0)
            if isinstance(score, (int, float)) and score > self._threshold:
                logger.info("Wake-word detected (score=%.3f)", score)
                callback()
        except Exception:  # detection errors are non-fatal
            logger.debug("OpenWakeWord prediction error", exc_info=True)

    def stop(self) -> None:
        """Stop detection and release audio resources."""
        self._running = False
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._JOIN_TIMEOUT)
        self._callback = None
        logger.info("OpenWakeWord detection stopped")


def create_wake_word(
    preferred: str = "openwakeword",
    hotword: str = "hey_jarvis",
    threshold: float | None = None,
) -> WakeWordProvider:
    """Return the best available wake-word provider, falling back to StubWakeWord.

    ``hotword`` default is "hey_jarvis" — openwakeword's predefined
    "hey jarvis" phrase (specification §1).
    """
    logger.info("Wake-word provider requested: %s (hotword=%s)", preferred, hotword)
    if preferred == "openwakeword":
        try:
            return OpenWakeWord(hotword=hotword, threshold=threshold)
        except Exception:
            logger.info("openwakeword unavailable, using stub")
    return StubWakeWord(hotword=hotword)
