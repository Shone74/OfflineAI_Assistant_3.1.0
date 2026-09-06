"""Off-GUI-thread execution for scheduled automation tasks.

The application's scheduler tick is driven by a QTimer on the GUI thread
(see :meth:`app.application.ApplicationManager._tick_automation`).  Due
evaluation must stay there — it is a cheap ``is_due`` scan — but the actual
task execution (tool runs, workflows) can block for seconds or minutes, and
running it on the GUI thread freezes the whole UI (verified by runtime
reproduction: a 1.5 s tool stalled all GUI event processing for its duration).

This module provides the minimal bridge, following the project's established
QThread-worker convention (cf. ``ui.main_window.GenerationWorker``,
``app.application._StartupModelLoadWorker``, ``ui.models_page.ModelLoadWorker``):

* :class:`AutomationTaskWorker` — a QThread running exactly one
  ``execute_fn(task, registry)`` call off the GUI thread and reporting the
  outcome through a Qt signal.  It never touches Qt widgets and never
  publishes to the EventBus.
* :class:`AutomationDispatcher` — a QObject living on the GUI thread.  It
  receives due tasks from the timer tick, submits each to a worker, and
  finalizes the task state (status, ``last_run``, ``schedule_next()``,
  EventBus publication) back on the GUI thread via queued signal delivery.
  EventBus subscribers therefore always see automation events published from
  the GUI thread — the same threading contract as the previous synchronous
  implementation.

In-flight protection: a task that is currently executing on a worker is
never submitted twice — the dispatcher keeps an in-flight set and marks the
task ``RUNNING`` immediately on submit, so both the dispatcher guard and the
scheduler's ``is_due`` (which returns False for RUNNING tasks) prevent
duplicate submissions while a previous execution is still in flight.

Shutdown: :meth:`AutomationDispatcher.shutdown` waits (bounded) for running
workers so no zombie QThreads outlive the application.  A task interrupted
by shutdown simply keeps its persisted identity (``status`` is not persisted)
and runs again on the next application start — the same semantics a
synchronous task interrupted mid-run always had.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot

from automation.task import TaskStatus
from core.logger import get_logger

if TYPE_CHECKING:
    from automation.manager import AutomationManager
    from automation.task import AutomationTask
    from core.event_bus import EventBus
    from tools.base import ToolRegistry, ToolResult

logger = get_logger("automation.worker")


class AutomationTaskWorker(QThread):
    """Runs one ``execute_fn(task, registry)`` call off the GUI thread.

    Mirrors the project's worker conventions: the blocking operation runs in
    ``run()`` and the outcome is reported via a Qt signal; no Qt widget is
    touched and no EventBus event is published from the worker thread.
    """

    task_finished = Signal(str, bool, str, str)  # task_name, success, message, error

    def __init__(
        self,
        task_name: str,
        execute_fn: Callable[[AutomationTask, ToolRegistry], ToolResult],
        task: AutomationTask,
        registry: ToolRegistry,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._task_name = task_name
        self._execute_fn = execute_fn
        self._task = task
        self._registry = registry

    def run(self) -> None:
        try:
            result: Any = self._execute_fn(self._task, self._registry)
            success = bool(getattr(result, "success", False))
            message = str(getattr(result, "message", "") or "")
            error = str(getattr(result, "error", "") or "")
        except Exception as exc:
            logger.exception("Automation worker '%s' raised", self._task_name)
            success, message, error = False, "", type(exc).__name__
        self.task_finished.emit(self._task_name, success, message, error)


class AutomationDispatcher(QObject):
    """GUI-thread coordinator for off-thread automation task execution.

    Lives on the GUI thread.  The application's QTimer tick calls
    :meth:`tick`, which asks the :class:`~automation.manager.AutomationManager`
    to due-evaluate synchronously (cheap) and submit every due task to a
    worker.  Completion returns to this object via a queued connection, and
    all task state mutation (status, ``last_run``, ``schedule_next``) plus
    the EventBus publication happen here on the GUI thread.
    """

    task_finalized = Signal(str, bool)  # task_name, success

    def __init__(
        self,
        automation_manager: AutomationManager,
        event_bus: EventBus | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._am = automation_manager
        self._event_bus = event_bus
        self._in_flight: dict[str, datetime] = {}  # task name -> submitted-at
        self._workers: dict[str, AutomationTaskWorker] = {}
        self._accepting = True

    # ------------------------------------------------------------------ #
    # Submission (called on the GUI thread by the scheduler timer tick)
    # ------------------------------------------------------------------ #
    def tick(self, now: datetime | None = None) -> None:
        """Due-evaluate and submit due tasks. Never blocks on task work."""
        if not self._accepting:
            return
        try:
            self._am.run_scheduled_dispatch(self, now)
        except Exception:
            logger.exception("Automation dispatcher tick failed")

    def is_in_flight(self, task_name: str) -> bool:
        return task_name in self._in_flight

    # ------------------------------------------------------------------ #
    # Run Now (called on the GUI thread by the Automation dashboard)
    # ------------------------------------------------------------------ #
    def run_now(self, name: str, now: datetime | None = None) -> bool:
        """Submit a task for immediate off-GUI-thread execution ("Run Now").

        Performs the same lightweight pre-checks as the synchronous
        ``AutomationManager.run_task_now`` (unknown task, disabled task) and
        additionally rejects duplicate submissions while the task is already
        in flight (whether started by the scheduler tick or a previous Run
        Now).  The actual execution, completion finalization, and shutdown
        behavior all reuse the existing :meth:`submit` / worker /
        ``_on_task_finished`` infrastructure — no second worker path exists.

        Returns ``True`` when a new execution was submitted; ``False`` when
        the request was rejected (unknown/disabled/in-flight/shutting down).
        """
        task = self._am.get_task(name)
        if task is None:
            logger.info("Run Now rejected — task '%s' not found", name)
            return False
        if not task.enabled:
            logger.info("Run Now rejected — task '%s' is disabled", name)
            return False
        if not self._accepting:
            logger.info("Run Now rejected — dispatcher is shutting down")
            return False
        if self.is_in_flight(name):
            logger.info("Run Now rejected — task '%s' is already running", name)
            return False
        return self.submit(task, self._am._dispatch_execute, now)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def submit(
        self,
        task: AutomationTask,
        execute_fn: Callable[[AutomationTask, ToolRegistry], ToolResult],
        now: datetime | None = None,
    ) -> bool:
        """Submit *task* for worker-thread execution.

        Returns ``True`` when the task was submitted, ``False`` when it was
        skipped (already in flight, or the dispatcher is shutting down).

        The task is marked ``RUNNING`` immediately so that the scheduler's
        own ``is_due`` (which returns False for RUNNING tasks) also rejects
        duplicate submissions between timer ticks.
        """
        if not self._accepting:
            return False
        if task.name in self._in_flight:
            return False
        task.status = TaskStatus.RUNNING
        self._in_flight[task.name] = now or datetime.now()  # noqa: DTZ005

        registry = self._am.tool_registry
        worker = AutomationTaskWorker(task.name, execute_fn, task, registry)
        self._workers[task.name] = worker
        # Cross-thread signal → queued delivery to this GUI-thread receiver.
        worker.task_finished.connect(
            self._on_task_finished, Qt.ConnectionType.QueuedConnection
        )
        worker.finished.connect(worker.deleteLater)
        logger.debug("Automation task '%s' submitted to worker", task.name)
        worker.start()
        return True

    # ------------------------------------------------------------------ #
    # Completion (delivered on the GUI thread via queued connection)
    # ------------------------------------------------------------------ #
    @Slot(str, bool, str, str)
    def _on_task_finished(self, name: str, success: bool, message: str, error: str) -> None:
        """Finalize one completed task on the GUI thread.

        Applies the same status/``schedule_next`` semantics as the
        synchronous ``StubScheduler.tick`` completion block, using the
        submission time as the scheduling reference (matching the
        synchronous tick's ``now``).
        """
        started_at = self._in_flight.pop(name, None)
        self._workers.pop(name, None)
        task = self._am.get_task(name)
        if task is not None and started_at is not None:
            self._finalize(task, success, message, error, started_at)
        self.task_finalized.emit(name, success)

    def _finalize(
        self,
        task: AutomationTask,
        success: bool,
        message: str,
        error: str,
        now: datetime,
    ) -> None:
        if success:
            task.status = TaskStatus.SUCCESS
            task.result = message or ""
        elif error == "ConfirmationRequired":
            task.status = TaskStatus.BLOCKED
            task.result = "ConfirmationRequired"
        else:
            task.status = TaskStatus.FAILED
            task.result = error or ""
        task.last_run = now
        task.schedule_next(now)
        if self._event_bus is not None:
            self._event_bus.publish(
                "AUTOMATION_TASK_COMPLETED",
                data={"task": task.name, "success": success},
            )

    # ------------------------------------------------------------------ #
    # Shutdown
    # ------------------------------------------------------------------ #
    def shutdown(self, wait_ms: int = 5000) -> None:
        """Stop accepting submissions and wait (bounded) for running workers.

        Workers are plain QThreads running cooperative Python code — they
        finish their current task and exit; ``terminate()`` is never used
        (the same policy as the model-load worker teardown).  A task still
        running after the bounded wait keeps its persisted identity and
        simply runs again on the next application start, because runtime
        fields (status/next_run) are excluded from task persistence.
        """
        self._accepting = False
        for name, worker in list(self._workers.items()):
            if worker.isRunning():
                logger.info("Waiting for automation worker '%s' to finish", name)
                if not worker.wait(wait_ms):
                    logger.warning(
                        "Automation worker '%s' did not finish within %d ms", name, wait_ms
                    )
            self._workers.pop(name, None)
            self._in_flight.pop(name, None)
        logger.info("Automation dispatcher shut down (workers cleared)")
