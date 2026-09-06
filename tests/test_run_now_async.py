"""Regression tests for the asynchronous "Run Now" dispatcher path.

Locks the contract from the Run Now off-GUI-thread fix:

* ``AutomationDispatcher.run_now(name)`` submits the task through the
  EXISTING worker infrastructure — actual tool/workflow execution runs on
  an ``AutomationTaskWorker`` (never the GUI thread), so the GUI event
  loop stays responsive during long-running tasks.
* Completion returns to the GUI thread via the queued ``task_finished``
  signal; finalization (status, ``last_run``, ``schedule_next``,
  EventBus publication) happens on the GUI thread.
* In-flight protection covers Run Now: a task already running (whether
  started by the scheduler tick or a previous Run Now) cannot be
  duplicated; after finalization it is submittable again.
* ONCE semantics from ``9ddd423`` are preserved through the async path:
  successful ONCE Run Now → disabled, ``next_run=None``, ``run_at`` kept.
* Security remains fail-closed: a WRITE tool without an approval callback
  is denied (UserDenied → FAILED) and never executes.
* Shutdown uses the existing bounded dispatcher shutdown; submissions
  after shutdown are rejected.
"""

from __future__ import annotations

import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation.manager import AutomationManager
from automation.task import AutomationTask, ScheduleType, TaskStatus
from automation.worker import AutomationDispatcher
from tools.base import RiskLevel, Tool, ToolResult, ToolRegistry


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict | None]] = []
        self.publish_thread: list[int] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.events.append((event_type, data))
        self.publish_thread.append(threading.get_ident())


class ProbeTool(Tool):
    """Records execution thread, optionally blocks or raises."""

    name = "probe"
    description = "run-now probe"
    calls = 0
    exec_threads: list[int] = []
    block_seconds = 0.0
    fail = False

    def execute(self, **params) -> ToolResult:
        type(self).calls += 1
        type(self).exec_threads.append(threading.get_ident())
        if type(self).block_seconds:
            time.sleep(type(self).block_seconds)
        if type(self).fail:
            return ToolResult(False, "", tool_name=self.name, error="Boom")
        return ToolResult(True, "probe ok", tool_name=self.name)

    @classmethod
    def reset(cls, block_seconds: float = 0.0, fail: bool = False) -> None:
        cls.calls = 0
        cls.exec_threads = []
        cls.block_seconds = block_seconds
        cls.fail = fail


class _RaisingTool(Tool):
    name = "raiser"
    description = "always raises"

    def execute(self, **params) -> ToolResult:
        raise RuntimeError("kaboom")


class _WriteTool(Tool):
    """WRITE-risk tool — requires SecurityLayer confirmation."""

    name = "write_probe"
    description = "write tool"
    risk_level = RiskLevel.WRITE

    def execute(self, **params) -> ToolResult:
        return ToolResult(True, "written", tool_name=self.name)


def _pump_events(app: QCoreApplication, seconds: float, step: float = 0.01) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(step)


@pytest.fixture()
def qapp() -> QCoreApplication:
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app


def _make_task(name: str = "t1", schedule: ScheduleType = ScheduleType.ONCE,
               run_at: datetime | None = None) -> AutomationTask:
    return AutomationTask(
        name=name,
        tool_name="probe",
        params={},
        schedule=schedule,
        interval_seconds=60.0,
        run_at=run_at if run_at is not None else datetime.now() - timedelta(minutes=1),  # noqa: DTZ005
    )


def _make_manager_with(tools: list[Tool]) -> tuple[AutomationManager, FakeEventBus]:
    registry = ToolRegistry()
    for tool in tools:
        registry.register(tool)
    bus = FakeEventBus()
    manager = AutomationManager(tool_registry=registry, event_bus=bus)
    return manager, bus


# --------------------------------------------------------------------------- #
# A. NON-BLOCKING — GUI event loop stays responsive during Run Now
# --------------------------------------------------------------------------- #
class TestNonBlocking:
    def test_gui_events_processed_while_run_now_task_executes(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset(block_seconds=1.5)
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        probe_events: list[float] = []
        probe = QTimer()
        probe.setInterval(200)
        t0 = time.monotonic()

        def on_probe() -> None:
            probe_events.append(time.monotonic() - t0)

        probe.timeout.connect(on_probe)
        probe.start()

        assert dispatcher.run_now("t1") is True
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert ProbeTool.calls == 1
        # Event-loop responsiveness: probes must fire DURING execution —
        # the pre-fix synchronous path delivered the first probe only at
        # ~1.5 s (task completion).  A blocked loop cannot do this.
        assert probe_events, "no GUI probe events delivered"
        assert probe_events[0] < 1.0, (
            f"GUI event loop appears blocked: first probe at {probe_events[0]:.2f}s"
        )
        during_task = [t for t in probe_events if t < 1.5]
        assert len(during_task) >= 3, (
            f"too few probe events during execution: {probe_events}"
        )


# --------------------------------------------------------------------------- #
# B. WORKER THREAD — execution is off the GUI thread
# --------------------------------------------------------------------------- #
class TestWorkerThread:
    def test_run_now_executes_on_worker_thread_not_gui(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        main_thread = threading.get_ident()
        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        assert dispatcher.run_now("t1") is True
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert ProbeTool.calls == 1
        assert ProbeTool.exec_threads[0] != main_thread


# --------------------------------------------------------------------------- #
# C. COMPLETION / GUI FINALIZATION
# --------------------------------------------------------------------------- #
class TestCompletionFinalization:
    def test_task_finalized_emitted_with_correct_state(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task()
        run_at_before = task.run_at
        manager.register_task(task)

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        submitted_at = datetime.now()  # noqa: DTZ005
        assert dispatcher.run_now("t1", now=submitted_at) is True
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        # Final state — same semantics as the synchronous run_task_now.
        assert task.status is TaskStatus.SUCCESS
        assert task.result == "probe ok"
        assert task.last_run == submitted_at
        # ONCE semantics (9ddd423) preserved through the async path.
        assert task.enabled is False
        assert task.next_run is None
        assert task.run_at == run_at_before  # run_at untouched
        # AUTOMATION_TASK_COMPLETED published from the GUI thread.
        completed = [
            bus.publish_thread[i]
            for i, (evt, _) in enumerate(bus.events)
            if evt == "AUTOMATION_TASK_COMPLETED"
        ]
        assert completed, "AUTOMATION_TASK_COMPLETED was not published"
        assert all(t == threading.get_ident() for t in completed)

    def test_interval_task_reschedules_through_run_now(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task(name="int1", schedule=ScheduleType.INTERVAL, run_at=None)
        manager.register_task(task)

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())
        submitted_at = datetime.now()  # noqa: DTZ005
        assert dispatcher.run_now("int1", now=submitted_at) is True
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is True  # INTERVAL never auto-disabled
        assert task.next_run == submitted_at + timedelta(seconds=60)


# --------------------------------------------------------------------------- #
# D. EXCEPTION — failing task does not break the dispatcher
# --------------------------------------------------------------------------- #
class TestExceptionHandling:
    def test_raising_task_fails_and_dispatcher_continues(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([_RaisingTool(), ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)

        bad = _make_task(name="bad")
        bad.tool_name = "raiser"
        good = _make_task(name="good")
        good.tool_name = "probe"
        manager.register_task(bad)
        manager.register_task(good)

        finalized: list[str] = []
        finished_bad = threading.Event()
        finished_good = threading.Event()
        state = {"n": 0}

        def on_finalized(name: str, _ok: bool) -> None:
            state["n"] += 1
            finalized.append(name)
            if name == "bad":
                finished_bad.set()
            if name == "good":
                finished_good.set()

        dispatcher.task_finalized.connect(on_finalized)

        assert dispatcher.run_now("bad") is True
        assert dispatcher.run_now("good") is True  # second task still accepted
        _pump_events(qapp, 3.0)

        assert finished_bad.is_set() and finished_good.is_set()
        # Worker catches the exception → FAILED + exception type preserved.
        assert bad.status is TaskStatus.FAILED
        assert bad.result == "RuntimeError"
        assert bad.enabled is True  # FAILED keeps the retry path
        # The other task executed normally afterwards.
        assert good.status is TaskStatus.SUCCESS
        assert ProbeTool.calls == 1


# --------------------------------------------------------------------------- #
# E. DUPLICATE / IN-FLIGHT RACE
# --------------------------------------------------------------------------- #
class TestInFlightRace:
    def test_run_now_rejected_while_scheduler_task_in_flight(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset(block_seconds=1.0)
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task(name="race", schedule=ScheduleType.INTERVAL, run_at=None)
        manager.register_task(task)

        # Scheduler tick submits the task (worker now running for 1 s).
        dispatcher.tick(datetime.now())  # noqa: DTZ005
        assert dispatcher.is_in_flight("race")

        # Repeated Run Now while in flight → rejected, no duplicate submission.
        assert dispatcher.run_now("race") is False
        assert dispatcher.run_now("race") is False

        _pump_events(qapp, 3.0)  # let the worker finish + finalize
        assert ProbeTool.calls == 1  # exactly ONE execution

        # After finalization the task left the in-flight set.
        assert not dispatcher.is_in_flight("race")
        # INTERVAL task is still due (next_run = submission + 60 s → not yet)
        # but Run Now bypasses the schedule: submittable again.
        ProbeTool.reset()
        assert dispatcher.run_now("race") is True
        _pump_events(qapp, 3.0)
        assert ProbeTool.calls == 1

    def test_repeated_run_now_clicks_execute_once(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset(block_seconds=0.8)
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        assert dispatcher.run_now("t1") is True
        # Simulate rapid repeated clicks while the worker runs.
        for _ in range(4):
            assert dispatcher.run_now("t1") is False

        _pump_events(qapp, 3.0)
        assert ProbeTool.calls == 1


# --------------------------------------------------------------------------- #
# F. ONCE COMPATIBILITY (async path mirrors the 9ddd423 fix)
# --------------------------------------------------------------------------- #
class TestOnceCompatibility:
    def test_once_run_now_success_disables_and_never_reexecutes(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        assert dispatcher.run_now("t1") is True
        _pump_events(qapp, 3.0)
        assert finished.is_set()
        assert ProbeTool.calls == 1
        task = manager.get_task("t1")
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False

        # Scheduler ticks must not re-execute the completed ONCE task.
        for _ in range(3):
            dispatcher.tick(datetime.now())  # noqa: DTZ005
            _pump_events(qapp, 0.05)
        # Run Now must reject the disabled ONCE task.
        assert dispatcher.run_now("t1") is False
        assert ProbeTool.calls == 1  # never more than one execution


# --------------------------------------------------------------------------- #
# G. SECURITY — WRITE tool denied without approval callback (fail-closed)
# --------------------------------------------------------------------------- #
class TestSecurityPath:
    def test_write_tool_run_now_denied_without_callback(
        self, qapp: QCoreApplication
    ) -> None:
        # No SecurityLayer approval callback is registered anywhere in this
        # stack — the WRITE tool must be denied through the same
        # ToolRegistry → SecurityLayer gateway used by scheduler execution.
        ProbeTool.reset()
        write_probe = _WriteTool()
        manager, bus = _make_manager_with([write_probe, ProbeTool()])
        # Attach a SecurityLayer with NO approval callback (fail-closed).
        from security.auditor import SecurityAuditor
        from security.permission_manager import PermissionManager
        from core.security_layer import SecurityLayer
        import tempfile
        from pathlib import Path as P

        audit = P(tempfile.mkdtemp()) / "audit.jsonl"
        SecurityLayer(
            registry=manager.tool_registry,
            pm=PermissionManager(),
            auditor=SecurityAuditor(log_path=audit),
            event_bus=None,
        )

        task = _make_task(name="secured")
        task.tool_name = "write_probe"
        manager.register_task(task)

        finished = threading.Event()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        assert dispatcher.run_now("secured") is True
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        # The tool never executed; the task finalized as FAILED with the
        # security denial error, exactly like the scheduler path.
        assert task.status is TaskStatus.FAILED
        assert task.result == "UserDenied"

    def test_execution_flows_through_tool_registry_gateway(
        self, qapp: QCoreApplication
    ) -> None:
        # The dispatcher's execute callback is the SAME one used by the
        # scheduler dispatch path (manager._dispatch_execute) — proven by
        # the Run Now submission working through a registry-backed tool.
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        assert dispatcher.is_in_flight("t1") is False
        assert dispatcher.run_now("t1") is True  # submitted through submit()
        assert dispatcher.is_in_flight("t1") is True
        _pump_events(qapp, 3.0)
        assert not dispatcher.is_in_flight("t1")
        assert ProbeTool.calls == 1


# --------------------------------------------------------------------------- #
# H. SHUTDOWN — existing bounded shutdown covers Run Now workers
# --------------------------------------------------------------------------- #
class TestShutdown:
    def test_shutdown_rejects_new_run_now_and_clears_workers(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset(block_seconds=0.5)
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())

        assert dispatcher.run_now("t1") is True  # worker now running

        before = threading.active_count()
        dispatcher.shutdown(wait_ms=5000)  # existing bounded shutdown
        _pump_events(qapp, 0.5)

        assert dispatcher.in_flight_count == 0
        # No automation QThreads left alive.
        automation_threads = [
            t for t in threading.enumerate()
            if t.name.startswith("QThread")
        ]
        assert all(
            not getattr(t, "isRunning", lambda: False)()
            for t in automation_threads
        ), f"worker threads still running: {automation_threads}"
        _pump_events(qapp, 0.2)
        assert threading.active_count() <= before + 1

        # Submissions after shutdown are rejected.
        ProbeTool.reset()
        assert dispatcher.run_now("t1") is False
        assert ProbeTool.calls == 0

    def test_run_now_rejections_for_unknown_and_disabled_tasks(
        self, qapp: QCoreApplication
    ) -> None:
        ProbeTool.reset()
        manager, bus = _make_manager_with([ProbeTool()])
        dispatcher = AutomationDispatcher(manager, event_bus=bus)

        # Unknown task → rejected (TaskNotFound semantics).
        assert dispatcher.run_now("ghost") is False
        assert ProbeTool.calls == 0

        # Disabled task → rejected (TaskDisabled semantics).
        task = _make_task()
        task.enabled = False
        manager.register_task(task)
        assert dispatcher.run_now("t1") is False
        assert ProbeTool.calls == 0
        assert dispatcher.is_in_flight("t1") is False
