"""Regression tests for ONCE automation task semantics.

Locks the contract established after the re-execution bug fix:

* A SUCCESSFUL one-shot (ONCE) task must never automatically run again —
  ``schedule_next()`` disables it (``enabled=False``) while preserving
  ``status=SUCCESS`` and the original ``run_at``.
* FAILED / BLOCKED ONCE tasks keep their existing (retry) semantics —
  unchanged by the fix, locked here as control tests.
* INTERVAL tasks are unaffected by the fix.

The bug: ``is_due()`` evaluates ``run_at`` without consulting terminal
status, and ``schedule_next()`` used to clear only ``next_run`` for ONCE
tasks — a completed one-shot stayed ``enabled`` with a past ``run_at`` and
re-executed on every scheduler tick (and once more after every restart,
because ``enabled`` is persisted while ``status`` is reconstructed as
PENDING).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from automation.manager import AutomationManager
from automation.scheduler import StubScheduler
from automation.task import AutomationTask, ScheduleType, TaskStatus
from tools.base import ToolResult


# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #
class FakeToolRegistry:
    """Minimal registry stand-in: counts executions, returns preset results."""

    def __init__(self, outcomes: list[ToolResult] | None = None) -> None:
        self.calls = 0
        self._outcomes = outcomes or [ToolResult(True, "ok", tool_name="x")]

    def execute(self, name: str, params: dict) -> ToolResult:
        result = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        return result


class FakeEventBus:
    """No-op event bus (avoids Qt/EventBus dependencies in unit tests)."""

    def publish(self, event_type: str, data: dict | None = None) -> None:  # noqa: ARG002
        pass


def _make_once_task(run_at: datetime) -> AutomationTask:
    return AutomationTask(
        name="once-test",
        tool_name="calculate",
        params={"expression": "1+1"},
        schedule=ScheduleType.ONCE,
        run_at=run_at,
    )


@pytest.fixture()
def past_run_at() -> datetime:
    return datetime.now() - timedelta(minutes=5)  # noqa: DTZ005


@pytest.fixture()
def now() -> datetime:
    return datetime.now()  # noqa: DTZ005


# --------------------------------------------------------------------------- #
# 1. CORE SUCCESS REPRODUCTION
# --------------------------------------------------------------------------- #
class TestOnceSuccessExecutesExactlyOnce:
    def test_first_tick_executes_exactly_once_and_disables(
        self, past_run_at: datetime, now: datetime
    ) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)

        assert task.is_due(now) is True  # initially due (run_at in the past)
        scheduler.tick(registry, now=now)

        assert registry.calls == 1
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False
        assert task.next_run is None
        assert task.run_at == past_run_at  # run_at preserved verbatim

    def test_second_tick_does_not_execute_again(
        self, past_run_at: datetime, now: datetime
    ) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)

        scheduler.tick(registry, now=now)
        scheduler.tick(registry, now=now + timedelta(seconds=2))
        scheduler.tick(registry, now=now + timedelta(minutes=10))

        assert registry.calls == 1  # never more than the single execution


# --------------------------------------------------------------------------- #
# 2. is_due CONTRACT
# --------------------------------------------------------------------------- #
class TestIsDueContract:
    def test_successful_once_task_is_not_due(self, past_run_at: datetime, now: datetime) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)
        scheduler.tick(registry, now=now)

        assert task.is_due(now + timedelta(seconds=1)) is False
        assert task.is_due(now + timedelta(days=365)) is False

    def test_pending_once_task_with_future_run_at_is_not_due_yet(self, now: datetime) -> None:
        task = _make_once_task(now + timedelta(hours=1))
        assert task.is_due(now) is False


# --------------------------------------------------------------------------- #
# 3. RESTART / PERSISTENCE
# --------------------------------------------------------------------------- #
class TestRestartPersistence:
    def test_completed_once_task_does_not_run_after_save_load_tick(
        self, past_run_at: datetime, now: datetime, tmp_path: Path
    ) -> None:
        import json

        registry = FakeToolRegistry()
        manager = AutomationManager(
            tool_registry=registry, event_bus=FakeEventBus()
        )
        task = _make_once_task(past_run_at)
        manager.register_task(task)
        manager.run_scheduled(now=now)

        assert registry.calls == 1
        assert task.enabled is False

        # Persist, then simulate an application restart: fresh manager,
        # fresh registry, load persisted state, tick again.
        persist_path = tmp_path / "tasks.json"
        manager.save_tasks(persist_path)
        with persist_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        assert raw["tasks"][0]["enabled"] is False  # persisted disabled

        manager2 = AutomationManager(
            tool_registry=FakeToolRegistry(), event_bus=FakeEventBus()
        )
        loaded = manager2.load_tasks(persist_path)
        assert loaded == 1

        registry2 = FakeToolRegistry()
        manager2._registry = registry2  # swap in a fresh counting registry
        outcomes = manager2.run_scheduled(now=now + timedelta(seconds=2))
        assert registry2.calls == 0  # not re-executed after restart
        assert outcomes == []

    def test_load_reconstructs_disabled_state(self, past_run_at: datetime, now: datetime) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)
        scheduler.tick(registry, now=now)

        saved = scheduler.save_tasks()
        assert saved[0]["enabled"] is False

        scheduler2 = StubScheduler(event_bus=FakeEventBus())
        scheduler2.load_tasks(saved)
        restored = scheduler2.get_task("once-test")
        assert restored is not None
        assert restored.enabled is False
        assert restored.is_due(now + timedelta(seconds=5)) is False


# --------------------------------------------------------------------------- #
# 4. run_task_now() PATH (Run Now button)
# --------------------------------------------------------------------------- #
class TestRunTaskNowPath:
    def test_run_task_now_disables_after_success(
        self, past_run_at: datetime, now: datetime
    ) -> None:
        registry = FakeToolRegistry()
        manager = AutomationManager(
            tool_registry=registry, event_bus=FakeEventBus()
        )
        task = _make_once_task(past_run_at)
        manager.register_task(task)

        result = manager.run_task_now("once-test", now=now)

        assert result.success is True
        assert registry.calls == 1
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False
        assert task.next_run is None
        assert task.run_at == past_run_at

    def test_subsequent_tick_after_run_now_does_not_reexecute(
        self, past_run_at: datetime, now: datetime
    ) -> None:
        registry = FakeToolRegistry()
        manager = AutomationManager(
            tool_registry=registry, event_bus=FakeEventBus()
        )
        task = _make_once_task(past_run_at)
        manager.register_task(task)

        manager.run_task_now("once-test", now=now)
        outcomes = manager.run_scheduled(now=now + timedelta(seconds=2))

        assert registry.calls == 1
        assert outcomes == []


# --------------------------------------------------------------------------- #
# 5. FAILED ONCE CONTROL (semantics preserved — NOT changed by the fix)
# --------------------------------------------------------------------------- #
class TestFailedOnceControl:
    def test_failed_once_task_stays_enabled_and_due(self, past_run_at: datetime, now: datetime) -> None:
        registry = FakeToolRegistry(
            outcomes=[ToolResult(False, "", tool_name="x", error="Boom")]
        )
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)

        scheduler.tick(registry, now=now)

        assert task.status is TaskStatus.FAILED
        assert task.enabled is True  # unchanged: failure keeps the retry path
        assert task.is_due(now + timedelta(seconds=1)) is True


# --------------------------------------------------------------------------- #
# 6. BLOCKED ONCE CONTROL (semantics preserved — NOT changed by the fix)
# --------------------------------------------------------------------------- #
class TestBlockedOnceControl:
    def test_blocked_once_task_stays_enabled_and_due(self, past_run_at: datetime, now: datetime) -> None:
        registry = FakeToolRegistry(
            outcomes=[ToolResult(False, "", tool_name="x", error="ConfirmationRequired")]
        )
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)

        scheduler.tick(registry, now=now)

        assert task.status is TaskStatus.BLOCKED
        assert task.enabled is True  # unchanged: blocked keeps the retry path
        assert task.is_due(now + timedelta(seconds=1)) is True


# --------------------------------------------------------------------------- #
# 7. INTERVAL CONTROL (unaffected by the fix)
# --------------------------------------------------------------------------- #
class TestIntervalControl:
    def test_interval_task_runs_only_when_interval_elapsed(self, now: datetime) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = AutomationTask(
            name="interval-test",
            tool_name="calculate",
            params={},
            schedule=ScheduleType.INTERVAL,
            interval_seconds=60,
        )
        scheduler.register(task)

        scheduler.tick(registry, now=now)  # newly registered → due immediately
        scheduler.tick(registry, now=now + timedelta(seconds=30))  # not due yet
        assert registry.calls == 1

        scheduler.tick(registry, now=now + timedelta(seconds=61))  # due again
        assert registry.calls == 2
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is True  # INTERVAL tasks are never auto-disabled


# --------------------------------------------------------------------------- #
# 8. RE-ENABLE / MANUAL RE-RUN (existing UI re-enable semantics)
# --------------------------------------------------------------------------- #
class TestReEnableManualRun:
    def test_reenabled_once_task_runs_once_more_then_disables_again(
        self, past_run_at: datetime, now: datetime
    ) -> None:
        registry = FakeToolRegistry()
        scheduler = StubScheduler(event_bus=FakeEventBus())
        task = _make_once_task(past_run_at)
        scheduler.register(task)

        scheduler.tick(registry, now=now)  # first completed execution
        assert task.enabled is False

        # Existing application re-enable semantics (ui/main_window.py
        # _on_task_enabled_changed): enabled=True, status=PENDING,
        # next_run reset to now.
        task.enabled = True
        task.status = TaskStatus.PENDING
        task.next_run = now

        assert task.is_due(now) is True
        scheduler.tick(registry, now=now)  # second (manual) execution
        assert registry.calls == 2
        assert task.status is TaskStatus.SUCCESS
        assert task.enabled is False  # disabled again after its second run

        scheduler.tick(registry, now=now + timedelta(seconds=5))
        assert registry.calls == 2  # and stays dormant afterwards
