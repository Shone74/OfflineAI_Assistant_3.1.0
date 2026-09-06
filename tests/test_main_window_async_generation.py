"""Regression tests for the MainWindow async generation fix (A1).

Locks the contract: MainWindow._start_generation dispatches ALL generation —
including slash commands and messages whose tool heuristics would previously
have routed to the synchronous GUI-thread path — to the existing
GenerationWorker (QThread), so LLM inference and tool execution never run on
the GUI thread.  The previous ``while … processEvents()`` busy-wait is
replaced by a nested QEventLoop that keeps the GUI responsive.

These tests construct a minimal MainWindow stand-in?  No — they exercise the
REAL MainWindow._start_generation_worker through a real MainWindow instance
(offscreen), with a stub Assistant whose process_message records its
execution thread and optionally blocks.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from ui.main_window import MainWindow


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
class StubAssistant:
    """Deterministic Assistant stand-in: records thread, blocks, streams.

    Provides the attribute surface MainWindow and its pages touch
    (get_assistant_profile, project helpers, model helpers).
    """

    def __init__(self, block_seconds: float = 0.0, fail: bool = False) -> None:
        self.calls = 0
        self.exec_threads: list[int] = []
        self.block_seconds = block_seconds
        self.fail = fail
        self.last_text: str | None = None

    # ---- Assistant surface used by MainWindow / pages ------------------- #
    @property
    def model_name(self) -> str:
        return "stub"

    class _StubEngine:
        model_name = "stub"

    _engine = _StubEngine()  # MainWindow._on_worker_finished reads ._engine

    def get_assistant_profile(self):
        return {
            "identity": {"name": "Stub", "description": "stub"},
            "personality": {},
            "communication": {},
            "expertise": {},
            "behavior": {},
            "boundaries": {},
        }

    def get_active_project_id(self):
        return None

    def get_project_context(self):
        return None

    def request_cancel(self) -> None:
        pass

    def run_knowledge_search(self, query, top_k=3):
        return "", []

    def switch_model(self, name):  # noqa: ARG002
        pass

    def assign_agent_to_project(self, agent_name):  # noqa: ARG002
        return False

    # ---- generation ------------------------------------------------------ #
    def process_message(self, text, **kwargs) -> str:
        self.calls += 1
        self.last_text = text
        self.exec_threads.append(threading.get_ident())
        pulse = kwargs.get("pulse_callback")
        if self.block_seconds:
            # Simulate a long generation; call the pulse callback the way the
            # native-tool loop would (the worker passes a no-op — proving the
            # generation no longer depends on GUI-side pumping).
            deadline = time.monotonic() + self.block_seconds
            while time.monotonic() < deadline:
                if pulse is not None:
                    pulse()
                time.sleep(0.05)
        if self.fail:
            raise RuntimeError("stub generation failed")
        return f"response to: {text}"

    def _message_needs_tool(self, lowered: str) -> bool:
        return any(k in lowered for k in ("open", "read", "search", "calculate"))


class FakeVoice:
    def speak(self, text: str) -> None:  # noqa: ARG002
        pass


def _make_window(tmp_path: Path, assistant: StubAssistant) -> MainWindow:
    config = ConfigManager(settings_path=tmp_path / "settings.json")
    bus = EventBus()
    theme = None
    window = MainWindow(
        config=config,
        event_bus=bus,
        theme=theme,
        assistant=assistant,  # type: ignore[arg-type]
    )
    return window


def _pump_events(app: QApplication, seconds: float, step: float = 0.01) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(step)


@pytest.fixture()
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    yield app


# --------------------------------------------------------------------------- #
# 1. WORKER THREAD — every generation path runs off the GUI thread
# --------------------------------------------------------------------------- #
class TestWorkerThread:
    def test_plain_message_executes_on_worker_thread(self, qapp, tmp_path) -> None:
        assistant = StubAssistant()
        window = _make_window(tmp_path, assistant)
        try:
            response = window._start_generation("hello there")

            assert assistant.calls == 1
            assert assistant.exec_threads[0] != threading.get_ident()
            assert response == "response to: hello there"
        finally:
            window.close()

    def test_slash_command_executes_on_worker_thread(self, qapp, tmp_path) -> None:
        """Slash commands previously forced the synchronous GUI path."""
        assistant = StubAssistant()
        window = _make_window(tmp_path, assistant)
        try:
            response = window._start_generation("/help")

            assert assistant.calls == 1
            assert assistant.exec_threads[0] != threading.get_ident()
            assert response == "response to: /help"
        finally:
            window.close()

    def test_tool_heuristic_message_executes_on_worker_thread(
        self, qapp, tmp_path
    ) -> None:
        """'open calculator' style messages previously forced the sync path."""
        assistant = StubAssistant()
        window = _make_window(tmp_path, assistant)
        try:
            response = window._start_generation("please open the calculator app")

            assert assistant.calls == 1
            assert assistant.exec_threads[0] != threading.get_ident()
            assert "open the calculator" in response
        finally:
            window.close()


# --------------------------------------------------------------------------- #
# 2. NON-BLOCKING — GUI event loop stays responsive during generation
# --------------------------------------------------------------------------- #
class TestNonBlocking:
    def test_gui_events_processed_during_slow_generation(self, qapp, tmp_path) -> None:
        """A slow generation must not stall the GUI event loop.

        The generation call blocks only its caller (it must return the
        response synchronously); the worker runs the LLM work off-thread.
        We call _start_generation from a helper thread while the test
        thread pumps the Qt event loop and counts probe-timer events —
        exactly how the GUI thread would experience it in production.
        """
        assistant = StubAssistant(block_seconds=1.5)
        window = _make_window(tmp_path, assistant)

        result: list[str] = []
        gen_thread_error: list[str] = []

        def run_generation() -> None:
            try:
                result.append(window._start_generation("slow one"))
            except Exception as exc:  # pragma: no cover
                gen_thread_error.append(repr(exc))

        gen_thread = threading.Thread(target=run_generation, daemon=True)

        probe_events: list[float] = []
        probe = QTimer()
        probe.setInterval(200)
        t0 = time.monotonic()

        def on_probe() -> None:
            probe_events.append(time.monotonic() - t0)

        probe.timeout.connect(on_probe)
        probe.start()

        try:
            gen_thread.start()
            _pump_events(qapp, 4.0)
            gen_thread.join(timeout=5.0)

            assert not gen_thread_error, gen_thread_error
            assert result and result[0] == "response to: slow one"
            assert assistant.calls == 1
            # Event-loop responsiveness: probes must fire DURING the 1.5 s
            # generation.  The old synchronous path blocked all events until
            # the generation finished (~1.5 s for the first probe).
            assert probe_events, "no GUI probe events delivered"
            assert probe_events[0] < 1.0, (
                f"GUI event loop appears blocked: first probe at {probe_events[0]:.2f}s"
            )
            during = [t for t in probe_events if t < 1.5]
            assert len(during) >= 3, (
                f"too few probe events during generation: {probe_events}"
            )
        finally:
            probe.stop()
            window.close()

    def test_generation_completes_when_called_on_gui_thread(self, qapp, tmp_path) -> None:
        """Direct GUI-thread invocation still returns the response.

        _start_generation is allowed to block its CALLER while the worker
        runs (nested QEventLoop keeps the GUI processing), so a direct call
        on the GUI thread must complete and return the full response.
        """
        assistant = StubAssistant(block_seconds=0.5)
        window = _make_window(tmp_path, assistant)
        try:
            response = window._start_generation("hello")
            assert response == "response to: hello"
            assert assistant.calls == 1
            assert assistant.exec_threads[0] != threading.get_ident()
        finally:
            window.close()

    def test_no_busy_wait_pumping_in_worker_path(self, qapp, tmp_path) -> None:
        """The worker wait uses a nested QEventLoop, not processEvents polling.

        The ``_pulse_event_loop`` helper exists only for backward
        compatibility with old tests — the worker path must never call it.
        """
        assistant = StubAssistant()
        window = _make_window(tmp_path, assistant)
        calls: list[int] = []

        original = window._pulse_event_loop

        def spy() -> None:
            calls.append(1)
            original()

        window._pulse_event_loop = spy  # type: ignore[method-assign]
        try:
            window._start_generation("plain")
            assert assistant.calls == 1
            assert calls == []  # worker path never pumps manually
        finally:
            window._pulse_event_loop = original  # type: ignore[method-assign]
            window.close()


# --------------------------------------------------------------------------- #
# 3. FAILURE / EXCEPTION — worker exceptions surface as empty + status event
# --------------------------------------------------------------------------- #
class TestFailureHandling:
    def test_generation_exception_returns_empty_and_does_not_crash(
        self, qapp, tmp_path
    ) -> None:
        assistant = StubAssistant(fail=True)
        window = _make_window(tmp_path, assistant)
        try:
            response = window._start_generation("boom")

            assert response == ""
            assert assistant.calls == 1  # attempted
            # The window remains usable for a subsequent generation.
            assistant.fail = False
            ok = window._start_generation("retry")
            assert ok == "response to: retry"
        finally:
            window.close()


# --------------------------------------------------------------------------- #
# 4. ROUTING PRESERVED — slash/tool heuristics still reach process_message
# --------------------------------------------------------------------------- #
class TestRoutingPreserved:
    def test_slash_commands_and_heuristic_texts_are_processed_verbatim(
        self, qapp, tmp_path
    ) -> None:
        assistant = StubAssistant()
        window = _make_window(tmp_path, assistant)
        try:
            window._start_generation("/agent plan something")
            window._start_generation("calculate 2+2")
            window._start_generation("just chatting")

            assert assistant.calls == 3
            assert assistant.last_text == "just chatting"
        finally:
            window.close()

    def test_reentrant_start_is_ignored(self, qapp, tmp_path) -> None:
        """Generation-active guard preserved from the original implementation."""
        assistant = StubAssistant(block_seconds=0.8)
        window = _make_window(tmp_path, assistant)
        try:
            result: list[str] = []
            gen_thread = threading.Thread(
                target=lambda: result.append(window._start_generation("first")),
                daemon=True,
            )
            gen_thread.start()
            _pump_events(qapp, 0.25)  # first generation now active on worker

            # Re-entrant call while the first generation is still active —
            # delivered on the GUI thread like a real second chat message.
            second = window._start_generation("second")
            assert second == ""

            gen_thread.join(timeout=5.0)
            _pump_events(qapp, 2.0)
            assert result == ["response to: first"]
            assert assistant.calls == 1  # re-entrant ignored
        finally:
            window.close()
