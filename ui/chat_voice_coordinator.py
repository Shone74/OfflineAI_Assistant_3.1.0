"""Chat + Voice koordinator za AppShell (Faza 7).

Rešava dva problema iz audita (docs/current_status.md — Faza 7):
1. ChatWidget u AppShell-u nije bio povezan ni na Assistant (send_requested
   bez konzumenta — poruke su završavale u skrivenom MainWindow chat-u) ni
   na VoiceManager (REC dugme mrtvo).
2. Nema eksplicitnog Automatic Listening (continuous conversation) moda.

Integracija prati isti obrazac koji koristi MainWindow (worker → Qt signal
(queued) → GUI-thread slot → tek onda EventBus publish), tako da su svi Qt
pozivi na GUI thread-u.

Voice state machine (specifikacija §4):
    IDLE → LISTENING → PROCESSING → SPEAKING → LISTENING → ... (petlja)
    bilo koje stanje → STOPPING → IDLE (korisnički izlaz)

Echo zaštita: tokom SPEAKING mikrofon se NE otvara (polu-dupleks pristup —
openwakeword/AAC nije dostupan; dokumentovano u docs/current_status.md).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QWidget

logger = logging.getLogger(__name__)


class _GenerationWorker(QThread):
    """Pozadinska LLM generacija — identičan obrazac kao MainWindow worker."""

    token_emitted = Signal(str)
    generation_finished = Signal(str)
    generation_cancelled = Signal()
    generation_failed = Signal(str)

    def __init__(self, assistant: Any, text: str, cancel_event) -> None:
        super().__init__()
        self._assistant = assistant
        self._text = text
        self._cancel_event = cancel_event

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
                pass  # worker već uništen


class ChatVoiceCoordinator(QWidget):
    """Povezuje ChatWidget, Assistant i VoiceManager unutar AppShell-a.

    Public API (pozivati samo sa GUI thread-a):
    - wire()  — poveže signale i evente (idempotentno)
    - unwire() — odveže pre zatvaranja prozora
    - set_automatic_listening(enabled: bool) — ulaz/izlaz iz continuous moda
    - is_automatic_listening — trenutno stanje
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
        self._responded = False  # odgovor prikazan (start/finish streaming)

        # Automatic Listening state machine (specifikacija §4)
        self._auto_listen = False           # korisnički mod (persistan) dok je ON
        self._auto_cycle_active = False     # trenutni ciklus (listen→…→listen)
        self._stopping = False             # STOPPING stanje — blokira re-schedule

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------

    def wire(self) -> None:
        """Poveže ChatWidget signale + EventBus evente (idempotentno)."""
        if self._wired:
            return
        self._wired = True

        # Chat input → generacija
        self._chat.send_requested.connect(self._on_send)
        self._chat.stop_generation.connect(self._on_stop_generation)
        self._chat.voice_requested.connect(self._on_voice_input)
        self._chat.play_requested.connect(self._on_play_recording)
        self._chat.automatic_listening_toggled.connect(self.set_automatic_listening)

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
        ]
        for event_type, handler in handlers:
            try:
                sub_id = self._event_bus.subscribe(event_type, handler)
                self._sub_ids.append((event_type, sub_id))
            except Exception:
                logger.debug("subscribe %s failed", event_type, exc_info=True)

    def unwire(self) -> None:
        """Odveže sve — sigurno pozvati više puta."""
        if self._event_bus is not None:
            for event_type, sub_id in self._sub_ids:
                try:
                    self._event_bus.unsubscribe(event_type, sub_id)
                except Exception:
                    pass
            self._sub_ids.clear()
        self._wired = False

    # ------------------------------------------------------------------
    # Automatic Listening (specifikacija §2/§4/§5)
    # ------------------------------------------------------------------

    @property
    def is_automatic_listening(self) -> bool:
        return self._auto_listen

    def set_automatic_listening(self, enabled: bool) -> bool:
        """Uključi/isključi continuous conversation mod (idempotentno).

        ON  → odmah započinje slušanje (ako je stanje sigurno).
        OFF → zaustavlja trenutni ciklus; nema novih automatskih sesija.
        """
        if enabled:
            if self._auto_listen:
                return True  # idempotentno (§4)
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
        self._stopping = True  # blokira ponovno zakazivanje (§4)
        self._chat.set_automatic_listening_ui(False)
        # Aktivnu sesiju prekini preko zvaničnog API-ja (definisano ponašanje)
        if self._voice is not None:
            try:
                if self._voice.is_recording:
                    # Završni snimak normalno — ne bacamo korisnikov govor
                    self._voice.stop_and_transcribe()
                else:
                    self._voice.stop_listening()
            except Exception:
                logger.exception("Automatic Listening OFF — voice stop failed")
        logger.info("Automatic Listening: OFF")
        # Zaustavljanje završeno — novi ON sme da radi cikluse
        self._stopping = False
        return False

    def _begin_auto_cycle(self) -> None:
        """Započne novi slušni ciklus (samo ako je mod aktivan i stanje safe)."""
        if not self._auto_listen or self._stopping:
            return
        if self._voice is None:
            return
        state = self._voice.state.value
        # Sigurno pokretanje samo iz IDLE/ERROR (nema re-entrancy)
        if state in ("idle", "error"):
            try:
                ok = self._voice.begin_auto_recording()
                if ok:
                    self._auto_cycle_active = True
            except Exception:
                logger.exception("Auto-listen begin_auto_recording failed")
                self._on_auto_error("begin_auto_recording failed")
        else:
            # PROCESSING/SPEAKING — ciklus se nastavlja kad se završi
            # (hook u _on_speak_done / _on_voice_end).
            self._auto_cycle_active = True

    # ------------------------------------------------------------------
    # Chat pipeline
    # ------------------------------------------------------------------

    def _on_send(self, text: str) -> None:
        if self._generation_active:
            logger.info("Generation already active — ignoring send")
            return
        self._start_generation(text)

    def _on_stop_generation(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()

    def _start_generation(self, text: str) -> None:
        """Streaming generacija u pozadini — isti obrazac kao MainWindow."""
        if self._assistant is None:
            return
        import threading

        self._generation_active = True
        self._responded = False
        self._cancel_event = threading.Event()
        if hasattr(self._assistant, "_cancel_event"):
            self._assistant._cancel_event = self._cancel_event
        try:
            worker = _GenerationWorker(self._assistant, text, self._cancel_event)
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
        if self._event_bus is not None:
            self._event_bus.publish("GENERATION_CANCELLED", data={"tokens_generated": 0})
        self._resume_after_response()

    def _on_generation_failed(self, error: str) -> None:
        self._generation_active = False
        self._generation_worker = None
        if self._event_bus is not None:
            self._event_bus.publish("GENERATION_FAILED", data={"error": error})
        self._resume_after_response()

    def _maybe_speak(self, text: str) -> None:
        """TTS ako je voice enabled — isti uslov kao MainWindow."""
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
        """REC dugme — manual push-to-talk (nešto drugo od auto-listen)."""
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

    # --- EventBus handlers (GUI thread — voice manager marshalluje) -------

    def _on_voice_start(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("recording")
        self._chat.set_play_available(bool(self._voice.last_recording_path if self._voice else False))

    def _on_voice_end(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("idle")
        if self._voice is not None:
            self._chat.set_play_available(bool(self._voice.last_recording_path))

    def _on_voice_transcript(self, event_type: str, data: dict) -> None:
        """VOICE_TRANSCRIPT → user poruka → generacija (auto-listen loop)."""
        if self._generation_active:
            logger.info("Transcript while generation active — deferring")
            return
        text = str(data.get("text", "")).strip()
        if not text:
            # Prazan transkript — ne generiši; nastavi ciklus ako je auto ON
            self._resume_after_response()
            return
        self._chat.add_message("user", text)
        self._start_generation(text)

    def _on_speak_start(self, event_type: str, data: dict) -> None:
        self._chat.set_voice_state("speaking")

    def _on_speak_done(self, event_type: str, data: dict) -> None:
        """TTS završen → nazad na slušanje (§2 korak 9) ako je auto mod ON."""
        self._chat.set_voice_state("idle")
        if self._voice is not None:
            self._chat.set_play_available(bool(self._voice.last_recording_path))
        self._resume_after_response()

    def _resume_after_response(self) -> None:
        """Nakon odgovora/TTS → novi ciklus slušanja (auto mod)."""
        if self._auto_listen and not self._stopping:
            self._begin_auto_cycle()
        else:
            self._auto_cycle_active = False

    def _on_voice_error(self, event_type: str, data: dict) -> None:
        message = str(data.get("error", "voice error"))
        self._chat.set_voice_state("error", message)
        self._on_auto_error(message)

    def _on_auto_error(self, message: str) -> None:
        """Nepoporljiva greška → mod mora u konzistentno OFF stanje (§12)."""
        if self._auto_listen:
            logger.error("Automatic Listening error → disabling: %s", message)
            self.set_automatic_listening(False)

    def _on_wake_word(self, event_type: str, data: dict) -> None:
        """Wake word trigger → jedna glasovna interakcija (§6).

        Wake word i auto-listen su NEZAVISNI modovi; wake trigger ne uključuje
        auto mod i ne startuje mikrofon ako je auto ciklus već aktivan.
        """
        if self._voice is None:
            return
        # Ako je auto-listen već aktivan — wake trigger je suvišan
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
        """Čist prekid svega (pozvati iz closeEvent)."""
        self.set_automatic_listening(False)
        if self._generation_worker is not None and self._generation_worker.isRunning():
            if self._cancel_event is not None:
                self._cancel_event.set()
            self._generation_worker.wait(2000)
        self._generation_worker = None
        self.unwire()
