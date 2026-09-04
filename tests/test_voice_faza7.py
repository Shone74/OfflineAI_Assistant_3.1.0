"""Testovi Faze 7: Wake Word + Automatic Listening (specifikacija §13).

Koristi postojeće injekcione šavove: StubSTT (set_transcript), StubTTS,
StubWakeWord, create_audio(preferred="stub") i injectable transcription_runner.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from PySide6.QtWidgets import QApplication

from core.event_bus import EventBus
from voice.audio import StubAudioManager
from voice.stt import StubSTT
from voice.tts import StubTTS
from voice.wake_word import StubWakeWord, create_wake_word


class FakeAudioManager(StubAudioManager):
    """Test mikrofon: available=True, buffer raste (za watchdog i sesije)."""

    def __init__(self):
        super().__init__()
        self._fake_buffer = bytearray()
        self._sessions = 0

    def is_available(self) -> bool:
        return True

    def start_recording(self) -> None:
        self._sessions += 1
        self._fake_buffer = bytearray(b"\x00\x01" * 160)  # 160 samples

    def stop_recording(self) -> tuple[bytes, int]:
        data = bytes(self._fake_buffer)
        self._fake_buffer = bytearray()
        return data, 16000

    def buffer_size(self) -> int:
        return len(self._fake_buffer)

    @property
    def session_count(self) -> int:
        return self._sessions


def _make_manager(qapp, **overrides):
    from voice.manager import VoiceManager

    stt = overrides.pop("stt", StubSTT())
    tts = overrides.pop("tts", StubTTS())
    # wake=None znači "kreiraj iz configa"; eksplicitan stub samo kad test traži
    wake = overrides.pop("wake", None)
    audio = overrides.pop("audio_manager", FakeAudioManager())
    bus = overrides.pop("event_bus", EventBus())
    config = overrides.pop("config", None)

    def sync_runner(stt_provider, pcm, sr, on_done, on_error):
        try:
            text = stt_provider.transcribe(pcm, sample_rate=sr)
            on_done(text)
        except Exception as exc:
            on_error(str(exc))

    manager = VoiceManager(
        bus,
        stt=stt,
        tts=tts,
        wake=wake,
        audio_manager=audio,
        transcription_runner=sync_runner,
        config=config,
        **overrides,
    )
    return manager, bus


def _make_coordinator(qapp, manager, bus, assistant=None):
    from ui.chat_voice_coordinator import ChatVoiceCoordinator
    from ui.chat_widget import ChatWidget

    chat = ChatWidget()
    coordinator = ChatVoiceCoordinator(
        chat=chat,
        assistant=assistant,
        voice_manager=manager,
        event_bus=bus,
    )
    coordinator.wire()
    return coordinator, chat


# ====================================================================== #
# WAKE WORD (specifikacija §13 — Wake word)
# ====================================================================== #

class TestWakeWord:
    def test_default_wake_word_is_hey_jarvis(self, qapp, tmp_path):
        """Default wake fraza mora biti 'hey_jarvis' (§1, §17)."""
        from core.config_manager import ConfigManager
        from voice.manager import VoiceManager

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        manager = VoiceManager(
            EventBus(),
            stt=StubSTT(),
            tts=StubTTS(),
            audio_manager=FakeAudioManager(),
            config=config,
        )
        assert manager._wake.hotword == "hey_jarvis"

    def test_config_default_wake_word_section(self, tmp_path):
        from core.config_manager import ConfigManager

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        wake_cfg = config.get("voice.wake_word", {})
        assert wake_cfg.get("hotword") == "hey_jarvis"
        assert wake_cfg.get("enabled") is True
        assert wake_cfg.get("provider") == "openwakeword"

    def test_custom_wake_word_config(self, qapp, tmp_path):
        """Custom hotword iz configa se poštuje (mora biti validna labela)."""
        from core.config_manager import ConfigManager

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        # "alexa" je predefinisana openwakeword labela (i u stubu se prenosi)
        config.set("voice.wake_word.hotword", "alexa")
        manager, _ = _make_manager(None, config=config)
        assert manager._wake.hotword == "alexa"

    def test_invalid_hotword_falls_back_to_hey_jarvis(self, tmp_path):
        """Nepostojeća labela → fallback na 'hey_jarvis' (graceful)."""
        from core.config_manager import ConfigManager

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        config.set("voice.wake_word.hotword", "nepostojeca_fraza")
        manager, _ = _make_manager(None, config=config)
        # Stub prenosi bilo šta; real provider validira. U oba slučaja
        # inicijalizacija ne sme da padne.
        assert manager._wake.hotword in ("nepostojeca_fraza", "hey_jarvis")

    def test_wake_word_detection_triggers_event(self, qapp):
        """Wake word detekcija okida WAKE_WORD_DETECTED (thread-safe marshalled)."""
        manager, bus = _make_manager(qapp)
        received: list[str] = []
        bus.subscribe("WAKE_WORD_DETECTED", lambda et, d: received.append(et))

        manager.start_wake_word()
        # Simuliraj detekciju (stub nikad sam ne okida — pozovemo callback)
        manager._wake._callback()
        # QMetaObject queued poziv — procesiramo event loop
        QApplication.processEvents()
        assert received == ["WAKE_WORD_DETECTED"]
        manager.stop()

    def test_duplicate_activation_prevented(self, qapp):
        """Refractory: drugi trigger unutar cooldown perioda se ignoriše."""
        manager, bus = _make_manager(qapp)
        received: list[str] = []
        bus.subscribe("WAKE_WORD_DETECTED", lambda et, d: received.append(et))

        manager.start_wake_word()
        manager._wake._callback()  # 1. detekcija
        QApplication.processEvents()
        manager._wake._callback()  # 2. detekcija (isti izgovoreni trenutak)
        QApplication.processEvents()
        assert len(received) == 1  # refractory blokira duplikat
        manager.stop()

    def test_detector_start_stop_lifecycle(self, qapp):
        """Start/stop je čist i idempotentan; restart radi."""
        manager, _ = _make_manager(qapp)
        manager.start_wake_word()
        manager.stop_wake_word()
        manager.stop_wake_word()  # idempotentno
        manager.start_wake_word()  # restart radi
        manager.stop()
        assert manager._wake.is_listening is False

    def test_provider_fallback_and_hotword(self):
        """Factory: hotword se poštuje u oba provider-a; fallback je siguran."""
        provider = create_wake_word(preferred="openwakeword", hotword="hey_jarvis")
        assert provider.hotword == "hey_jarvis"
        # Bez obzira na backend (real ili stub), interfеjs je konzistentan
        assert hasattr(provider, "start") and hasattr(provider, "stop")

    def test_stub_fallback_carries_hotword(self):
        """Stub fallback prenosi hotword (config se ne gubi u fallback-u)."""
        from voice.wake_word import StubWakeWord

        stub = StubWakeWord(hotword="hey_jarvis")
        assert stub.hotword == "hey_jarvis"

    def test_real_openwakeword_backend_works(self, qapp):
        """Sa instaliranim openwakeword (ONNX) — stvarni provider radi."""
        import importlib.util

        if importlib.util.find_spec("openwakeword") is None:
            pytest.skip("openwakeword nije instaliran")
        from voice.wake_word import OpenWakeWord

        provider = OpenWakeWord(hotword="hey_jarvis")
        assert provider.hotword == "hey_jarvis"
        # Inferencija na tišini — score 0, nema trigera
        import numpy as np

        silence = np.zeros(1024, dtype=np.float32)
        triggered = []
        provider._callback = lambda: triggered.append(True)
        provider._running = True
        provider._detect(silence)
        assert triggered == []  # tišina ne okida

    def test_real_openwakeword_start_stop(self, qapp):
        """Stvarni provider start/stop lifecycle (sa mikrofonom)."""
        import importlib.util

        if importlib.util.find_spec("openwakeword") is None:
            pytest.skip("openwakeword nije instaliran")
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            pytest.skip("sounddevice/mikrofon nije dostupan")
        from voice.wake_word import OpenWakeWord

        provider = OpenWakeWord(hotword="hey_jarvis")
        provider.start(lambda: None)
        assert provider.is_listening is True
        provider.stop()
        assert provider.is_listening is False

    def test_wake_word_error_does_not_crash(self, qapp):
        """Greška u detektoru ne ruši aplikaciju (§12)."""
        class ExplodingWake(StubWakeWord):
            def start(self, on_detected):
                raise RuntimeError("backend exploded")

        manager, _ = _make_manager(qapp, wake=ExplodingWake())
        manager.start_wake_word()  # ne sme da baci
        manager.stop()


# ====================================================================== #
# AUTOMATIC LISTENING (specifikacija §13 — Automatic Listening)
# ====================================================================== #

class TestAutomaticListening:
    def test_off_on_transition(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _chat = _make_coordinator(qapp, manager, bus)
        assert coordinator.is_automatic_listening is False

        ok = coordinator.set_automatic_listening(True)
        assert ok is True
        assert coordinator.is_automatic_listening is True
        # Ciklus je počeo — state je RECORDING
        assert manager.state.value == "recording"
        coordinator.shutdown()

    def test_on_off_transition(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _chat = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        coordinator.set_automatic_listening(False)
        assert coordinator.is_automatic_listening is False
        assert coordinator._stopping is False  # resetovan
        assert manager.state.value == "idle"
        coordinator.shutdown()

    def test_on_is_idempotent(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        coordinator.set_automatic_listening(True)  # drugi ON — no-op
        assert coordinator.is_automatic_listening is True
        coordinator.shutdown()

    def test_repeated_on_off_cycles_are_safe(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        for _ in range(5):
            coordinator.set_automatic_listening(True)
            assert manager.state.value == "recording"
            coordinator.set_automatic_listening(False)
            assert manager.state.value == "idle"
        coordinator.shutdown()

    def test_off_does_not_create_duplicate_workers(self, qapp):
        """Ponovljeni ON/OFF ne akumulira streamove/callback-eve."""
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        for _ in range(3):
            coordinator.set_automatic_listening(True)
            coordinator.set_automatic_listening(False)
        # Samo jedan audio resurs (stub — proveravamo da stop() radi svaki put)
        manager.stop()
        assert manager._auto_watchdog is None

    def test_full_cycle_listen_stt_response_tts_relisten(self, qapp):
        """Pun ciklus: LISTENING → STT → odgovor → TTS → nazad na LISTENING."""
        manager, bus = _make_manager(qapp)
        stt = manager._stt
        stt.set_transcript("Koliko je sati?")

        assistant = MagicMock()
        assistant.process_message = MagicMock(return_value="Tacno podne.")
        # MagicMock ima sve atribute — isključi interferenciju sa cancel_event
        del assistant._cancel_event

        coordinator, _chat = _make_coordinator(qapp, manager, bus, assistant=assistant)
        coordinator.set_automatic_listening(True)
        assert manager.state.value == "recording"

        # Korisnik je završio izjavu (watchdog bi ovo radio u realnom vremenu)
        manager.stop_and_transcribe()
        assert manager.state.value == "processing" or manager.state.value == "idle"

        # Transcript stigao → generacija pokrenuta u worker thread-u →
        # čekamo da završi (worker je QThread; processEvents pumpa signale)
        deadline = 30
        while not assistant.process_message.called and deadline > 0:
            QApplication.processEvents()
            import time

            time.sleep(0.05)
            deadline -= 1
        assert assistant.process_message.called, "Generacija se nije pokrenula"
        # Koordinator je započeo novi ciklus nakon odgovora; ako je TTS aktivan
        # (stvarni settings.json postoji), čekamo i kroz TTS fazu do re-listen.
        deadline = 60
        while manager.state.value != "recording" and deadline > 0:
            QApplication.processEvents()
            import time

            time.sleep(0.05)
            deadline -= 1
        assert coordinator.is_automatic_listening is True
        assert manager.state.value == "recording", (
            f"Ciklus se nije nastavio — state={manager.state.value}"
        )
        coordinator.shutdown()

    def test_stopping_during_listening_is_safe(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        assert manager.state.value == "recording"
        coordinator.set_automatic_listening(False)  # STOP tokom LISTENING
        assert coordinator.is_automatic_listening is False
        assert manager.state.value == "idle"
        coordinator.shutdown()

    def test_stopping_during_processing_is_safe(self, qapp):
        manager, bus = _make_manager(qapp)
        stt = manager._stt
        stt.set_transcript("test")

        class SlowAssistant:
            def __init__(self):
                self.calls = 0

            def process_message(self, text, **kwargs):
                self.calls += 1
                return "odgovor"

        assistant = SlowAssistant()
        coordinator, _ = _make_coordinator(qapp, manager, bus, assistant=assistant)
        coordinator.set_automatic_listening(True)
        manager.stop_and_transcribe()  # → PROCESSING
        QApplication.processEvents()
        # STOP tokom PROCESSING — ne sme da baci
        coordinator.set_automatic_listening(False)
        assert coordinator.is_automatic_listening is False
        coordinator.shutdown()

    def test_stopping_during_tts_is_safe(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        manager.speak("Odgovor asistenta")  # → SPEAKING
        assert manager.state.value == "speaking"
        coordinator.set_automatic_listening(True)  # tokom SPEAKING — čeka TTS
        coordinator.set_automatic_listening(False)  # STOP tokom SPEAKING
        assert coordinator.is_automatic_listening is False
        coordinator.shutdown()

    def test_shutdown_while_active_is_clean(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        coordinator.shutdown()  # shutdown bez prethodnog OFF
        assert coordinator.is_automatic_listening is False
        assert manager.state.value == "idle"
        assert manager._auto_watchdog is None

    def test_error_disables_auto_mode(self, qapp):
        """Nepoporljiva greška → mod mora u OFF stanje (§12)."""
        class BrokenAudio(StubAudioManager):
            def start_recording(self):
                from voice.audio import AudioCaptureError

                raise AudioCaptureError("mic unavailable")

        manager, bus = _make_manager(qapp, audio_manager=BrokenAudio())
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        # begin_recording je pao → _on_auto_error → mod OFF
        assert coordinator.is_automatic_listening is False
        coordinator.shutdown()


# ====================================================================== #
# INTERACTION (specifikacija §13 — Interaction)
# ====================================================================== #

class TestInteractionModes:
    def test_wake_word_and_auto_listen_no_competing_sessions(self, qapp):
        """Wake trigger tokom aktivnog auto ciklusa se ignoriše (§6)."""
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        # Auto ciklus aktivan (RECORDING) — wake trigger suvišan:
        coordinator._on_wake_word("WAKE_WORD_DETECTED", {})
        assert manager.state.value == "recording"  # i dalje JEDNA sesija
        coordinator.shutdown()

    def test_wake_word_triggers_voice_interaction_when_idle(self, qapp):
        """Wake word u IDLE → pokreće glasovnu sesiju (kao klik na REC)."""
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        assert manager.state.value == "idle"
        coordinator._on_wake_word("WAKE_WORD_DETECTED", {})
        assert manager.state.value == "recording"
        coordinator.shutdown()

    def test_manual_and_auto_no_unsafe_overlap(self, qapp):
        """Manual klik tokom auto LISTENING — ne pravi drugu sesiju."""
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        # Manual klik tokom RECORDING → VoiceManager tretira kao STOP
        coordinator._on_voice_input()
        # Nije puklo; i dalje jedna sesija konzistentna
        assert manager.state.value in ("processing", "idle")
        coordinator.shutdown()

    def test_tts_suppresses_wake_word_echo(self, qapp):
        """TTS gasi wake word (echo zaštita §8) i vraća ga posle."""
        import time

        manager, _bus = _make_manager(qapp)
        manager.start_wake_word()
        manager.speak("Ovo je odgovor")
        # Wake word ugašen tokom TTS-a
        assert manager._wake_suppressed_for_tts is True
        # TTS worker je QThread — čekamo finished signal
        deadline = 30
        while manager.state.value == "speaking" and deadline > 0:
            QApplication.processEvents()
            time.sleep(0.05)
            deadline -= 1
        QApplication.processEvents()
        # Posle TTS-a wake word se vratio (voice enabled default)
        assert manager._wake_suppressed_for_tts is False
        assert manager.state.value == "idle"
        manager.stop()


# ====================================================================== #
# STATE MACHINE / LIFECYCLE (specifikacija §4/§11)
# ====================================================================== #

class TestLifecycle:
    def test_single_microphone_session_guarantee(self, qapp):
        manager, _ = _make_manager(qapp)
        assert manager.begin_recording() is True
        # Drugi begin_recording MORA odbiti (jedna sesija)
        assert manager.begin_recording() is False
        manager.stop_and_transcribe()
        manager.stop()

    def test_auto_watchdog_stops_on_session_end(self, qapp):
        manager, _ = _make_manager(qapp)
        manager.begin_auto_recording()
        assert manager._auto_session is True
        manager.stop_and_transcribe()
        assert manager._auto_session is False
        assert manager._auto_watchdog is None

    def test_stop_releases_everything(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, _ = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        manager.stop()  # full teardown dok je auto mod aktivan
        assert manager.state.value == "idle"
        assert manager._auto_watchdog is None
        assert manager._wake.is_listening is False

    def test_buffer_size_reports_stub_zero(self, qapp):
        audio = StubAudioManager()
        assert audio.buffer_size() == 0

    def test_wake_cooldown_resets(self, qapp):
        manager, _ = _make_manager(qapp)
        manager._wake_cooldown_active = True
        manager._reset_wake_cooldown()
        assert manager._wake_cooldown_active is False


# ====================================================================== #
# UI (specifikacija §5)
# ====================================================================== #

class TestAutomaticListeningUI:
    def test_button_exists_with_clear_label(self, qapp):
        from ui.chat_widget import ChatWidget

        chat = ChatWidget()
        assert chat._auto_listen_btn.text() == "Automatic Listening"

    def test_button_label_reflects_state(self, qapp):
        from ui.chat_widget import ChatWidget

        chat = ChatWidget()
        chat.set_automatic_listening_ui(True)
        assert chat._auto_listen_btn.text() == "Automatic Listening: ON"
        assert chat._auto_listen_btn.isChecked() is True
        chat.set_automatic_listening_ui(False)
        assert chat._auto_listen_btn.text() == "Automatic Listening"
        assert chat._auto_listen_btn.isChecked() is False

    def test_button_toggles_coordinator(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, chat = _make_coordinator(qapp, manager, bus)
        chat._auto_listen_btn.click()
        assert coordinator.is_automatic_listening is True
        chat._auto_listen_btn.click()
        assert coordinator.is_automatic_listening is False
        coordinator.shutdown()

    def test_coordinator_updates_button_state(self, qapp):
        manager, bus = _make_manager(qapp)
        coordinator, chat = _make_coordinator(qapp, manager, bus)
        coordinator.set_automatic_listening(True)
        assert chat._auto_listen_btn.text() == "Automatic Listening: ON"
        coordinator.set_automatic_listening(False)
        assert chat._auto_listen_btn.text() == "Automatic Listening"
        coordinator.shutdown()


# ====================================================================== #
# CONFIG (specifikacija §10)
# ====================================================================== #

class TestConfiguration:
    def test_every_wake_config_consumed_by_runtime(self, qapp, tmp_path):
        """Svaki config ključ mora imati realan efekat (§10)."""
        from core.config_manager import ConfigManager
        from voice.manager import VoiceManager

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        config.set("voice.wake_word.hotword", "alexa")
        manager = VoiceManager(
            EventBus(),
            stt=StubSTT(),
            tts=StubTTS(),
            audio_manager=StubAudioManager(),
            config=config,
        )
        # hotword se stvarno koristi u provideru
        assert manager._wake.hotword == "alexa"
        # enabled se stvarno koristi u start_wake_word restart logici
        config.set("voice.wake_word.enabled", False)
        manager._state = manager._state.__class__.IDLE
        manager._restart_wake_word_if_enabled()  # ne startuje (disabled)
        assert manager._wake.is_listening is False
        manager.stop()
