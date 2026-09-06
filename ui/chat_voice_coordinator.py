"""Chat + Voice coordinator for AppShell (Phase 7).

Fixes two problems from the audit (docs/current_status.md — Phase 7):
1. ChatWidget in AppShell was not connected to the Assistant (send_requested
   without a consumer — messages ended up in the hidden MainWindow chat) nor
   to the VoiceManager (REC button dead).
2. There was no explicit Automatic Listening (continuous conversation) mode.

The integration follows the same pattern used by MainWindow (worker → Qt
signal (queued) → GUI-thread slot → only then EventBus publish), so all Qt
calls stay on the GUI thread.

Voice state machine (specification §4):
    IDLE → LISTENING → PROCESSING → SPEAKING → LISTENING → ... (loop)
    any state → STOPPING → IDLE (user exit)

Echo protection: while SPEAKING the microphone is NOT opened (half-duplex
approach — openwakeword/AAC is not available; documented in
docs/current_status.md).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class _GenerationWorker(QThread):
    """Background LLM generation — same pattern as the MainWindow worker."""

    token_emitted = Signal(str)
    generation_finished = Signal(str)
    generation_cancelled = Signal()
    generation_failed = Signal(str)

    def __init__(self, assistant: Any, text: str, cancel_event, images: list | None = None) -> None:
        super().__init__()
        self._assistant = assistant
        self._text = text
        self._cancel_event = cancel_event
        self._images = images

    def run(self) -> None:
        try:
            from PySide6.QtCore import QCoreApplication

            def on_token(token: str) -> None:
                if not self.isInterruptionRequested():
                    self.token_emitted.emit(token)

            def should_cancel() -> bool:
                QCoreApplication.processEvents()
                return bool(self._cancel_event and self._cancel_event.is_set())

            response = self._assistant.process_message(
                self._text,
                cancel_event=self._cancel_event,
                token_callback=on_token,
                should_cancel=should_cancel,
                images=self._images,
            )
            if self.isInterruptionRequested():
                self.generation_cancelled.emit()
                return
            self.generation_finished.emit(response)
        except Exception as exc:
            logger.exception("Generation worker failed")
            try:
                self.generation_failed.emit(str(exc))
            except RuntimeError:
                pass  # worker already destroyed


class ChatVoiceCoordinator(QWidget):
    """Connects ChatWidget, Assistant, and VoiceManager within AppShell.

    Public API (call only from the GUI thread):
    - wire()  — connect signals and events (idempotent)
    - unwire() — disconnect before closing the window
    - set_automatic_listening(enabled: bool) — enter/exit continuous mode
    - is_automatic_listening — current state
    """

    def __init__(
        self,
        chat: Any,
        assistant: Any,
        voice_manager: Any,
        event_bus: Any,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._chat = chat
        self._assistant = assistant
        self._voice = voice_manager
        self._event_bus = event_bus

        self._wired = False
        self._generation_active = False
        self._generation_worker: _GenerationWorker | None = None
        self._cancel_event: Any = None
        self._sub_ids: list[tuple[str, str]] = []
        self._responded = False  # response shown (start/finish streaming)

        # Automatic Listening state machine (specification §4)
        self._auto_listen = False           # user mode (persistent) while ON
        self._auto_cycle_active = False     # current cycle (listen→…→listen)
        self._stopping = False             # STOPPING state — blocks re-scheduling

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def wire(self) -> None:
        """Connects ChatWidget signals + EventBus events (idempotent)."""
        if self._wired:
            return
        self._wired = True

        # Chat input → generation
        self._chat.send_requested.connect(self._on_send)
        if hasattr(self._chat, "send_with_images_requested"):
            self._chat.send_with_images_requested.connect(self._on_send_with_images)
        self._chat.stop_generation.connect(self._on_stop_generation)
        self._chat.voice_requested.connect(self._on_voice_input)
        self._chat.play_requested.connect(self._on_play_recording)
        self._chat.automatic_listening_toggled.connect(self.set_automatic_listening)
        self._sync_vision_availability()

        if self._event_bus is None:
            return
        handlers = [
            ("VOICE_INPUT_START", self._on_voice_start),
            ("VOICE_INPUT_END", self._on_voice_end),
            ("VOICE_TRANSCRIPT", self._on_voice_transcript),
            ("VOICE_PLAY_START", self._on_speak_start),
            ("VOICE_PLAY_DONE", self._on_speak_done),
            ("VOICE_ERROR", self._on_voice_error),
            ("WAKE_WORD_DETECTED", self._on_wake_word),
            ("MODEL_LOADED", self._on_model_event),
            ("MODEL_UNLOADED", self._on_model_event),
            ("API_ENGINE_ACTIVE", self._on_api_engine_active),
        ]
        for event_type, handler in handlers:
            try:
                sub_id = self._event_bus.subscribe(event_type, handler)
                self._sub_ids.append((event_type, sub_id))
            except Exception:
                logger.debug("subscribe %s failed", event_type, exc_info=True)

    def unwire(self) -> None:
        """Disconnects everything — safe to call multiple times."""
        if self._event_bus is not None:
            for event_type, sub_id in self._sub_ids:
                try:
                    self._event_bus.unsubscribe(event_type, sub_id)
                except Exception:
                    pass
            self._sub_ids.clear()
        self._wired = False

    # ------------------------------------------------------------------
    # Automatic Listening (specification §2/§4/§5)
    # ------------------------------------------------------------------

    @property
    def is_automatic_listening(self) -> bool:
        return self._auto_listen

    def set_automatic_listening(self, enabled: bool) -> bool:
        """Enable/disable continuous conversation mode (idempotent).

        ON  → immediately starts listening (if the state is safe).
        OFF → stops the current cycle; no new automatic sessions.
        """
        if enabled:
            if self._auto_listen:
                return True  # idempotent (§4)
            self._auto_listen = True
            self._stopping = False
            logger.info("Automatic Listening: ON")
            self._chat.set_automatic_listening_ui(True)
            self._begin_auto_cycle()
            return True

        # OFF
        if not self._auto_listen:
            return False
        self._auto_listen = False
        self._stopping = True  # blocks re-scheduling (§4)
        self._chat.set_automatic_listening_ui(False)
        # Stop the active session via the official API (defined behavior)
        if self._voice is not None:
            try:
                if self._voice.is_recording:
                    # Finish the recording normally — we don't throw away
                    # the user's speech
                    self._voice.stop_and_transcribe()
                else:
                    self._voice.stop_listening()
            except Exception:
                logger.exception("Automatic Listening OFF — voice stop failed")
        logger.info("Automatic Listening: OFF")
        # Stopping finished — a new ON may run cycles
        self._stopping = False
        return False

    def _begin_auto_cycle(self) -> None:
        """Starts a new listening cycle (only if the mode is active and the state is safe)."""
        if not self._auto_listen or self._stopping:
            return
        if self._voice is None:
            return
        state = self._voice.state.value
        # Safe to start only from IDLE/ERROR (no re-entrancy)
        if state in ("idle", "error"):
            try:
                ok = self._voice.begin_auto_recording()
                if ok:
                    self._auto_cycle_active = True
            except Exception:
                logger.exception("Auto-listen begin_auto_recording failed")
                self._on_auto_error("begin_auto_recording failed")
        else:
            # PROCESSING/SPEAKING — the cycle continues when they finish
            # (hook in _on_speak_done / _on_voice_end).
            self._auto_cycle_active = True

    # ------------------------------------------------------------------
    # Chat pipeline
    # ------------------------------------------------------------------

    def _on_send(self, text: str) -> None:
        if self._generation_active:
            logger.info("Generation already active — ignoring send")
            return
        self._start_generation(text)

    def _on_send_with_images(self, text: str, images: list) -> None:
        """Multimodal send — images are forwarded to Assistant.process_message."""
        if self._generation_active:
            logger.info("Generation already active — ignoring send")
            return
        self._start_generation(text, images=images)

    def _on_model_event(self, event_type: str, data: dict) -> None:
        """Model changed — refresh the Vision button availability."""
        self._sync_vision_availability()

    def _on_api_engine_active(self, event_type: str, data: dict) -> None:
        """An agent turn is served by the online API — show the indicator
        until the generation finishes."""
        self._set_online_indicator(True)

    def _set_online_indicator(self, active: bool) -> None:
        if self._chat is not None and hasattr(self._chat, "set_online_active"):
            try:
                self._chat.set_online_active(active)
            except Exception:
                logger.debug("set_online_active failed", exc_info=True)

    def _sync_vision_availability(self) -> None:
        """Enable Vision only when the active model supports it."""
        if self._chat is None or not hasattr(self._chat, "set_vision_available"):
            return
        engine = getattr(self._assistant, "_engine", None)
        available = bool(getattr(engine, "supports_vision", False)) if engine else False
        try:
            self._chat.set_vision_available(available)
        except Exception:
            logger.debug("set_vision_available failed", exc_info=True)

    def _on_stop_generation(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _start_generation(self, text: str, images: list | None = None) -> None:
        """Streaming generation in the background — same pattern as MainWindow."""
        if self._assistant is None:
            return
        import threading

        self._generation_active = True
        self._responded = False
        self._cancel_event = threading.Event()
        if hasattr(self._assistant, "_cancel_event"):
            self._assistant._cancel_event = self._cancel_event
        try:
            worker = _GenerationWorker(self._assistant, text, self._cancel_event, images)
            self._generation_worker = worker
            worker.token_emitted.connect(self._on_token)
            worker.generation_finished.connect(self._on_generation_finished)
            worker.generation_cancelled.connect(self._on_generation_cancelled)
            worker.generation_failed.connect(self._on_generation_failed)
            worker.finished.connect(worker.deleteLater)
            worker.start()
        except Exception:
            logger.exception("Generation start failed")
            self._generation_active = False
            self._generation_worker = None

    def _on_token(self, token: str) -> None:
        if not self._chat.is_streaming():
            self._chat.start_streaming()
        if self._event_bus is not None:
            self._event_bus.publish("GENERATION_TOKEN", data={"token": token})

    def _on_generation_finished(self, response: str) -> None:
        self._generation_active = False
        self._generation_worker = None
        self._set_online_indicator(False)
        cid = f"conv-{datetime.now(UTC).isoformat()}"
        model_name = (
            self._assistant._engine.model_name
            if self._assistant is not None and getattr(self._assistant, "_engine", None)
            else "stub"
        )
        if self._event_bus is not None:
            self._event_bus.publish(
                "GENERATION_COMPLETED",
                data={"tokens_used": len(response), "response_length": len(response)},
            )
            self._event_bus.publish(
                "AI_RESPONSE_RECEIVED",
                data={"text": response, "conversation_id": cid, "model": model_name},
            )
        self._maybe_speak(response)

    def _on_generation_cancelled(self) -> None:
        self._generation_active = False
        self._generation_worker = None
        self._set_online_indicator(False)
        if self._event_bus is not None:
            self._event_bus.publish("GENERATION_CANCELLED", data={"tokens_generated": 0})
        self._resume_after_response()

    def _on_generation_failed(self, error: str) -> None:
        self._generation_active = False
        self._generation_worker = None
        self._set_online_indicator(False)
        if self._event_bus is not None:
            self._event_bus.publish("GENERATION_FAILED", data={"error": error})
        self._resume_after_response()

    def _maybe_speak(self, text: str) -> None:
        """TTS if voice is enabled — same condition as MainWindow."""
        if (
            self._voice is not None
            and self._event_bus is not None
        ):
            try:
                import json
                from pathlib import Path

                cfg_path = Path.home() / "AppData" / "Local" / "OfflineAI" / "config" / "settings.json"
                if cfg_path.exists():
                    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
                    if cfg.get("voice", {}).get("enabled", True):
                        self._voice.speak(text)
                        return
            except Exception:
                logger.debug("voice config read failed — skipping TTS", exc_info=True)
        self._resume_after_response()

    # ------------------------------------------------------------------
    # Voice integration
    # ------------------------------------------------------------------

    def _on_voice_input(self) -> None:
        """REC button — manual push-to-talk (different from auto-listen)."""
        if self._voice is None:
            return
        self._voice.handle_mic_click()
        self._sync_voice_ui()

    def _on_play_recording(self) -> None:
        if self._voice is not None:
            self._voice.play_last_recording()

    def _sync_voice_ui(self) -> None:
        if self._voice is not None:
            self._chat.set_voice_state(self._voice.state.value)
            self._chat.set_play_available(bool(self._voice.last_recording_path))

    # --- EventBus handlers (GUI thread — voice manager marshals) ---------

    def _on_voice_start(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("recording")
        self._chat.set_play_available(bool(self._voice.last_recording_path if self._voice else False))

    def _on_voice_end(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("idle")
        if self._voice is not None:
            self._chat.set_play_available(bool(self._voice.last_recording_path))

    def _on_voice_transcript(self, event_type: str, data: dict) -> None:
        """VOICE_TRANSCRIPT → user message → generation (auto-listen loop)."""
        if self._generation_active:
            logger.info("Transcript while generation active — deferring")
            return
        text = str(data.get("text", "")).strip()
        if not text:
            # Empty transcript — don't generate; continue the cycle if auto is ON
            self._resume_after_response()
            return
        self._chat.add_message("user", text)
        self._start_generation(text)

    def _on_speak_start(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("speaking")

    def _on_speak_done(self, event_type: str, data: dict) -> None:
        """TTS finished → back to listening (§2 step 9) if auto mode is ON."""
        self._chat.set_voice_state("idle")
        if self._voice is not None:
            self._chat.set_play_available(bool(self._voice.last_recording_path))
        self._resume_after_response()

    def _resume_after_response(self) -> None:
        """After response/TTS → new listening cycle (auto mode)."""
        if self._auto_listen and not self._stopping:
            self._begin_auto_cycle()
        else:
            self._auto_cycle_active = False

    def _on_voice_error(self, event_type: str, data: dict) -> None:
        message = str(data.get("error", "voice error"))
        self._chat.set_voice_state("error", message)
        self._on_auto_error(message)

    def _on_auto_error(self, message: str) -> None:
        """Unrecoverable error → the mode must end in a consistent OFF state (§12)."""
        if self._auto_listen:
            logger.error("Automatic Listening error → disabling: %s", message)
            self.set_automatic_listening(False)

    def _on_wake_word(self, event_type: str, data: dict) -> None:
        """Wake word trigger → one voice interaction (§6).

        Wake word and auto-listen are INDEPENDENT modes; the wake trigger does
        not enable auto mode and does not start the microphone if an auto
        cycle is already active.
        """
        if self._voice is None:
            return
        # If auto-listen is already active — the wake trigger is redundant
        if self._auto_cycle_active and self._voice.state.value in ("recording",):
            return
        state = self._voice.state.value
        if state in ("idle", "error"):
            self._voice.handle_mic_click()
            self._sync_voice_ui()

    # ------------------------------------------------------------------
    # Teardown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Clean interruption of everything (call from closeEvent)."""
        self.set_automatic_listening(False)
        if self._generation_worker is not None and self._generation_worker.isRunning():
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._generation_worker.wait(2000)
        self._generation_worker = None
        self.unwire()
