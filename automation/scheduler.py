"""Scheduler — in-memory interval/one-shot scheduler (APscheduler optional).

When ``APScheduler`` or ``croniter`` are unavailable the scheduler falls back to
simple interval scheduling, still fully functional offline.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from automation.task import AutomationTask, TaskStatus
from core.logger import get_logger

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from tools.base import ToolRegistry, ToolResult

logger = get_logger("automation")

try:
    import croniter as _croniter
except ImportError:  # pragma: no cover - optional dependency
    _croniter = None


class StubScheduler:
    """Lightweight scheduler storing tasks in memory."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._event_bus = event_bus
        self._tasks: list[AutomationTask] = []
        self._lock = threading.RLock()
        self._tick_active = False

    @property
    def tasks(self) -> list[AutomationTask]:
        return list(self._tasks)

    def register(self, task: AutomationTask) -> AutomationTask:
        with self._lock:
            task.next_run = task.next_run or task.run_at or datetime.now()  # noqa: DTZ005
            self._tasks.append(task)
            if self._event_bus is not None:
                self._event_bus.publish(
                    "AUTOMATION_TASK_SCHEDULED",
                    data={"task": task.name, "schedule": task.schedule.value},
                )
            logger.info("Scheduled automation task '%s' (%s)", task.name, task.schedule.value)
            return task

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tasks = [t for t in self._tasks if t.name != name]

    def get_task(self, name: str) -> AutomationTask | None:
        """Return a task by name, or None if not found."""
        with self._lock:
            for t in self._tasks:
                if t.name == name:
                    return t
            return None

    def update_task(self, task: AutomationTask) -> None:
        """Replace an existing task with the same name, or register if new."""
        with self._lock:
            for i, t in enumerate(self._tasks):
                if t.name == task.name:
                    self._tasks[i] = task
                    return
            self.register(task)

    def save_tasks(self) -> list[dict[str, Any]]:
        """Return all tasks as persistence-safe dictionaries."""
        with self._lock:
            return [t.to_dict() for t in self._tasks]

    def load_tasks(self, task_dicts: list[dict[str, Any]]) -> int:
        """Restore tasks from persisted dictionaries. Returns count loaded."""
        with self._lock:
            loaded = 0
            for td in task_dicts:
                if not isinstance(td, dict):
                    continue
                tname = td.get("name", "")
                if not tname:
                    continue
                try:
                    task = AutomationTask.from_dict(td)
                except Exception:
                    logger.warning("Failed to load task '%s' from persistence", tname, exc_info=True)
                    continue
                self.unregister(tname)
                self.register(task)
                loaded += 1
            return loaded

    def due(self, now: datetime | None = None) -> list[AutomationTask]:
        with self._lock:
            now = now or datetime.now()  # noqa: DTZ005
            return [t for t in self._tasks if t.is_due(now)]

    def tick(
        self,
        tool_registry: ToolRegistry,
        now: datetime | None = None,
        execute_fn: Callable[[AutomationTask, ToolRegistry], ToolResult] | None = None,
    ) -> list[tuple[AutomationTask, str]]:
        """Execute all due tasks. Returns ``(task, outcome)`` pairs.

        :param execute_fn: Optional custom execution function. When ``None``,
            falls back to :meth:`execute` (tool-name based).  The
            :class:`AutomationManager` passes a custom function that dispatches
            workflow-targeted tasks to ``run_workflow`` while keeping tool
            tasks on the standard secured path.

        Thread-safe: Uses a reentrant lock to prevent concurrent tick execution.
        Re-entry protection: Returns early if a tick is already in progress.
        """
        with self._lock:
            # Re-entry protection: if tick is already running, skip this call
            if self._tick_active:
                logger.debug("Scheduler tick skipped — re-entry detected")
                return []
            self._tick_active = True

        try:
            now = now or datetime.now()  # noqa: DTZ005
            if self._event_bus is not None:
                self._event_bus.publish(
                    "SCHEDULER_TICK", data={"now": now.isoformat(), "due": len(self.due(now))}
                )

            exec_fn = execute_fn or StubScheduler.execute
            outcomes: list[tuple[AutomationTask, str]] = []
            
            # Get due tasks while holding the lock, then release for execution
            with self._lock:
                due_tasks = self.due(now)
            
            for task in due_tasks:
                result = exec_fn(task, tool_registry)
                if result.success:
                    task.status = TaskStatus.SUCCESS
                    task.result = result.message or ""
                elif result.error == "ConfirmationRequired":
                    task.status = TaskStatus.BLOCKED
                    task.result = "ConfirmationRequired"
                else:
                    task.status = TaskStatus.FAILED
                    task.result = result.error or ""
                task.last_run = now
                task.schedule_next(now)
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "AUTOMATION_TASK_COMPLETED",
                        data={"task": task.name, "success": result.success},
                    )
                outcomes.append((task, task.result or ""))
            return outcomes
        finally:
            with self._lock:
                self._tick_active = False

    @staticmethod
    def execute(task: AutomationTask, tool_registry: ToolRegistry):
        """Run one task through the secured registry. Never raises."""
        from tools.base import ToolResult

        task.status = TaskStatus.RUNNING
        try:
            return tool_registry.execute(task.tool_name, task.params or {})
        except Exception as exc:
            logger.exception("Task '%s' execution raised", task.name)
            return ToolResult(False, "", tool_name=task.tool_name, error=str(exc))
