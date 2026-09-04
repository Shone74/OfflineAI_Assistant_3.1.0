"""Audio capture abstraction for the Voice subsystem.

Separates low-level microphone / audio-capture concerns from ``VoiceManager``
so VoiceManager remains an orchestration layer.

Backends
--------
* :class:`StubAudioManager` — safe no-op when no native backend is available
  (Phase 1 default); raises when recording is attempted and never yields fake audio.
* :class:`SoundDeviceAudioManager` — real microphone capture backed by
  ``sounddevice`` + PortAudio.

Native-rate capture architecture (Phase 2D)
-------------------------------------------
When ``prefer_wasapi`` is enabled (the default), the manager discovers the
**WASAPI** endpoint corresponding to the system's default input device and
opens a PortAudio ``InputStream`` at that endpoint's *native* sample rate with
``dtype=float32``.  WASAPI only accepts the hardware-native rate, so PortAudio
does **not** perform any internal resampling — the raw, high-fidelity float32
stream is captured directly.

After recording stops, the float32 buffer is downsampled to Whisper's target
rate (16 kHz) using ``scipy.signal.resample_poly`` — a high-quality polyphase
filter with built-in anti-aliasing.  If scipy is unavailable, the manager falls
back to a linear-interpolation resampler (``numpy.interp``) with a warning
log.  If WASAPI is unavailable, the manager falls back to the legacy MME path
(int16 capture at 16 kHz with PortAudio's internal resampling).

In all paths the returned ``(pcm_bytes, sample_rate)`` from ``stop_recording``
is **int16 mono at the target rate (16 kHz)** — preserving the interface
contract with :class:`~voice.stt.WhisperSTT` and :class:`~voice.manager.VoiceManager`.

Lifecycle
---------
Recording is **user-driven**, not duration-bound: ``start_recording`` opens a
non-blocking PortAudio ``InputStream`` whose callback appends PCM to an internal
buffer, and ``stop_recording`` stops/closes that *stream instance* and
returns the accumulated bytes (resampled to 16 kHz int16 if needed).
"""

from __future__ import annotations

import importlib.util
import logging
import threading
import wave
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.paths import DATA_DIR

logger = get_logger("voice.audio")

RECORDINGS_DIR: Path = DATA_DIR / "voice_captures"

# WASAPI host-API index in PortAudio's host-API enumeration (Windows).
# 0=MME, 1=DirectSound, 2=WASAPI, 3=WDM-KS
_WASAPI_HOST_API = 2


class AudioCaptureError(Exception):
    """Controlled error raised by AudioManager when capture cannot proceed.

    VoiceManager converts this into a ``VOICE_ERROR`` EventBus event.
    """


class RecordingState(str, Enum):
    """Deterministic recording lifecycle states."""

    IDLE = "idle"
    RECORDING = "recording"
    STOPPING = "stopping"
    ERROR = "error"


@dataclass
class AudioConfig:
    """Audio capture settings (defaults compatible with Whisper).

    Attributes
    ----------
    sample_rate:
        Target recording rate in Hz (Whisper expects 16 kHz).  This is the
        *canonical* rate returned by ``stop_recording`` and accepted by STT —
        regardless of the native capture rate.
    channels:
        Number of input channels (Whisper expects mono = 1).
    format:
        PCM format label for downstream consumers.
    dtype:
        Default sounddevice/pynumpy sample dtype used for MME fallback capture
        (``int16`` -> signed 16-bit little-endian PCM, i.e. ``pcm_s16le``).
        Ignored when WASAPI native capture is active — float32 is always used
        for native-rate capture.
    device:
        PortAudio input-device index.  ``None`` selects the system default
        input device.  When ``None`` and ``prefer_wasapi`` is ``True``, the
        manager discovers the WASAPI endpoint corresponding to the default
        physical input and captures at its native rate.

        When set to an explicit PortAudio index (e.g. selected by the user in
        Settings), that device is used directly — bypassing the WASAPI
        name-discovery fallback.  This prevents the false-match problem where
        truncated PortAudio device names cause an incorrect WASAPI endpoint
        to be selected.
    input_device_name:
        Human-readable name of the selected input device, persisted for
        re-resolution after restart.  Empty string when ``System Default``.
    input_device_hostapi:
        Host API name of the selected input device (e.g. ``"Windows WASAPI"``).
        Persisted for re-resolution.  Empty string when ``System Default``.
    output_device_index:
        PortAudio output-device index for playback.  ``None`` selects the
        system default output device.
    output_device_name:
        Human-readable name of the selected output device.
    output_device_hostapi:
        Host API name of the selected output device.
    recording_duration:
        Retained for API compatibility. The manual-start/stop lifecycle no
        longer gates on a fixed duration — recording ends when the user
        stops it.
    capture_sample_rate:
        Native hardware sample rate for WASAPI capture.  When ``None``
        (default), the rate is auto-discovered from the selected WASAPI
        endpoint's ``default_samplerate``.  When set explicitly, overrides
        auto-discovery (useful for testing).
    prefer_wasapi:
        When ``True`` (default), attempt to find and use a WASAPI endpoint
        for the default input device.  If no WASAPI endpoint is found or the
        WASAPI stream fails to open, falls back to the MME path transparently.
    wasapi_fallback_to_mme:
        When ``True`` (default), fall back to MME capture (16 kHz, int16,
        PortAudio resampling) if WASAPI is unavailable.  When ``False``,
        raises :class:`AudioCaptureError` if WASAPI cannot be used.
    """

    sample_rate: int = 16000
    channels: int = 1
    format: str = "pcm_s16le"
    dtype: str = "int16"
    device: int | None = None
    recording_duration: float = 6.0
    capture_sample_rate: int | None = None
    prefer_wasapi: bool = True
    wasapi_fallback_to_mme: bool = True
    input_device_name: str = ""
    input_device_hostapi: str = ""
    output_device_index: int | None = None
    output_device_name: str = ""
    output_device_hostapi: str = ""


class AudioManager:
    """Low-level audio capture interface.

    Responsibilities owned by this layer (not by ``VoiceManager``):

        * microphone device selection
        * recording state
        * sample rate / channels / format
        * audio buffering
        * start recording
        * stop recording
        * resource cleanup
        * last-recording retention / playback

    The base class is a safe stub. Use :class:`SoundDeviceAudioManager` (via
    :func:`create_audio`) for real capture when a backend is available.
    """

    def __init__(self, config: AudioConfig | None = None) -> None:
        self.config: AudioConfig = config or AudioConfig()
        self._recording = False
        self._state: RecordingState = RecordingState.IDLE
        self._last_recording_path: Path | None = None
        self._lock = threading.Lock()

    name: str = "abstract"

    @property
    def is_recording(self) -> bool:
        return self._recording

    @property
    def state(self) -> RecordingState:
        return self._state

    @property
    def last_audio(self) -> bytes:
        """PCM bytes of the most recent completed recording (empty in stub)."""
        return b""

    @property
    def last_recording_path(self) -> Path | None:
        """Filesystem path of the most recent completed recording, if persisted."""
        return self._last_recording_path

    def is_available(self) -> bool:
        """Whether a real microphone backend + input device is present (stub -> ``False``)."""
        return False

    def list_devices(self) -> Sequence[dict[str, Any]]:
        """Return available input devices (stub -> empty sequence)."""
        return []

    def list_output_devices(self) -> Sequence[dict[str, Any]]:
        """Return available output devices (stub -> empty sequence)."""
        return []

    def resolve_input_device(self) -> int | None:
        """Resolve the persisted device selection to a live index (stub -> None)."""
        return self.config.device

    def resolve_output_device(self) -> int | None:
        """Resolve the persisted output device selection to a live index (stub -> None)."""
        return self.config.output_device_index

    def set_output_device(self, device_index: int | None) -> None:
        """Update the output device for playback at runtime (stub: no-op)."""
        _ = device_index

    def start_recording(self) -> None:
        """Begin recording.

        The stub raises :class:`NotImplementedError` to signal that real
        microphone capture is unavailable. ``VoiceManager`` treats this as a
        graceful no-op so no empty or fake audio is forwarded to the STT
        provider.
        """
        raise NotImplementedError("Audio capture is not yet available")

    def stop_recording(self) -> tuple[bytes, int]:
        """Stop recording and return ``(audio_bytes, sample_rate)``.

        Returns ``(b"", sample_rate)`` if no recording is in progress, so
        callers never receive a stale/None buffer.
        """
        self._recording = False
        self._state = RecordingState.IDLE
        return b"", self.config.sample_rate

    def stop(self) -> None:
        """Release audio resources (idempotent, safe)."""
        self._recording = False
        self._state = RecordingState.IDLE
        logger.debug("AudioManager.stop() called")

    def save_last_recording(self, path: str | Path) -> None:
        """Persist the most recent completed recording to *path*.

        The stub is a no-op (no audio is ever captured in stub mode).
        Concrete backends overwrite the file on every successful save so only
        the latest recording is retained.
        """
        return

    def play_audio(self, audio: bytes, sample_rate: int) -> None:
        """Play raw PCM *audio* (default sample rate 16000).

        Playback is best-effort and runs off the calling thread. The stub is a
        no-op.
        """
        return

    def play_last(self) -> None:
        """Replay the most recently retained recording (no-op in the stub)."""
        return


class StubAudioManager(AudioManager):
    """Explicit no-op audio backend (mirrors the stub provider pattern)."""

    name = "stub"

    def is_available(self) -> bool:
        return False


def _sounddevice_available() -> bool:
    """True only when the ``sounddevice`` backend can be imported."""
    return importlib.util.find_spec("sounddevice") is not None


def _scipy_available() -> bool:
    """True only when ``scipy`` is importable (for high-quality resampling)."""
    return importlib.util.find_spec("scipy") is not None


def resolve_device_index(
    devices: list[dict[str, Any]],
    saved_index: int | None,
    saved_name: str,
    saved_hostapi: str,
) -> int | None:
    """Resolve a persisted device selection to a live PortAudio index.

    Uses saved device name + host API to find the matching entry in the
    *current* device enumeration, falling back to the saved index only if
    name-based matching fails.  Returns ``None`` when ``saved_name`` is empty
    (meaning ``System Default``).

    Device-name matching uses **exact** equality (after case-insensitive
    comparison), not substring matching.  This prevents truncated PortAudio
    device names from producing false matches — e.g. a saved name of
    ``"Microsoft Sound Mapper - Input"`` must match a device whose full name
    contains that string exactly, not merely as a substring of a different
    device's name.
    """
    if not saved_name:
        return None
    import sounddevice as sd

    host_apis = sd.query_hostapis()
    saved_name_lower = saved_name.lower()
    for i, dev in enumerate(devices):
        dev_name = dev.get("name", "")
        if dev_name.lower() != saved_name_lower and saved_name_lower not in dev_name.lower():
            continue
        ha_idx = dev.get("hostapi", -1)
        if ha_idx >= 0 and ha_idx < len(host_apis):
            ha_name = host_apis[ha_idx]["name"]
            if saved_hostapi and saved_hostapi.lower() == ha_name.lower():
                return dev.get("index", i)
            if saved_hostapi and saved_hostapi.lower() in ha_name.lower():
                return dev.get("index", i)
    # Fallback: try index match
    if saved_index is not None and 0 <= saved_index < len(devices):
        dev = devices[saved_index]
        if saved_name_lower in dev.get("name", "").lower():
            return saved_index
    return None


def _normalize_device_name(name: str) -> str:
    """Extract the core physical-device identifier from a PortAudio device name.

    Strips leading role words (``Microphone``, ``Headset``, ``Input``) and any
    numeric bus prefix (``6-``) so that the same physical microphone can be
    matched across different host APIs (MME, DirectSound, WASAPI, WDM-KS).
    """
    import re

    m = re.match(
        r"^(?:Microphone|Headset|Input)\s*\(?\s*(?:\d+\s*-\s*)?(.*?)\)?\s*$",
        name,
        re.IGNORECASE,
    )
    if m:
        core = m.group(1).strip().lower()
    else:
        core = name.strip().lower()
    # Remove residual parenthesised suffixes such as "(Wave)" etc.
    core = re.sub(r"\s*\([^)]*\)\s*", "", core).strip()
    return core


def resample_audio(
    float32_bytes: bytes,
    from_rate: int,
    to_rate: int,
) -> bytes:
    """Down/up-sample mono float32 PCM *bytes* from *from_rate* to *to_rate*.

    The returned bytes are **int16** little-endian PCM at *to_rate*, suitable
    for :class:`~voice.stt.WhisperSTT`.  Uses ``scipy.signal.resample_poly``
    (polyphase anti-aliasing filter) when scipy is available; falls back to
    ``numpy.interp`` (linear interpolation) with a warning log otherwise.

    No peak-normalisation, AGC, or gain scaling is applied — the signal is
    passed through faithfully, clipped only to prevent int16 overflow.
    """
    if not float32_bytes:
        return b""
    if from_rate <= 0 or to_rate <= 0:
        raise ValueError(f"invalid sample rate: from_rate={from_rate}, to_rate={to_rate}")

    import numpy as np

    # Decode raw float32 little-endian bytes.
    float_arr = np.frombuffer(float32_bytes, dtype=np.float32).astype(np.float64)

    if float_arr.size == 0:
        return b""

    if from_rate == to_rate:
        int16_arr = np.clip(float_arr, -1.0, 1.0)
        int16_arr = (int16_arr * 32767.0).astype(np.int16)
        return int16_arr.tobytes()

    if _scipy_available():
        from fractions import Fraction

        from scipy.signal import resample_poly

        ratio = Fraction(to_rate, from_rate)
        up = ratio.numerator
        down = ratio.denominator
        resampled = resample_poly(float_arr, up, down, axis=0)
    else:
        logger.warning(
            "scipy not available; falling back to numpy.interp linear "
            "interpolation (degraded resampling quality)"
        )
        n_out = round(len(float_arr) * to_rate / from_rate)
        if n_out == 0:
            n_out = 1
        src_idx = np.linspace(0, len(float_arr) - 1, n_out)
        resampled = np.interp(src_idx, np.arange(len(float_arr)), float_arr)

    # Clip to [-1, 1] to prevent int16 overflow, then convert.
    clipped = np.clip(resampled, -1.0, 1.0)
    int16_arr = (clipped * 32767.0).astype(np.int16)
    return int16_arr.tobytes()


class SoundDeviceAudioManager(AudioManager):
    """Real microphone capture backed by ``sounddevice`` + PortAudio.

    When WASAPI is available and ``prefer_wasapi`` is ``True``, the manager
    discovers the WASAPI endpoint for the default input device and captures at
    the hardware-native sample rate with ``dtype=float32`` — avoiding
    PortAudio's internal resampling.  The float32 buffer is down-sampled to the
    target rate (16 kHz) inside :meth:`stop_recording` using
    :func:`resample_audio`.

    When WASAPI is unavailable or ``prefer_wasapi`` is ``False``, falls back to
    the legacy MME path: ``dtype=int16`` at the target rate (16 kHz).

    Recording runs until :meth:`stop_recording` is called (user-driven), never
    for a fixed duration.  The underlying stream is owned by this instance and
    is closed via the *instance* ``stream.close()`` (never a module-level
    ``sd.close()``).
    """

    name = "sounddevice"

    def __init__(self, config: AudioConfig | None = None) -> None:
        super().__init__(config)
        self._stream: Any = None
        self._buffer: bytearray = bytearray()
        self._actual_sample_rate: int = self.config.sample_rate
        self._actual_capture_sample_rate: int = self.config.sample_rate
        self._capture_dtype: str = self.config.dtype
        self._wasapi_active: bool = False
        self._selected_device: int | None = None
        self._output_device_index: int | None = self.config.output_device_index

    def is_available(self) -> bool:
        """True only when sounddevice is importable *and* a default input exists."""
        if not _sounddevice_available():
            return False
        try:
            import sounddevice as sd

            idx = self.config.device if self.config.device is not None else sd.default.device[0]
            if idx is None or idx < 0:
                return False
            info = sd.query_devices(idx, "input")
            return bool(info.get("max_input_channels", 0))
        except Exception:
            logger.debug("sounddevice availability probe failed", exc_info=True)
            return False

    def _discover_wasapi_input(self) -> tuple[int | None, int | None]:
        """Find the WASAPI input endpoint for the system's default physical microphone.

        Returns ``(device_index, native_sample_rate)`` for the matching WASAPI
        endpoint, or ``(None, None)`` if none is found.

        Strategy:
        1. Use the WASAPI host API's own ``default_input_device`` index
           (from ``sd.query_hostapis()``).  This directly identifies the WASAPI
           version of the system-default audio input endpoint — no name
           matching required, avoiding false matches from truncated PortAudio
           device names.
        2. If the host-API approach is unavailable (non-Windows or older
           PortAudio that doesn't populate ``default_input_device``), fall
           back to *exact* normalised-name matching against the default
           input device.  Substring matching is intentionally NOT used because
           a short truncated name (e.g. ``"high definition aud"``) can be a
           substring of an unrelated device's longer name (e.g.
           ``"high definition audio device"``), causing the wrong endpoint to
           be selected.
        """
        if not _sounddevice_available():
            return None, None
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            host_apis = sd.query_hostapis()

            # --- Strategy 1: WASAPI host API's own default input device ---
            wasapi_api_idx = None
            for ha_idx, ha in enumerate(host_apis):
                ha_name = ha.get("name", "").lower()
                if ha_name in ("windows wasapi", "wasapi"):
                    wasapi_api_idx = ha_idx
                    break
            if wasapi_api_idx is None:
                wasapi_api_idx = _WASAPI_HOST_API

            if 0 <= wasapi_api_idx < len(host_apis):
                default_in = host_apis[wasapi_api_idx].get("default_input_device", -1)
                if default_in is not None and 0 <= default_in < len(devices):
                    dev = devices[default_in]
                    if dev.get("max_input_channels", 0) > 0:
                        native_sr = dev.get("default_samplerate")
                        if native_sr is not None and native_sr > 0:
                            logger.info(
                                "WASAPI discovery: selected default WASAPI "
                                "input device %d (index=%s) at %d Hz",
                                default_in,
                                dev.get("name"),
                                int(native_sr),
                            )
                            return default_in, int(native_sr)

            # --- Strategy 2: exact normalised-name fallback ---
            default_idx = (
                self.config.device
                if self.config.device is not None
                else sd.default.device[0]
            )
            if default_idx is None or default_idx < 0 or default_idx >= len(devices):
                return None, None

            default_dev = devices[default_idx]
            if default_dev.get("max_input_channels", 0) <= 0:
                return None, None

            target_name = _normalize_device_name(default_dev.get("name", ""))
            if not target_name:
                return None, None

            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) <= 0:
                    continue
                if dev.get("hostapi") != wasapi_api_idx:
                    continue
                dev_name = _normalize_device_name(dev.get("name", ""))
                if dev_name == target_name:
                    native_sr = dev.get("default_samplerate")
                    if native_sr is not None and native_sr > 0:
                        logger.info(
                            "WASAPI discovery (name-fallback): matched '%s' -> "
                            "device %d at %d Hz",
                            target_name,
                            i,
                            int(native_sr),
                        )
                        return i, int(native_sr)

            logger.debug(
                "WASAPI discovery: no matching endpoint for default input '%s'",
                default_dev.get("name"),
            )
            return None, None
        except Exception:
            logger.debug("WASAPI device discovery failed", exc_info=True)
            return None, None

    def list_devices(self) -> list[dict[str, Any]]:
        """Return input-capable devices (empty if sounddevice is unavailable)."""
        if not _sounddevice_available():
            return []
        try:
            import sounddevice as sd

            return [d for d in sd.query_devices() if d.get("max_input_channels", 0) > 0]
        except Exception:
            logger.debug("sounddevice device enumeration failed", exc_info=True)
            return []

    def list_output_devices(self) -> list[dict[str, Any]]:
        """Return output-capable devices (empty if sounddevice is unavailable)."""
        if not _sounddevice_available():
            return []
        try:
            import sounddevice as sd

            return [d for d in sd.query_devices() if d.get("max_output_channels", 0) > 0]
        except Exception:
            logger.debug("sounddevice output device enumeration failed", exc_info=True)
            return []

    def resolve_input_device(self) -> int | None:
        """Resolve the persisted device selection to a live PortAudio index.

        Uses the saved device name + host API to find the matching entry in the
        current device enumeration.  Returns ``None`` when ``System Default``
        is selected (or when the saved device is no longer available).
        """
        if not self.config.input_device_name:
            return None
        if not _sounddevice_available():
            return None
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            idx = resolve_device_index(
                devices,
                self.config.device,
                self.config.input_device_name,
                self.config.input_device_hostapi,
            )
            if idx is not None:
                return idx
            logger.warning(
                "Saved input device '%s' not found; falling back to system default",
                self.config.input_device_name,
            )
            return None
        except Exception:
            logger.debug("input device resolution failed", exc_info=True)
            return None

    def _get_device_native_rate(self, device_index: int) -> int | None:
        """Return the native/default sample rate of a specific PortAudio device."""
        if not _sounddevice_available():
            return None
        try:
            import sounddevice as sd

            info = sd.query_devices(device_index)
            sr = info.get("default_samplerate")
            if sr is not None and sr > 0:
                return int(sr)
        except Exception:
            logger.debug("device native rate query failed", exc_info=True)
        return None

    def _get_device_host_api(self, device_index: int) -> str:
        """Return the human-readable host API name for a PortAudio device.

        Queries ``sd.query_devices`` for the device's ``hostapi`` index, then
        resolves it via ``sd.query_hostapis()`` to obtain the name (e.g.
        ``"Windows WASAPI"``, ``"MME"``).
        """
        if not _sounddevice_available():
            return ""
        try:
            import sounddevice as sd

            info = sd.query_devices(device_index)
            ha_idx = info.get("hostapi", -1)
            if ha_idx >= 0:
                host_apis = sd.query_hostapis()
                if ha_idx < len(host_apis):
                    return host_apis[ha_idx].get("name", "")
        except Exception:
            logger.debug("device host API lookup failed", exc_info=True)
        return ""

    def _host_api_is_wasapi(self) -> bool:
        """Return True iff the currently selected/active device is on WASAPI.

        Checks the actual host API of ``self._selected_device`` (discovery
        path) or ``self.config.device`` (explicit path).  Falls back to
        checking the stream's own device attribute when available.
        """
        dev_idx: int | None = None
        if self._selected_device is not None:
            dev_idx = self._selected_device
        elif self.config.device is not None:
            dev_idx = self.config.device

        if dev_idx is not None and dev_idx >= 0:
            host_api_name = self._get_device_host_api(dev_idx)
            return host_api_name.lower() == "windows wasapi"
        return False

    def _callback(self, indata: Any, frames: int, time: Any, status: Any) -> None:
        """PortAudio callback — append captured PCM to the buffer (thread-safe)."""
        if status:
            logger.debug("sounddevice input status: %s", status)
        try:
            with self._lock:
                self._buffer.extend(bytes(indata.tobytes()))
        except Exception:
            logger.debug("sounddevice callback buffer append failed", exc_info=True)

    def start_recording(self) -> None:
        """Open a non-blocking ``InputStream`` and begin capturing until stopped.

        When ``prefer_wasapi`` is ``True``, discovers the WASAPI endpoint for
        the default input device and captures at its native rate with
        ``dtype=float32`` — avoiding PortAudio's internal resampling.  If WASAPI
        is unavailable or the WASAPI stream fails to open, falls back to the MME
        path (int16 at the target rate) when ``wasapi_fallback_to_mme`` is set.

        Raises :class:`AudioCaptureError` if a recording is already in progress,
        the backend is unavailable, or the device cannot be opened.
        """
        if self._recording:
            raise AudioCaptureError("recording already in progress")
        if not _sounddevice_available():
            self._state = RecordingState.ERROR
            raise AudioCaptureError("sounddevice backend unavailable")
        if not self.is_available():
            self._state = RecordingState.ERROR
            raise AudioCaptureError("no input device available")

        self._state = RecordingState.RECORDING
        self._recording = True
        self._buffer = bytearray()
        self._stream = None
        self._wasapi_active = False
        self._actual_capture_sample_rate = self.config.sample_rate
        self._capture_dtype = self.config.dtype
        self._selected_device = None

        try:
            import sounddevice as sd

            # --- Explicit device selection (from Settings) ---
            # When an explicit input device has been selected by the user,
            # use it directly — bypassing the WASAPI name-discovery logic
            # that can produce false matches on truncated PortAudio names.
            if self.config.device is not None:
                self._selected_device = self.config.device
                self._actual_capture_sample_rate = (
                    self.config.capture_sample_rate
                    if self.config.capture_sample_rate is not None
                    else self.config.sample_rate
                )
                self._capture_dtype = self.config.dtype
                # Try native float32 capture at the device's native rate
                if self.config.prefer_wasapi:
                    native_sr = self._get_device_native_rate(self.config.device)
                    if native_sr and native_sr != self._actual_capture_sample_rate:
                        self._actual_capture_sample_rate = native_sr
                        self._capture_dtype = "float32"
                self._stream = sd.InputStream(
                    samplerate=self._actual_capture_sample_rate,
                    channels=self.config.channels,
                    dtype=self._capture_dtype,
                    device=self.config.device,
                    callback=self._callback,
                )
                self._stream.start()
            elif self.config.prefer_wasapi:
                wasapi_dev, native_sr = self._discover_wasapi_input()
                if wasapi_dev is not None and native_sr is not None:
                    try:
                        if (
                            self.config.capture_sample_rate is not None
                            and self.config.capture_sample_rate != native_sr
                        ):
                            logger.warning(
                                "capture_sample_rate=%d differs from WASAPI native "
                                "rate=%d; using native rate",
                                self.config.capture_sample_rate,
                                native_sr,
                            )
                        capture_rate = native_sr
                        self._actual_capture_sample_rate = capture_rate
                        self._capture_dtype = "float32"
                        self._selected_device = wasapi_dev
                        self._stream = sd.InputStream(
                            samplerate=capture_rate,
                            channels=self.config.channels,
                            dtype="float32",
                            device=self._selected_device,
                            callback=self._callback,
                        )
                        self._stream.start()
                    except Exception as exc:
                        if not self.config.wasapi_fallback_to_mme:
                            raise
                        logger.warning(
                            "WASAPI stream creation/startup failed (%s); "
                            "falling back to MME capture",
                            exc,
                        )
                        self._stream = None
                        self._selected_device = None
                else:
                    # WASAPI endpoint not found
                    if not self.config.wasapi_fallback_to_mme:
                        raise AudioCaptureError(
                            "WASAPI capture was requested but no compatible "
                            "WASAPI endpoint was found for the default input "
                            "device"
                        )
                    logger.warning(
                        "WASAPI endpoint not found; falling back to MME capture"
                    )

            # --- MME fallback (or prefer_wasapi=False) ---
            if self._stream is None:
                capture_rate = (
                    self.config.capture_sample_rate
                    if self.config.capture_sample_rate is not None
                    else self.config.sample_rate
                )
                self._actual_capture_sample_rate = capture_rate
                self._capture_dtype = self.config.dtype
                self._stream = sd.InputStream(
                    samplerate=capture_rate,
                    channels=self.config.channels,
                    dtype=self.config.dtype,
                    device=self.config.device,
                    callback=self._callback,
                )
                self._stream.start()

            # --- Verify _wasapi_active from the actual host API ---
            # _wasapi_active must reflect the real host API of the device
            # that is actually being used, NOT the sample-rate difference
            # between native and target rate.
            self._wasapi_active = self._host_api_is_wasapi()
        except AudioCaptureError:
            self._recording = False
            self._state = RecordingState.ERROR
            self._stream = None
            self._buffer = bytearray()
            raise
        except Exception as exc:
            self._recording = False
            self._state = RecordingState.ERROR
            self._stream = None
            self._buffer = bytearray()
            raise AudioCaptureError(f"failed to start recording: {exc}") from exc

    def stop_recording(self) -> tuple[bytes, int]:
        """Stop the active stream and return the accumulated PCM bytes.

        Returns ``(b"", sample_rate)`` when nothing is recording.

        When capture used ``float32`` at a native rate, the raw float32 buffer is
        float32 buffer is resampled to the target rate (16 kHz) and converted
        to int16 via :func:`resample_audio` before returning.  The MME fallback
        path returns int16 bytes directly at the target rate.

        In all cases the returned ``(audio_bytes, sample_rate)`` is **int16
        mono at the target rate** — preserving the interface contract with
        :class:`~voice.stt.WhisperSTT` and :class:`~voice.manager.VoiceManager`.

        Owns stream teardown (instance ``stop``/``close``) — no module-level
        ``sd.close()``.
        """
        if not self._recording:
            return b"", self.config.sample_rate

        self._state = RecordingState.STOPPING
        self._recording = False
        stream = self._stream
        self._stream = None
        stop_exc: Exception | None = None

        if stream is not None:
            try:
                stream.stop()
            except Exception as exc:
                stop_exc = exc
                logger.debug("stream.stop() failed", exc_info=True)
            try:
                stream.close()
            except Exception:
                logger.debug("stream.close() failed", exc_info=True)

        if stop_exc is not None:
            self._state = RecordingState.ERROR
            raise AudioCaptureError(f"recording interrupted: {stop_exc}") from stop_exc

        self._state = RecordingState.IDLE
        with self._lock:
            raw_bytes = bytes(self._buffer)
            self._buffer = bytearray()

        # --- Resampling / format conversion ---
        target_rate = self.config.sample_rate
        if self._capture_dtype == "float32" and raw_bytes:
            # Float32 capture at native rate → resample to target rate → int16
            capture_rate = self._actual_capture_sample_rate
            if capture_rate != target_rate and capture_rate > 0:
                pcm = resample_audio(raw_bytes, capture_rate, target_rate)
                logger.info(
                    "Resampled capture: %d Hz float32 -> %d Hz int16 (%d bytes in, %d bytes out)",
                    capture_rate, target_rate, len(raw_bytes), len(pcm),
                )
            else:
                # Native rate already equals target — just float32→int16
                import numpy as np

                float_arr = np.frombuffer(raw_bytes, dtype=np.float32)
                int16_arr = (np.clip(float_arr, -1.0, 1.0) * 32767.0).astype(np.int16)
                pcm = int16_arr.tobytes()
                logger.info("Converted %d Hz float32 -> %d Hz int16 (no resampling)", capture_rate, target_rate)
            self._last_audio = pcm
            self._actual_sample_rate = target_rate
        elif self._capture_dtype == "float32":
            # Float32 capture active but no audio captured — still return target rate
            pcm = b""
            self._last_audio = b""
            self._actual_sample_rate = target_rate
        else:
            # MME fallback: raw int16 at target rate (no conversion needed)
            pcm = raw_bytes
            self._last_audio = pcm
            self._actual_sample_rate = self._actual_capture_sample_rate

        return pcm, self._actual_sample_rate

    def stop(self) -> None:
        """Release the active PortAudio stream (idempotent, safe).

        Uses the stream *instance* for teardown. The previous implementation
        called ``sounddevice.close()`` (non-existent module attribute); this is
        now corrected to ``stream.stop()``/``stream.close()`` on the owned
        ``InputStream``.
        """
        self._recording = False
        self._state = RecordingState.IDLE
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                logger.debug("stream.stop() failed during stop()", exc_info=True)
            try:
                stream.close()
            except Exception:
                logger.debug("stream.close() failed during stop()", exc_info=True)
        with self._lock:
            self._buffer = bytearray()
        self._last_audio = b""
        self._last_recording_path = None
        self._actual_capture_sample_rate = self.config.sample_rate
        self._capture_dtype = self.config.dtype
        self._wasapi_active = False
        self._selected_device = None
        self._output_device_index = self.config.output_device_index
        logger.debug("SoundDeviceAudioManager stopped")

    def set_output_device(self, device_index: int | None) -> None:
        """Update the output device for playback at runtime."""
        self._output_device_index = device_index
        self.config.output_device_index = device_index

    def resolve_output_device(self) -> int | None:
        """Resolve the persisted output device selection to a live index."""
        if self._output_device_index is not None:
            return self._output_device_index
        return self.resolve_output_device_from_config()

    def resolve_output_device_from_config(self) -> int | None:
        """Resolve output device from config persistence."""
        if not self.config.output_device_name:
            return None
        if not _sounddevice_available():
            return None
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            idx = resolve_device_index(
                devices,
                self.config.output_device_index,
                self.config.output_device_name,
                self.config.output_device_hostapi,
            )
            if idx is not None:
                self._output_device_index = idx
                return idx
            logger.warning(
                "Saved output device '%s' not found; falling back to system default",
                self.config.output_device_name,
            )
            return None
        except Exception:
            logger.debug("output device resolution failed", exc_info=True)
            return None

    @property
    def last_audio(self) -> bytes:
        return getattr(self, "_last_audio", b"")

    @property
    def wasapi_active(self) -> bool:
        """True when the active capture device is on the Windows WASAPI host API."""
        return self._wasapi_active

    @property
    def capture_sample_rate(self) -> int:
        """The native hardware sample rate currently in use for capture."""
        return self._actual_capture_sample_rate

    @property
    def target_sample_rate(self) -> int:
        """The canonical output rate (16 kHz for Whisper)."""
        return self.config.sample_rate

    def save_last_recording(self, path: str | Path) -> None:
        """Write the most recent recording to *path* as 16 kHz mono WAV.

        Overwrites any previous file so only the latest recording is retained.
        Creates parent directories as needed. The path is remembered for
        playback / diagnostics.
        """
        audio = self.last_audio
        if not audio:
            return
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        sampwidth = 2  # int16
        with wave.open(str(dest), "wb") as wf:
            wf.setnchannels(self.config.channels)
            wf.setsampwidth(sampwidth)
            wf.setframerate(self._actual_sample_rate)
            wf.writeframes(audio)
        self._last_recording_path = dest
        self._last_audio = audio

    def play_audio(self, audio: bytes, sample_rate: int) -> None:
        """Play raw PCM *audio* (int16) off the calling thread.

        Playback runs in a daemon thread so it never blocks the GUI. Best-effort;
        failures are logged and swallowed.  If an output device is selected in
        ``AudioConfig``, playback routes to that device instead of the system
        default.
        """
        if not audio:
            return
        try:
            import numpy as np
            import sounddevice as sd

            arr = np.frombuffer(audio, dtype=np.int16)
        except Exception:
            logger.debug("playback input conversion failed", exc_info=True)
            return

        out_device = self._output_device_index
        if out_device is None:
            out_device = self.config.output_device_index
        if out_device is not None and out_device >= 0:
            try:
                out_info = sd.query_devices(out_device)
                if out_info.get("max_output_channels", 0) <= 0:
                    out_device = None
            except Exception:
                logger.debug("output device validation failed", exc_info=True)
                out_device = None

        def _play() -> None:
            try:
                if out_device is not None:
                    sd.play(arr, sample_rate, device=out_device)
                else:
                    sd.play(arr, sample_rate)
                sd.wait()
            except Exception:
                logger.debug("sounddevice playback failed", exc_info=True)

        threading.Thread(target=_play, name="voice-playback", daemon=True).start()

    def play_last(self) -> None:
        """Replay the most recently retained recording (no-op if none)."""
        audio = self.last_audio
        if not audio:
            return
        self.play_audio(audio, self._actual_sample_rate or self.config.sample_rate)

    @property
    def selected_output_device(self) -> int | None:
        """The PortAudio index of the currently active output device (or None)."""
        return self._output_device_index


def create_audio(
    config: AudioConfig | None = None,
    preferred: str = "stub",
) -> AudioManager:
    """Return the best available AudioManager.

    ``preferred="sounddevice"`` selects :class:`SoundDeviceAudioManager` when
    ``sounddevice`` is importable and available, falling back to
    :class:`StubAudioManager` otherwise. The default (``preferred="stub"``)
    always returns the stub, preserving the Phase 1 contract that the
    application starts safely without a real backend.
    """
    log = logging.getLogger("voice")
    log.info("AudioManager requested (preferred=%s)", preferred)
    if preferred == "sounddevice" and _sounddevice_available():
        try:
            am = SoundDeviceAudioManager(config=config)
            if am.is_available():
                return am
            log.info("sounddevice backend unavailable (no input device), using stub AudioManager")
        except Exception:
            log.info("SoundDeviceAudioManager init failed, using stub AudioManager")
    return StubAudioManager(config=config)
