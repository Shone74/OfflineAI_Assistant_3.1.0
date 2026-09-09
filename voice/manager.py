"""Voice manager — orchestrates STT, TTS, and wake-word detection.

In stub mode (the default: no native backends installed) the manager emits
the standard EventBus events so the GUI can reflect voice state, and
``StubSTT.set_transcript`` provides a canned transcript for testing / demos.

Real microphone capture is delegated to an :class:`~voice.audio.AudioManager`;
the default stub reports capture as unavailable so no empty or fake audio is
ever forwarded to the STT provider.

The lifecycle uses the Phase 2C REC/STOP/PROCESSING model: ``handle_mic_click``
dispatches to ``begin_recording`` (IDLE -> RECORDING) and ``stop_and_transcribe``
(RECORDING -> PROCESSING -> IDLE), with a ``VOICE_INPUT_START`` event at the
start and ``VOICE_TRANSCRIPT`` / ``VOICE_INPUT_END`` events when transcription
finishes. Tests inject a synchronous ``transcription_runner`` so results are
delivered inline without a QThread.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from core.event_bus import EventBus
from core.logger import get_logger
from core.paths import DATA_DIR, get_model_category_dir
from voice.audio import AudioCaptureError, AudioConfig, AudioManager, create_audio
from voice.base import STTProvider, TTSProvider, WakeWordProvider
from voice.stt import STTModelError, _whisper_available, create_stt
from voice.tts import create_tts
from voice.wake_word import create_wake_word

logger = get_logger("voice.manager")

# Events published on the EventBus:
#   VOICE_INPUT_START, VOICE_INPUT_END, VOICE_TRANSCRIPT
#   VOICE_PLAY_START, VOICE_PLAY_DONE, VOICE_ERROR, WAKE_WORD_DETECTED

_DEFAULT_SAMPLE_RATE = 16000

# Local, user-writable directory for the most-recent captured WAV (offline).
RECORDINGS_DIR: Path = DATA_DIR / "voice_captures"

# Callback type for the (injectable) transcription worker.
TranscriptionCallback = Callable[[str], None]
TranscriptionErrorHandler = Callable[[str], None]


class VoiceState(str, Enum):
    """High-level VoiceManager lifecycle states (Phase 2C REC/STOP lifecycle).

    * ``IDLE``       - ready; button shows ``REC``.
    * ``RECORDING``  - microphone feeding the buffer; button shows ``STOP``.
    * ``PROCESSING`` - audio finalised, STT running; button shows ``PROCESSING...``.
    * ``SPEAKING``   - TTS playing; button shows ``SPEAKING``; mic input blocked.
    * ``ERROR``      - recoverable failure; button returns to ``REC``.
    """

    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class _VoiceTranscribeWorker(QThread):
    """Background worker that runs STT off the Qt GUI (main) thread.

    Mirrors the project's ``ModelLoadWorker(QThread)`` convention: results and
    errors are emitted as Qt signals (queued to the main thread), so Qt widgets
    are never touched from a worker thread. Only one worker is live at a time.
    """

    transcript_ready = Signal(str)
    error = Signal(str)

    def __init__(self, stt: STTProvider, audio: bytes, sample_rate: int, generation: int = 0) -> None:
        super().__init__()
        self._stt = stt
        self._audio = audio
        self._sample_rate = sample_rate
        self._generation = generation

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            text = self._stt.transcribe(self._audio, sample_rate=self._sample_rate)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        if self.isInterruptionRequested():
            return
        self.transcript_ready.emit(text or "")


class _VoiceSpeakWorker(QThread):
    """Background worker that runs TTS off the Qt GUI (main) thread.

    ``pyttsx3.runAndWait`` is a blocking call — executing it on the main thread
    would freeze the UI for the entire duration of speech synthesis.  This worker
    runs the provider's ``speak`` method in a separate QThread and communicates
    completion/failure back to the main thread via Qt signals (queued connection
    by default for cross-thread delivery).

    Mirrors the pattern established by ``_VoiceTranscribeWorker``.
    """

    finished = Signal()
    error = Signal(str)

    def __init__(self, tts: TTSProvider, text: str, generation: int = 0) -> None:
        super().__init__()
        self._tts = tts
        self._text = text
        self._generation = generation

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            self._tts.speak(self._text)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        if self.isInterruptionRequested():
            return
        self.finished.emit()


class _PersistingSTTProxy:
    """STT provider wrapper that persists the WAV before transcribing.

    M6: the WAV write (proportional to the recording length) executes on
    the transcription worker thread right before STT, instead of on the
    GUI thread.  The wrapped provider's STT behaviour is unchanged; a
    persist failure never blocks transcription (it is logged and
    skipped, exactly as before).
    """

    __slots__ = ("_manager", "_stt")

    def __init__(self, manager: VoiceManager, stt: STTProvider) -> None:
        self._manager = manager
        self._stt = stt

    def transcribe(self, pcm: bytes, sample_rate: int = 16000, **kwargs) -> str:
        try:
            self._manager._persist_recording(pcm, sample_rate)
        except Exception:
            logger.debug("failed to persist last recording", exc_info=True)
        return self._stt.transcribe(pcm, sample_rate=sample_rate, **kwargs)

    def __getattr__(self, name):  # transparent pass-through for other attrs
        return getattr(self._stt, name)


class VoiceManager:
    """Coordinates the voice subsystems and the EventBus voice events."""

    def __init__(
        self,
        event_bus: EventBus,
        *,
        stt: STTProvider | None = None,
        tts: TTSProvider | None = None,
        wake: WakeWordProvider | None = None,
        record_fn: Callable[[], tuple[bytes, int]] | None = None,
        audio_manager: AudioManager | None = None,
        config: Any = None,
        transcription_runner: Callable[
            [STTProvider, bytes, int, TranscriptionCallback, TranscriptionErrorHandler],
            None,
        ]
        | None = None,
    ) -> None:
        from core.config_manager import ConfigManager

        self._event_bus = event_bus
        self._stt: STTProvider = stt or create_stt()
        self._tts: TTSProvider = tts or create_tts()
        self._config: ConfigManager | None = config if isinstance(config, ConfigManager) else None
        # wake word is created AFTER _config (reads voice.wake_word from config)
        self._wake: WakeWordProvider = wake or self._create_wake_word_from_config()
        self._record_fn = record_fn
        self._audio: AudioManager = audio_manager or create_audio()
        self._config_sub_id: str | None = None
        self._voice_enabled_sub_id: str | None = None
        self._pending_stt_config: dict[str, Any] | None = None
        self._pending_tts_config: dict[str, Any] | None = None
        self._pending_startup_errors: list[dict[str, Any]] = []
        self._listening = False
        self._initialized = False
        # --- Wake word refractory (prevents a burst of triggers from one phrase) ---
        self._wake_cooldown_active = False
        # --- Echo protection: wake word disabled during TTS (§8) ---
        self._wake_suppressed_for_tts = False
        # --- Automatic Listening session state (Phase 7) ---
        self._auto_session = False
        self._auto_watchdog = None
        self._auto_buffer_marker = 0
        self._auto_last_change_ms = 0
        self._auto_silence_ms = 3000
        # --- Phase 2C REC/STOP/PROCESSING lifecycle ---
        self._state: VoiceState = VoiceState.IDLE
        self._worker: _VoiceTranscribeWorker | None = None
        self._speak_worker: _VoiceSpeakWorker | None = None
        self._finished_workers: list[_VoiceSpeakWorker] = []
        self._transcription_runner = transcription_runner
        # --- Worker lifecycle generation counters ---
        # Each new transcription or TTS operation increments its counter,
        # tagging the worker with a unique generation.  Completion/error
        # callbacks check their captured generation against the live counter
        # before mutating state, so stale queued callbacks from superseded
        # workers are silently discarded.  stop() also bumps both counters to
        # invalidate any in-flight workers.
        self._stt_generation: int = 0
        self._tts_generation: int = 0
        if self._config is not None and tts is None:
            self._apply_tts_config(self._read_tts_config_from_config())
        self._subscribe_to_config()
        self._voice_enabled_sub_id = self._event_bus.subscribe("VOICE_ENABLED_CHANGED", self._on_voice_enabled_changed)

    def _subscribe_to_config(self) -> None:
        """Subscribe to CONFIG_CHANGED events for audio reconfiguration."""
        if self._config is not None:
            self._config_sub_id = self._event_bus.subscribe(
                "CONFIG_CHANGED", self._on_config_changed
            )

    def _create_wake_word_from_config(self) -> WakeWordProvider:
        """Create the wake-word provider from configuration.

        Config schema (voice.wake_word):
            enabled  — bool (default True; used by application bootstrap)
            provider — "openwakeword" | "stub" (default "openwakeword")
            hotword  — phrase (default "hey_jarvis")
            threshold — score threshold 0..1 (default 0.5)

        "hey_jarvis" is openwakeword's predefined "hey jarvis" label —
        the default phrase for this project (specification §1).
        """

        hotword = "hey_jarvis"
        provider = "openwakeword"
        threshold = 0.5
        if self._config is not None:
            try:
                wake_cfg = self._config.get("voice.wake_word", {})
                if isinstance(wake_cfg, dict):
                    hotword = wake_cfg.get("hotword", hotword)
                    provider = wake_cfg.get("provider", provider)
                    threshold = float(wake_cfg.get("threshold", threshold))
            except Exception:
                logger.debug("wake-word config read failed — using defaults")
        return create_wake_word(preferred=provider, hotword=hotword, threshold=threshold)

    def _unsubscribe_from_config(self) -> None:
        """Remove the CONFIG_CHANGED subscription (idempotent)."""
        if self._config_sub_id is not None:
            try:
                self._event_bus.unsubscribe("CONFIG_CHANGED", self._config_sub_id)
            except Exception:
                logger.debug("CONFIG_CHANGED unsubscribe failed", exc_info=True)
            self._config_sub_id = None
        self._unsubscribe_from_voice_enabled()

    def _unsubscribe_from_voice_enabled(self) -> None:
        """Remove the VOICE_ENABLED_CHANGED subscription (idempotent)."""
        if self._voice_enabled_sub_id is not None:
            try:
                self._event_bus.unsubscribe("VOICE_ENABLED_CHANGED", self._voice_enabled_sub_id)
            except Exception:
                logger.debug("VOICE_ENABLED_CHANGED unsubscribe failed", exc_info=True)
            self._voice_enabled_sub_id = None

    @property
    def stt_name(self) -> str:
        return self._stt.name

    @property
    def tts_name(self) -> str:
        return self._tts.name

    @property
    def audio_name(self) -> str:
        return self._audio.name

    @property
    def is_listening(self) -> bool:
        return self._listening

    # ------------------------------------------------------------------ #
    # Runtime audio configuration (CONFIG_CHANGED)
    # ------------------------------------------------------------------ #
    def _on_config_changed(self, event_type: str, data: dict[str, Any]) -> None:
        """Handle CONFIG_CHANGED events for audio and voice settings.

        Only ``audio.*`` and ``voice.*`` keys are processed; all other config
        changes (e.g. ``ui.theme``, ``ai.model_name``) are ignored.
        """
        if not isinstance(data, dict):
            return
        key = data.get("key", "")
        if not key:
            return
        if key.startswith("audio."):
            logger.debug("VoiceManager: CONFIG_CHANGED for %s — reconfiguring audio", key)
            self.reconfigure_audio()
        elif key.startswith("voice.stt."):
            logger.debug("VoiceManager: CONFIG_CHANGED for %s — reconfiguring STT", key)
            self._reconfigure_stt()
        elif key.startswith("voice.tts."):
            logger.debug("VoiceManager: CONFIG_CHANGED for %s — reconfiguring TTS", key)
            self._reconfigure_tts()
        elif key == "voice.language":
            logger.debug("VoiceManager: CONFIG_CHANGED for voice.language — updating STT language")
            self._update_stt_language()
        elif key == "voice.enabled":
            enabled = data.get("value", True)
            logger.debug("VoiceManager: CONFIG_CHANGED for voice.enabled — enabled=%s", enabled)
            self._event_bus.publish(
                "VOICE_ENABLED_CHANGED", {"enabled": enabled}
            )

    def _on_voice_enabled_changed(self, event_type: str, data: dict[str, Any]) -> None:
        """React to runtime VOICE_ENABLED_CHANGED — start/stop wake-word detection."""
        enabled = bool(data.get("enabled", True))
        if enabled:
            self.start_wake_word()
        else:
            self.stop_wake_word()

    def _build_audio_config_from_config(self) -> AudioConfig:
        """Build a fresh AudioConfig from the persisted ConfigManager settings."""
        if self._config is None:
            return AudioConfig()
        audio_cfg = self._config.get("audio", {})
        input_dev_name = audio_cfg.get("input_device_name", "")
        input_dev_idx = audio_cfg.get("input_device_index")
        output_dev_name = audio_cfg.get("output_device_name", "")
        output_dev_idx = audio_cfg.get("output_device_index")
        return AudioConfig(
            device=input_dev_idx if input_dev_name else None,
            input_device_name=input_dev_name,
            input_device_hostapi=audio_cfg.get("input_device_hostapi", ""),
            output_device_index=output_dev_idx if output_dev_name else None,
            output_device_name=output_dev_name,
            output_device_hostapi=audio_cfg.get("output_device_hostapi", ""),
            prefer_wasapi=audio_cfg.get("prefer_wasapi", True),
            wasapi_fallback_to_mme=audio_cfg.get("wasapi_fallback_to_mme", True),
        )

    def reconfigure_audio(self) -> bool:
        """Rebuild the AudioManager from the current ConfigManager settings.

        Safe to call at any lifecycle state:

        * If currently **RECORDING**, the active recording is stopped first
          and a ``VOICE_INPUT_END`` event is published so the UI returns to
          the idle / REC button state.
        * The old AudioManager is stopped (closing any open streams) before
          the new one is created.
        * On failure the previous AudioManager and state are restored, the
          application remains usable, and ``VOICE_ERROR`` is *not* published
          (this is a settings-level concern, not a voice-pipeline failure).

        Returns:
            ``True`` if the AudioManager was successfully rebuilt, ``False``
            otherwise (in which case the previous manager is retained).
        """
        if self._config is None:
            logger.debug("reconfigure_audio: no config reference, skipping")
            return False

        new_config = self._build_audio_config_from_config()

        # Safely interrupt an active recording so the state machine is clean.
        was_recording = self._state == VoiceState.RECORDING
        old_state = self._state
        if was_recording:
            try:
                self._audio.stop_recording()
            except Exception as exc:
                logger.warning("reconfigure_audio: stop_recording failed: %s", exc)
            self._state = VoiceState.IDLE
            self._event_bus.publish("VOICE_INPUT_END")

        old_audio = self._audio
        preferred = "sounddevice" if old_audio.name != "stub" else "stub"

        try:
            old_audio.stop()
            self._audio = create_audio(config=new_config, preferred=preferred)
            logger.info(
                "Audio reconfigured from settings (audio=%s)", self.audio_name
            )
            return True
        except Exception as exc:
            logger.error("Audio reconfiguration failed: %s", exc)
            # Roll back to the old audio manager.
            self._audio = old_audio
            self._state = old_state
            if was_recording:
                # Restore recording state so the UI is consistent.
                self._state = VoiceState.RECORDING
            logger.warning("Audio reconfiguration failed — restored previous audio config")
            return False

    # ------------------------------------------------------------------ #
    # Phase 2D — STT runtime configuration (CONFIG_CHANGED)
    # ------------------------------------------------------------------ #
    def _update_stt_language(self) -> bool:
        """Update the recognition language on the current STT provider.

        ``WhisperSTT`` stores ``_language`` as a mutable attribute that is read
        on every ``transcribe()`` call, so this is a safe hot-swap: no model
        reload, no provider recreation, no conflict with an in-flight worker.

        If the current provider lacks a ``_language`` attribute (e.g.
        ``StubSTT``) the update is a no-op.
        """
        if self._config is None:
            return False
        lang = self._config.get("voice.language", "auto")
        if hasattr(self._stt, "_language"):
            old_lang = self._stt._language
            self._stt._language = lang
            logger.info("STT language updated: %s -> %s", old_lang, lang)
            return True
        return False

    def _read_stt_config_from_config(self) -> dict[str, Any]:
        """Read the current STT configuration from the persisted ConfigManager."""
        stt_cfg = self._config.get("voice.stt", {}) if self._config else {}
        language = self._config.get("voice.language", "auto") if self._config else "auto"
        return {
            "provider": stt_cfg.get("provider", "faster-whisper"),
            "model": stt_cfg.get("model", "tiny"),
            "device": stt_cfg.get("device", "auto"),
            "language": language,
        }

    def _reconfigure_stt(self) -> bool:
        """Rebuild the STT provider from the current ConfigManager settings.

        Safe at any lifecycle state:

        * **PROCESSING** — the transcription worker holds its own reference to
          the old provider; replacing ``self._stt`` would orphan the worker's
          STT.  The change is deferred.
        * **RECORDING** — the change is deferred until the recording cycle
          completes.
        * **IDLE** — the new provider is created and swapped immediately.

        Only the *latest* requested configuration is retained; intermediate
        changes made while defered are discarded.
        """
        if self._config is None:
            logger.debug("reconfigure_stt: no config reference, skipping")
            return False

        new_config = self._read_stt_config_from_config()

        if self._state != VoiceState.IDLE:
            # Store the latest pending config (overwrites any previous pending).
            self._pending_stt_config = new_config
            logger.info(
                "STT reconfiguration deferred (state=%s) — pending config stored",
                self._state.value,
            )
            return False

        return self._apply_stt_config(new_config)

    def _apply_stt_config(self, cfg: dict[str, Any]) -> bool:
        """Create a new STT provider from *cfg* and swap it in.

        Returns ``True`` on success, ``False`` on failure (previous provider
        is retained, ``VOICE_ERROR`` is published for UI feedback).
        """
        old_stt = self._stt
        preferred = "whisper" if cfg["provider"] == "faster-whisper" else "stub"

        try:
            new_stt = create_stt(
                preferred=preferred,
                model_name=cfg["model"],
                device=cfg["device"],
                language=cfg["language"],
                stt_dir=get_model_category_dir("stt"),
            )

            # Pre-validate: if WhisperSTT, check that the model directory exists
            # so the user gets immediate feedback rather than a transcription-time error.
            if hasattr(new_stt, "_stt_dir") and hasattr(new_stt, "_model_name"):
                model_path = new_stt._stt_dir / new_stt._model_name
                if not model_path.is_dir():
                    raise STTModelError(
                        f"Whisper model '{new_stt._model_name}' not found in "
                        f"'{new_stt._stt_dir}'. Place model folders under the "
                        f"stt category dir of the configured models root."
                    )

            # New provider validated — stop old, swap in new.
            stop_old = getattr(old_stt, "stop", None)
            if callable(stop_old):
                stop_old()
            self._stt = new_stt
            logger.info(
                "STT reconfigured (provider=%s, model=%s, device=%s, language=%s)",
                cfg["provider"], cfg["model"], cfg["device"], cfg["language"],
            )
            self._event_bus.publish(
                "STT_RECONFIGURED",
                {
                    "provider": new_stt.name,
                    "model": cfg["model"],
                    "device": cfg["device"],
                    "language": cfg["language"],
                },
            )
            return True
        except Exception as exc:
            logger.error("STT reconfiguration failed: %s", exc)
            # Rollback: restore the previous working provider.
            self._stt = old_stt
            self._event_bus.publish(
                "VOICE_ERROR",
                {"error": f"STT reconfiguration failed: {exc}"},
            )
            return False

    def _check_pending_stt_config(self) -> None:
        """Apply any pending STT configuration now that state is IDLE.

        Called from ``_on_transcription_result`` and ``_publish_voice_error``
        — both of which transition the state machine back to IDLE.
        """
        if self._pending_stt_config is not None:
            cfg = self._pending_stt_config
            self._pending_stt_config = None
            logger.info(
                "Applying pending STT configuration (provider=%s, model=%s)",
                cfg.get("provider"), cfg.get("model"),
            )
            self._apply_stt_config(cfg)

    def _check_pending_tts_config(self) -> None:
        """Apply any pending TTS configuration now that state is IDLE.

        Called from ``_on_transcription_result`` and ``_publish_voice_error``
        — both of which transition the state machine back to IDLE.
        """
        if self._pending_tts_config is not None:
            cfg = self._pending_tts_config
            self._pending_tts_config = None
            logger.info(
                "Applying pending TTS configuration (provider=%s)",
                cfg.get("provider"),
            )
            self._apply_tts_config(cfg)

    def _read_tts_config_from_config(self) -> dict[str, Any]:
        """Read the current TTS configuration from the persisted ConfigManager."""
        tts_cfg = self._config.get("voice.tts", {}) if self._config else {}
        return {
            "provider": tts_cfg.get("provider", "pyttsx3"),
            "voice": tts_cfg.get("voice", ""),
            "rate": tts_cfg.get("rate", 200),
            "volume": tts_cfg.get("volume", 1.0),
        }

    def _reconfigure_tts(self) -> bool:
        """Rebuild the TTS provider from the current ConfigManager settings.

        Safe at any lifecycle state:

        * **RECORDING** / **PROCESSING** — replacing the active TTS instance
          mid-pipeline is deferred to avoid interrupting active speech.
        * **IDLE** — the new provider is created and swapped immediately.

        Only the *latest* requested configuration is retained; intermediate
        changes made while deferred are discarded.
        """
        if self._config is None:
            logger.debug("reconfigure_tts: no config reference, skipping")
            return False

        new_config = self._read_tts_config_from_config()

        if self._state != VoiceState.IDLE:
            self._pending_tts_config = new_config
            logger.info(
                "TTS reconfiguration deferred (state=%s) — pending config stored",
                self._state.value,
            )
            return False

        return self._apply_tts_config(new_config)

    def _apply_tts_config(self, cfg: dict[str, Any]) -> bool:
        """Create or reconfigure the TTS provider from *cfg*."""
        old_tts = self._tts
        preferred = cfg.get("provider", "pyttsx3")
        old_provider = old_tts.name

        try:
            if preferred != old_provider:
                self._tts = create_tts(preferred=preferred)
                logger.info(
                    "TTS provider switched: %s -> %s", old_provider, self._tts.name
                )
            if self._tts.name == "pyttsx3":
                if cfg.get("voice"):
                    setattr = getattr(self._tts, "set_voice", None)
                    if callable(setattr):
                        setattr(cfg["voice"])
                if cfg.get("rate") is not None:
                    set_rate = getattr(self._tts, "set_rate", None)
                    if callable(set_rate):
                        set_rate(int(cfg["rate"]))
                if cfg.get("volume") is not None:
                    set_volume = getattr(self._tts, "set_volume", None)
                    if callable(set_volume):
                        set_volume(float(cfg["volume"]))
            self._event_bus.publish(
                "TTS_RECONFIGURED",
                {
                    "provider": self._tts.name,
                    "voice": cfg.get("voice", ""),
                    "rate": cfg.get("rate", 200),
                    "volume": cfg.get("volume", 1.0),
                },
            )
            return True
        except Exception as exc:
            logger.error("TTS reconfiguration failed: %s", exc)
            self._tts = old_tts
            self._event_bus.publish(
                "VOICE_ERROR", {"error": f"TTS reconfiguration failed: {exc}"}
            )
            return False

    def initialize(self) -> None:
        """Prepare voice resources (idempotent)."""
        if self._initialized:
            return
        self._initialized = True
        if self._config is not None:
            self._apply_tts_startup_config(self._read_tts_config_from_config())
            stt_cfg = self._read_stt_config_from_config()
            self._validate_stt_startup(stt_cfg)
        logger.info("VoiceManager initialized (STT=%s, TTS=%s)", self.stt_name, self.tts_name)

    def flush_pending_startup_errors(self) -> None:
        """Publish any VOICE_ERROR events buffered during initialize().

        Must be called AFTER the MainWindow (which subscribes to VOICE_ERROR)
        has been constructed, so that UI components actually receive the error.
        """
        while self._pending_startup_errors:
            err = self._pending_startup_errors.pop(0)
            try:
                self._event_bus.publish("VOICE_ERROR", err)
            except Exception:
                logger.debug("VOICE_ERROR publish failed", exc_info=True)

    def _apply_tts_startup_config(self, cfg: dict[str, Any]) -> None:
        """Apply saved TTS settings to the existing provider at startup.

        Unlike :meth:`_apply_tts_config`, this does **not** switch providers —
        the provider was already created from the config by the caller
        (``application.py``).  It only pushes voice / rate / volume onto the
        live engine so persisted user settings take effect immediately.
        """
        set_voice = getattr(self._tts, "set_voice", None)
        if callable(set_voice) and cfg.get("voice"):
            try:
                set_voice(cfg["voice"])
            except Exception:
                logger.debug("TTS startup voice apply failed", exc_info=True)
        set_rate = getattr(self._tts, "set_rate", None)
        if callable(set_rate) and cfg.get("rate") is not None:
            try:
                set_rate(int(cfg["rate"]))
            except Exception:
                logger.debug("TTS startup rate apply failed", exc_info=True)
        set_volume = getattr(self._tts, "set_volume", None)
        if callable(set_volume) and cfg.get("volume") is not None:
            try:
                set_volume(float(cfg["volume"]))
            except Exception:
                logger.debug("TTS startup volume apply failed", exc_info=True)

    def _validate_stt_startup(self, stt_cfg: dict[str, Any]) -> None:
        """Pre-validate STT model availability at startup (consistent with runtime).

        When the config requests the Whisper backend, verify that the model
        directory exists on disk now so the user gets immediate feedback
        rather than discovering the error at first transcription. Falls back
        to ``STTModelError``-style behavior (error published) without blocking.
        """
        if stt_cfg["provider"] != "faster-whisper" or not _whisper_available():
            return
        stt_dir = get_model_category_dir("stt")
        model_name = stt_cfg["model"]
        model_path = stt_dir / model_name
        if not model_path.is_dir():
            try:
                self._pending_startup_errors.append(
                    {
                        "error": (
                            f"Whisper model '{model_name}' not found in the "
                            f"local model directory '{stt_dir}'. The application "
                            "runs fully offline; faster-whisper will not download "
                            "a model automatically."
                        )
                    }
                )
                logger.warning(
                    "STT model '%s' not found at startup — transcribe will raise STTModelError",
                    model_name,
                )
            except Exception:
                logger.debug("STT startup validation error publish failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # Phase 2C REC/STOP/PROCESSING lifecycle
    # ------------------------------------------------------------------ #
    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def is_processing(self) -> bool:
        return self._state == VoiceState.PROCESSING

    @property
    def is_recording(self) -> bool:
        # Phase 2C lifecycle state (distinct from the audio backend's own flag).
        return self._state == VoiceState.RECORDING

    @property
    def last_recording_path(self) -> Path | None:
        """Filesystem path of the most recent captured WAV, if persisted."""
        return self._audio.last_recording_path

    def handle_mic_click(self) -> bool:
        """Toggle the microphone button (single entry point for the UI).

        Dispatches on the current lifecycle state so invalid actions are
        rejected at the source:

        * ``IDLE``      -> start recording
        * ``RECORDING`` -> stop recording and transcribe
        * ``ERROR``     -> clear error and return to IDLE
        * ``PROCESSING`` -> ignored (no re-entrancy)
        * ``SPEAKING``  -> ignored (TTS playback active, mic blocked)
        """
        if self._state == VoiceState.IDLE:
            return self.begin_recording()
        if self._state == VoiceState.RECORDING:
            return self.stop_and_transcribe()
        if self._state == VoiceState.ERROR:
            self._state = VoiceState.IDLE
            return self.begin_recording()
        return False

    def begin_recording(self) -> bool:
        """Transition IDLE -> RECORDING and start the microphone stream.

        Returns ``True`` when recording started, ``False`` when the action was
        rejected or the microphone could not be opened (in which case a
        ``VOICE_ERROR`` event is published and state returns to ``IDLE``).
        """
        if self._state != VoiceState.IDLE:
            return False
        self.stop_wake_word()
        if not self._audio.is_available():
            self._publish_voice_error("microphone unavailable")
            self._restart_wake_word_if_enabled()
            return False
        try:
            self._audio.start_recording()
        except AudioCaptureError as exc:
            self._publish_voice_error(str(exc))
            self._restart_wake_word_if_enabled()
            return False
        except Exception as exc:
            self._publish_voice_error(f"failed to start recording: {exc}")
            self._restart_wake_word_if_enabled()
            return False
        self._state = VoiceState.RECORDING
        self._listening = True
        self._event_bus.publish("VOICE_INPUT_START")
        logger.info("Voice recording started")
        return True

    def stop_and_transcribe(self) -> bool:
        """Transition RECORDING -> PROCESSING, finalise audio, then run STT.

        Returns ``False`` (and publishes ``VOICE_ERROR``) if stopping the
        stream fails. The transcript is delivered asynchronously via
        ``VOICE_TRANSCRIPT`` on the main thread once the worker finishes.

        M6: the WAV persistence (a disk write proportional to the
        recording length) runs INSIDE the transcription worker thread —
        it is attached to the STT provider proxy, so whichever runner
        executes the transcription (default QThread worker or an
        injected test runner) performs the persist on its own thread,
        never on the GUI thread.
        """
        if self._state != VoiceState.RECORDING:
            return False
        self._stop_auto_watchdog()
        self._state = VoiceState.PROCESSING
        self._listening = False
        try:
            pcm, sr = self._audio.stop_recording()
        except AudioCaptureError as exc:
            self._publish_voice_error(f"failed to stop recording: {exc}")
            return False
        except Exception as exc:
            self._publish_voice_error(f"failed to stop recording: {exc}")
            return False
        stt = _PersistingSTTProxy(self, self._stt)
        self._run_transcription(
            pcm, sr,
            self._on_transcription_result, self._on_transcription_error,
            stt=stt,
        )
        return True

    # ------------------------------------------------------------------ #
    # Automatic Listening (Phase 7) — auto sessions with silence watchdog
    # ------------------------------------------------------------------ #

    def begin_auto_recording(self, silence_timeout_s: float = 3.0) -> bool:
        """Start an AUTOMATIC recording session (Automatic Listening).

        Difference from a manual session: it is started from VoiceManager (not
        by a click) and carries a silence watchdog — when the user stops
        speaking (no new audio chunk with energy ~silence), the session
        finalises itself as if the user had clicked STOP (stop_and_transcribe).

        The watchdog is energy-based on buffer growth: while the buffer grows,
        the user is probably speaking; the watchdog checks every 500 ms — if
        the total buffer is unchanged for longer than silence_timeout_s, the
        end of the utterance is assumed.
        (Full RMS VAD detection is a future upgrade — see docs/current_status.)
        """
        started = self.begin_recording()
        if not started:
            return False
        self._auto_session = True
        self._auto_buffer_marker = 0
        try:
            from PySide6.QtCore import QTimer

            self._auto_watchdog = QTimer(self)
            self._auto_watchdog.setInterval(500)
            self._auto_watchdog.timeout.connect(self._on_auto_watchdog_tick)
            self._auto_watchdog.start()
            self._auto_silence_ms = int(silence_timeout_s * 1000)
            self._auto_last_change_ms = 0
            logger.info("Auto listening session started (silence timeout %.1fs)", silence_timeout_s)
        except Exception:
            logger.debug("QTimer unavailable — auto watchdog disabled (headless test?)")
            self._auto_watchdog = None
        return True

    def _stop_auto_watchdog(self) -> None:
        watchdog = getattr(self, "_auto_watchdog", None)
        if watchdog is not None:
            try:
                watchdog.stop()
                watchdog.deleteLater()
            except Exception:
                pass
        self._auto_watchdog = None
        self._auto_session = False

    def _on_auto_watchdog_tick(self) -> None:
        """Watchdog tick: detect silence via audio buffer growth."""
        if self._state != VoiceState.RECORDING or not getattr(self, "_auto_session", False):
            self._stop_auto_watchdog()
            return
        try:
            marker = self._audio.buffer_size()
        except Exception:
            marker = getattr(self, "_auto_buffer_marker", 0)
        if marker != getattr(self, "_auto_buffer_marker", -1):
            # Buffer is growing — the user is speaking (or noise); reset the silence timer.
            self._auto_buffer_marker = marker
            self._auto_last_change_ms = 0
            return
        self._auto_last_change_ms += 500
        if self._auto_last_change_ms >= self._auto_silence_ms:
            logger.info("Auto listening: silence detected — finalizing utterance")
            self._stop_auto_watchdog()
            self.stop_and_transcribe()

    def _persist_recording(self, pcm: bytes, sample_rate: int) -> None:
        """Store the latest capture as a local WAV for playback/diagnostics."""
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        path = RECORDINGS_DIR / "last_recording.wav"
        self._audio.save_last_recording(path)

    def _run_transcription(
        self,
        pcm: bytes,
        sample_rate: int,
        on_done: TranscriptionCallback,
        on_error: TranscriptionErrorHandler,
        stt: STTProvider | None = None,
    ) -> None:
        """Dispatch ``pcm`` to the STT provider via the configured runner.

        The default runner spawns a :class:`_VoiceTranscribeWorker` (QThread).
        Tests inject a synchronous runner so results can be asserted without a
        Qt event loop.  *stt* overrides the provider for this dispatch (used
        to attach the persist proxy without rebinding manager state).
        """
        provider = stt if stt is not None else self._stt
        runner = self._transcription_runner or self._default_transcribe_worker
        runner(provider, pcm, sample_rate, on_done, on_error)

    def _default_transcribe_worker(
        self,
        stt: STTProvider,
        audio: bytes,
        sample_rate: int,
        on_done: TranscriptionCallback,
        on_error: TranscriptionErrorHandler,
    ) -> None:
        """Qt-worker default: run STT off the GUI thread, queue results back."""
        self._stt_generation += 1
        generation = self._stt_generation
        worker = _VoiceTranscribeWorker(stt, audio, sample_rate, generation)
        worker.transcript_ready.connect(lambda t: self._on_transcription_result(t, generation))
        worker.error.connect(lambda m: self._on_transcription_error(m, generation))
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def _on_transcription_result(self, text: str, generation: int = 0) -> None:
        """Main-thread slot: deliver the transcript and end the voice session."""
        if generation != self._stt_generation:
            logger.debug(
                "Discarding stale transcription result (generation %d != %d)",
                generation,
                self._stt_generation,
            )
            return
        self._worker = None
        self._state = VoiceState.IDLE
        self._restart_wake_word_if_enabled()
        # Empty / whitespace transcripts are suppressed (never reach Assistant).
        if text and str(text).strip():
            self._event_bus.publish(
                "VOICE_TRANSCRIPT",
                {
                    "text": str(text),
                    "wav_path": (
                        str(self._audio.last_recording_path)
                        if self._audio.last_recording_path is not None
                        else None
                    ),
                },
            )
        self._event_bus.publish("VOICE_INPUT_END")
        self._check_pending_stt_config()
        self._check_pending_tts_config()

    def _on_transcription_error(self, message: str, generation: int = 0) -> None:
        """Main-thread slot: an STT failure surfaces as a recoverable error."""
        if generation != self._stt_generation:
            logger.debug(
                "Discarding stale transcription error (generation %d != %d)",
                generation,
                self._stt_generation,
            )
            return
        self._worker = None
        self._publish_voice_error(message)

    def _publish_voice_error(self, message: str) -> None:
        """Set state to ERROR and publish a ``VOICE_ERROR`` event.

        The runtime ``state`` now reflects the recoverable error terminal so
        the UI-visible state matches the actual runtime state.  Recovery to
        ``IDLE`` happens via ``handle_mic_click`` when the user retries.
        """
        self._state = VoiceState.ERROR
        self._worker = None
        logger.error("Voice error: %s", message)
        self._event_bus.publish("VOICE_ERROR", {"error": message})
        self._check_pending_stt_config()
        self._check_pending_tts_config()

    def play_last_recording(self) -> None:
        """Play the most recently captured WAV (delegates to the audio backend)."""
        self._audio.play_last()

    def stop_listening(self) -> None:
        self._listening = False
        self._audio.stop()
        if self._state == VoiceState.RECORDING:
            self._event_bus.publish("VOICE_INPUT_END")

    def speak(self, text: str) -> None:
        """Speak *text* aloud (TTS).

        Runs the TTS provider in a background ``_VoiceSpeakWorker`` so that
        blocking backends (e.g. ``pyttsx3.runAndWait``) do not freeze the GUI
        thread.  ``VOICE_PLAY_START`` is published immediately; ``VOICE_PLAY_DONE``
        or ``VOICE_ERROR`` is published from the main thread when the worker
        finishes.

        If a previous worker is still running, its signals are disconnected
        (so its completion does not clobber the new worker) and it is left
        to finish on its own — ``QThread.terminate()`` is never called because
        it is unsafe when the worker is executing Python code.
        """
        if self._state not in (VoiceState.IDLE, VoiceState.SPEAKING):
            logger.debug("speak() rejected — state=%s (not IDLE or SPEAKING)", self._state.value)
            return
        # Echo protection (Phase 7, specification §8): during TTS output the
        # microphone must not hear its own speech — half-duplex approach. The
        # wake word is disabled at the start of speak() and restarted on
        # completion (_on_speak_finished).
        # (TTS sound from the speakers can trigger the wake word / enter STT.)
        self._wake_suppressed_for_tts = True
        self.stop_wake_word()
        self._state = VoiceState.SPEAKING
        self._event_bus.publish("VOICE_PLAY_START", {"text": text})
        self._tts_generation += 1
        generation = self._tts_generation
        old = self._speak_worker
        if old is not None:
            # Retain the old worker to prevent premature GC while its signals
            # may still be queued.  Stale callbacks are neutralised by the
            # generation guard in _on_speak_finished / _on_speak_error — no
            # reliance on disconnect() to prevent stale delivery.
            self._finished_workers.append(old)
        self._speak_worker = _VoiceSpeakWorker(self._tts, text, generation)
        self._speak_worker.finished.connect(lambda: self._on_speak_finished(generation))
        self._speak_worker.error.connect(lambda m: self._on_speak_error(m, generation))
        self._speak_worker.finished.connect(self._speak_worker.deleteLater)
        self._speak_worker.error.connect(self._speak_worker.deleteLater)
        self._speak_worker.start()

    def _on_speak_finished(self, generation: int = 0) -> None:
        """Main-thread slot: publish VOICE_PLAY_DONE after successful TTS."""
        if generation != self._tts_generation:
            logger.debug(
                "Discarding stale TTS completion (generation %d != %d)",
                generation,
                self._tts_generation,
            )
            return
        self._speak_worker = None
        self._state = VoiceState.IDLE
        self._check_pending_tts_config()
        self._check_pending_stt_config()
        self._event_bus.publish("VOICE_PLAY_DONE", {})
        # Echo protection (Phase 7): TTS finished → restore the wake word (if it
        # was disabled due to TTS and if voice is enabled in config).
        if getattr(self, "_wake_suppressed_for_tts", False):
            self._wake_suppressed_for_tts = False
            self._restart_wake_word_if_enabled()

    def _on_speak_error(self, message: str, generation: int = 0) -> None:
        """Main-thread slot: publish VOICE_ERROR after TTS failure."""
        if generation != self._tts_generation:
            logger.debug(
                "Discarding stale TTS error (generation %d != %d)",
                generation,
                self._tts_generation,
            )
            return
        self._speak_worker = None
        self._state = VoiceState.ERROR
        logger.error("TTS failed: %s", message)
        self._check_pending_stt_config()
        self._check_pending_tts_config()
        self._event_bus.publish("VOICE_ERROR", {"error": message})
        if getattr(self, "_wake_suppressed_for_tts", False):
            self._wake_suppressed_for_tts = False
            self._restart_wake_word_if_enabled()

    def start_wake_word(self) -> None:
        """Start wake-word detection (if a usable provider is available).

        Safe to call in any environment: when only the :class:`StubWakeWord`
        provider is available (no real backend installed), ``start`` is a no-op
        and detection simply never fires.
        """
        if self._wake_cooldown_active:
            # Refractory: recent trigger — do not restart the detector
            # immediately to prevent a burst of repeated detections of the
            # same spoken phrase.
            self._wake_cooldown_active = False
        try:
            self._wake.start(self._on_wake_word_detected)
            logger.info("Wake-word detection started (%s)", self._wake.name)
        except Exception as exc:
            logger.warning("Wake-word start failed: %s", exc)

    def _on_wake_word_detected(self) -> None:
        """Publish WAKE_WORD_DETECTED — thread-safe (marshalled to owner thread).

        The detector calls this callback from its background thread. A direct
        EventBus publish would run subscribers (Qt widgets) on that thread —
        violating Qt thread-affinity. QMetaObject marshalling moves the call
        to the VoiceManager owner's (GUI) thread.
        """
        if self._wake_cooldown_active:
            logger.debug("Wake word trigger suppressed (refractory)")
            return
        self._wake_cooldown_active = True
        try:
            from PySide6.QtCore import QMetaObject, Qt

            QMetaObject.invokeMethod(
                self, "_emitWakeWordDetected", Qt.ConnectionType.QueuedConnection
            )
        except Exception:
            # Fallback: direct publish (non-Qt environment/test without QApplication)
            self._emitWakeWordDetected()

    def _emitWakeWordDetected(self) -> None:
        """GUI-thread slot: publish WAKE_WORD_DETECTED + refractory reset."""
        self._event_bus.publish("WAKE_WORD_DETECTED", {})
        # Refractory period: 2 s — one spoken phrase = one trigger.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(2000, self._reset_wake_cooldown)

    def _reset_wake_cooldown(self) -> None:
        self._wake_cooldown_active = False

    def stop_wake_word(self) -> None:
        try:
            self._wake.stop()
        except Exception:
            logger.debug("wake-word stop failed", exc_info=True)

    def _restart_wake_word_if_enabled(self) -> None:
        """Restart wake-word detection when returning to IDLE, if voice enabled.

        Called after a recording session ends (success or failure) so the
        system returns to hands-free wake-word listening rather than requiring
        a manual reclick.  Respects BOTH switches: ``voice.enabled`` (master)
        and ``voice.wake_word.enabled`` (sub-setting, Phase 7).
        When voice is disabled in config or the VoiceManager was not
        configured with a ConfigManager, this is a no-op.
        """
        if self._state != VoiceState.IDLE:
            return
        if self._config is not None:
            voice_cfg = self._config.get("voice", {})
            if not voice_cfg.get("enabled", True):
                return
            wake_cfg = voice_cfg.get("wake_word", {})
            if isinstance(wake_cfg, dict) and not wake_cfg.get("enabled", True):
                return
        self.start_wake_word()

    def stop(self) -> None:
        """Release all voice resources (idempotent, safe to call multiple times)."""
        self._pending_stt_config = None
        self._pending_tts_config = None
        self._pending_startup_errors.clear()
        self._unsubscribe_from_config()
        # The Automatic Listening watchdog must stop BEFORE the other resources (§11/§14)
        self._stop_auto_watchdog()
        self.stop_listening()
        self.stop_wake_word()
        # Invalidate all pending worker callbacks by bumping generation
        # counters.  Any already-queued signal from an in-flight worker will
        # find its generation stale and become a no-op.
        self._stt_generation += 1
        self._tts_generation += 1
        # Cancel any in-flight transcription worker spawned by the REC/STOP path.
        worker = self._worker
        self._worker = None
        if worker is not None and worker.isRunning():
            worker.requestInterruption()
            # QThread.terminate() uses TerminateThread() on Windows, which can
            # cause an access violation when the worker is blocked inside a
            # Python C-API call (e.g. threading.Event.wait, numpy, pyttsx3).
            # The generation bump above (stt_generation) neutralises any stale
            # queued _on_transcription_result/_on_transcription_error callbacks,
            # so forceful termination is unnecessary.  The worker will finish
            # on its own and deleteLater will reclaim it via the finished signal.
        # Stop any in-flight TTS speak worker spawned by speak().
        speak_worker = self._speak_worker
        self._speak_worker = None
        if speak_worker is not None and speak_worker.isRunning():
            speak_worker.requestInterruption()
            # Same rationale as above — no terminate(); the tts_generation
            # bump and _check_pending_stt/tts_config guards neutralise stale
            # callbacks.  stop_workers() on the TTS provider itself signals
            # the backend (e.g. pyttsx3.stop()) to abort cleanly.
        try:
            self._audio.stop()
        except Exception:
            logger.debug("AudioManager stop failed", exc_info=True)
        try:
            stop_stt = getattr(self._stt, "stop", None)
            if callable(stop_stt):
                stop_stt()
        except Exception:
            logger.debug("STT stop failed", exc_info=True)
        try:
            stop_tts = getattr(self._tts, "stop", None)
            if callable(stop_tts):
                stop_tts()
        except Exception:
            logger.debug("TTS stop failed", exc_info=True)
        self._state = VoiceState.IDLE
        self._listening = False
        self._initialized = False
        self._finished_workers.clear()
        logger.info("VoiceManager stopped")
