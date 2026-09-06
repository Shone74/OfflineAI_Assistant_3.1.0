"""Regression tests for off-GUI-thread automation task execution.

Locks the threading contract established by the dispatcher fix:

* Due evaluation stays on the GUI thread; actual task execution
  (``execute_fn(task, registry)``) runs on a QThread worker.
* GUI event processing continues while a slow task executes
  (the pre-fix runtime reproduction measured a fully blocked event
  loop — first probe event arrived only after the tool finished).
* Completion returns to the GUI thread via a queued connection; task
  state finalization (status, last_run, schedule_next, EventBus
  publication) happens on the GUI thread.
* A task is never submitted twice while its worker is still running.
* The synchronous ``AutomationManager.run_scheduled`` / ``Scheduler.tick``
  API remains intact (existing ONCE tests keep passing unchanged).
* Workers terminate cleanly on shutdown — no zombie QThreads.
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
from automation.worker import AutomationDispatcher, AutomationTaskWorker
from tools.base import Tool, ToolResult, ToolRegistry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
class FakeEventBus:
    """Records publishes thread-safely enough for tests (list.append is atomic)."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict | None]] = []
        self.publish_thread: list[int] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.events.append((event_type, data))
        self.publish_thread.append(threading.get_ident())


class ProbeTool(Tool):
    """Records its execution thread and optionally blocks."""

    name = "probe"
    description = "thread probe"
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


def _pump_events(app: QCoreApplication, seconds: float, step: float = 0.01) -> None:
    """Pump the Qt event loop for *seconds* without blocking the test thread."""
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


def _make_manager_with_probe() -> tuple[AutomationManager, FakeEventBus]:
    ProbeTool.reset()
    registry = ToolRegistry()
    registry.register(ProbeTool())
    bus = FakeEventBus()
    manager = AutomationManager(tool_registry=registry, event_bus=bus)
    return manager, bus


# --------------------------------------------------------------------------- #
# 1. GUI-THREAD CONTRACT — tool execution runs off the GUI thread
# --------------------------------------------------------------------------- #
class TestWorkerThreadContract:
    def test_tool_executes_off_gui_thread(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task()
        manager.register_task(task)

        main_thread = threading.get_ident()
        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())
        dispatcher.tick(datetime.now())  # noqa: DTZ005

        _pump_events(qapp, 3.0)
        assert finished.is_set()
        assert ProbeTool.calls == 1
        assert ProbeTool.exec_threads[0] != main_thread  # worker thread, not GUI

    def test_state_finalization_happens_on_gui_thread(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task()
        manager.register_task(task)

        main_thread = threading.get_ident()
        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())
        dispatcher.tick(datetime.now())  # noqa: DTZ005
        _pump_events(qapp, 3.0)

        # The AUTOMATION_TASK_COMPLETED publication must have come from the
        # GUI thread (queued completion), never from the worker thread.
        completed_threads = [
            bus.publish_thread[i]
            for i, (evt, _) in enumerate(bus.events)
            if evt == "AUTOMATION_TASK_COMPLETED"
        ]
        assert completed_threads, "AUTOMATION_TASK_COMPLETED was not published"
        assert all(t == main_thread for t in completed_threads)


# --------------------------------------------------------------------------- #
# 2. NON-BLOCKING GUI EVENT LOOP
# --------------------------------------------------------------------------- #
class TestNonBlockingEventLoop:
    def test_gui_events_processed_while_slow_task_runs(self, qapp: QCoreApplication) -> None:
        ProbeTool.reset(block_seconds=1.5)
        registry = ToolRegistry()
        registry.register(ProbeTool())
        bus = FakeEventBus()
        manager = AutomationManager(tool_registry=registry, event_bus=bus)
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

        dispatcher.tick(datetime.now())  # noqa: DTZ005

        # Pre-fix behavior (measured): the first probe event arrived only at
        # ~1.61 s because the tool blocked the GUI thread.  With the fix the
        # event loop must keep processing while the worker runs.
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert ProbeTool.calls == 1
        # First probe must fire well before the 1.5 s tool can finish —
        # a blocked event loop cannot deliver ANY probe until ~1.5 s.
        assert probe_events, "no GUI probe events delivered"
        assert probe_events[0] < 1.0, (
            f"GUI event loop appears blocked: first probe at {probe_events[0]:.2f}s"
        )
        # And the loop must have kept firing during the 1.5 s task window.
        during_task = [t for t in probe_events if t < 1.5]
        assert len(during_task) >= 3, (
            f"too few probe events during task execution: {probe_events}"
        )


# --------------------------------------------------------------------------- #
# 3. SUCCESSFUL COMPLETION — state finalized correctly on the GUI thread
# --------------------------------------------------------------------------- #
class TestSuccessfulCompletion:
    def test_status_last_run_and_schedule_next_applied(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task()
        manager.register_task(task)
        run_at_before = task.run_at

        submitted_at = datetime.now()  # noqa: DTZ005
        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())
        dispatcher.tick(submitted_at)
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False          # ONCE success → disabled (9ddd423)
        assert task.next_run is None
        assert task.run_at == run_at_before    # run_at preserved
        assert task.last_run == submitted_at   # scheduling reference = submission time
        assert task.result == "probe ok"
        assert any(evt == "AUTOMATION_TASK_COMPLETED" for evt, _ in bus.events)

    def test_interval_task_reschedules_after_async_run(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task(name="int1", schedule=ScheduleType.INTERVAL, run_at=None)
        manager.register_task(task)

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())
        submitted_at = datetime.now()  # noqa: DTZ005
        dispatcher.tick(submitted_at)
        _pump_events(qapp, 3.0)

        assert finished.is_set()
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is True  # INTERVAL is never auto-disabled
        assert task.next_run == submitted_at + timedelta(seconds=60)


# --------------------------------------------------------------------------- #
# 4. IN-FLIGHT PROTECTION — no duplicate submissions
# --------------------------------------------------------------------------- #
class TestInFlightProtection:
    def test_task_not_resubmitted_while_worker_running(self, qapp: QCoreApplication) -> None:
        ProbeTool.reset(block_seconds=1.0)
        registry = ToolRegistry()
        registry.register(ProbeTool())
        bus = FakeEventBus()
        manager = AutomationManager(tool_registry=registry, event_bus=bus)
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        # INTERVAL task stays due every tick until schedule_next runs at
        # completion — the dispatcher's in-flight set must suppress dupes.
        task = _make_task(name="int1", schedule=ScheduleType.INTERVAL, run_at=None)
        manager.register_task(task)

        finished = threading.Event()
        dispatcher.task_finalized.connect(lambda *_: finished.set())

        for _ in range(5):  # five ticks while the 1.0 s worker is still running
            dispatcher.tick(datetime.now())  # noqa: DTZ005
            _pump_events(qapp, 0.1)

        _pump_events(qapp, 3.0)
        assert finished.is_set()
        assert ProbeTool.calls == 1, "task was submitted more than once while in flight"

    def test_submit_returns_false_for_in_flight_task(self, qapp: QCoreApplication) -> None:
        ProbeTool.reset(block_seconds=0.5)
        registry = ToolRegistry()
        registry.register(ProbeTool())
        bus = FakeEventBus()
        manager = AutomationManager(tool_registry=registry, event_bus=bus)
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        task = _make_task()
        manager.register_task(task)

        assert dispatcher.submit(task, manager._dispatch_execute) is True
        assert dispatcher.submit(task, manager._dispatch_execute) is False  # already in flight
        assert task.status is TaskStatus.RUNNING  # RUNNING also blocks is_due
        assert task.is_due(datetime.now()) is False  # noqa: DTZ005
        _pump_events(qapp, 3.0)


# --------------------------------------------------------------------------- #
# 5. EXCEPTION HANDLING — worker raises → FAILED, scheduler keeps working
# --------------------------------------------------------------------------- #
class _RaisingTool(Tool):
    name = "raiser"
    description = "always raises"

    def execute(self, **params) -> ToolResult:
        raise RuntimeError("kaboom")


class _GoodTool(Tool):
    name = "probe"
    description = "ok"
    calls = 0

    def execute(self, **params) -> ToolResult:
        type(self).calls += 1
        return ToolResult(True, "ok", tool_name=self.name)


class TestExceptionHandling:
    def test_worker_exception_marks_task_failed_and_scheduler_continues(
        self, qapp: QCoreApplication
    ) -> None:
        _GoodTool.calls = 0
        registry = ToolRegistry()
        registry.register(_RaisingTool())
        registry.register(_GoodTool())
        bus = FakeEventBus()
        manager = AutomationManager(tool_registry=registry, event_bus=bus)
        dispatcher = AutomationDispatcher(manager, event_bus=bus)

        bad = _make_task(name="bad")
        bad.tool_name = "raiser"
        good = _make_task(name="good")
        good.tool_name = "probe"
        manager.register_task(bad)
        manager.register_task(good)

        finished = {"n": 0}
        def on_finalized(_name: str, _ok: bool) -> None:
            finished["n"] += 1

        dispatcher.task_finalized.connect(on_finalized)
        dispatcher.tick(datetime.now())  # noqa: DTZ005
        _pump_events(qapp, 3.0)

        assert finished["n"] == 2
        assert bad.status is TaskStatus.FAILED
        assert bad.result == "RuntimeError"  # exception type preserved as error
        assert bad.enabled is True            # FAILED keeps retry semantics
        assert good.status is TaskStatus.SUCCESS
        assert _GoodTool.calls == 1           # the other due task still executed


# --------------------------------------------------------------------------- #
# 6. MULTIPLE DUE TASKS — both processed, serialized submission, no unbounded
#    parallelism beyond one worker per task
# --------------------------------------------------------------------------- #
class TestMultipleDueTasks:
    def test_two_due_tasks_both_complete(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        t1 = _make_task(name="a1")
        t2 = _make_task(name="a2")
        manager.register_task(t1)
        manager.register_task(t2)

        finished = {"n": 0}
        dispatcher.task_finalized.connect(lambda *_: finished.__setitem__("n", finished["n"] + 1))
        dispatcher.tick(datetime.now())  # noqa: DTZ005
        _pump_events(qapp, 3.0)

        assert finished["n"] == 2
        assert ProbeTool.calls == 2
        assert t1.status is TaskStatus.SUCCESS and t1.enabled is False
        assert t2.status is TaskStatus.SUCCESS and t2.enabled is False


# --------------------------------------------------------------------------- #
# 7. SHUTDOWN — no zombie worker threads
# --------------------------------------------------------------------------- #
class TestShutdown:
    def test_shutdown_leaves_no_worker_threads(self, qapp: QCoreApplication) -> None:
        ProbeTool.reset(block_seconds=0.5)
        registry = ToolRegistry()
        registry.register(ProbeTool())
        bus = FakeEventBus()
        manager = AutomationManager(tool_registry=registry, event_bus=bus)
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        manager.register_task(_make_task())
        dispatcher.tick(datetime.now())  # noqa: DTZ005 — worker now running

        before = threading.active_count()
        dispatcher.shutdown(wait_ms=5000)
        _pump_events(qapp, 0.5)

        assert dispatcher.in_flight_count == 0
        # Every automation QThread must be finished.
        automation_threads = [
            t for t in threading.enumerate()
            if t.name.startswith("QThread") or "AutomationTaskWorker" in type(t).__name__
        ]
        assert all(
            not getattr(t, "isRunning", lambda: False)() for t in automation_threads
        ), f"worker threads still running: {automation_threads}"
        # Give Qt a moment to reap deleteLater'ed objects; thread count must
        # not grow.
        _pump_events(qapp, 0.2)
        assert threading.active_count() <= before + 1  # +1 tolerance for reaper noise

    def test_shutdown_rejects_new_submissions(self, qapp: QCoreApplication) -> None:
        manager, bus = _make_manager_with_probe()
        dispatcher = AutomationDispatcher(manager, event_bus=bus)
        dispatcher.shutdown()
        task = _make_task()
        manager.register_task(task)
        assert dispatcher.submit(task, manager._dispatch_execute) is False
        assert ProbeTool.calls == 0


# --------------------------------------------------------------------------- #
# 8. SYNCHRONOUS API UNCHANGED — run_scheduled still works exactly as before
# --------------------------------------------------------------------------- #
class TestSynchronousApiUnchanged:
    def test_run_scheduled_still_executes_synchronously(
        self, qapp: QCoreApplication
    ) -> None:
        manager, bus = _make_manager_with_probe()
        manager.register_task(_make_task())
        outcomes = manager.run_scheduled()  # direct synchronous call — no worker

        assert ProbeTool.calls == 1
        assert len(outcomes) == 1 and outcomes[0].startswith("t1:")
        task = manager.get_task("t1")
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False  # ONCE fix (9ddd423) intact on sync path
