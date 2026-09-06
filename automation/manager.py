"""Automation manager — ties scheduler, workflows, and tools together."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from automation.scheduler import StubScheduler
from automation.task import TaskStatus
from automation.workflow import Workflow
from core.logger import get_logger

if TYPE_CHECKING:
    from automation.task import AutomationTask
    from core.event_bus import EventBus
    from tools.base import ToolRegistry, ToolResult

logger = get_logger("automation")


class AutomationManager:
    """Registers scheduled tasks and named workflows, then drives them."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        event_bus: EventBus,
        scheduler: StubScheduler | None = None,
    ) -> None:
        self._registry = tool_registry
        self._event_bus = event_bus
        self._scheduler = scheduler or StubScheduler(event_bus)
        self._workflows: dict[str, Workflow] = {}
        self._task_history: list[dict[str, Any]] = []

    @property
    def scheduler(self) -> StubScheduler:
        return self._scheduler

    def register_task(self, task: AutomationTask) -> AutomationTask:
        return self._scheduler.register(task)

    def register_workflow(self, workflow: Workflow | str, definition: Any = None) -> Workflow:
        if isinstance(workflow, str):
            if definition is None:
                raise ValueError("Workflow definition (list[dict]) required when name is a string")
            workflow = Workflow.of(workflow, definition, event_bus=self._event_bus)
        self._workflows[workflow.name] = workflow
        logger.info("Registered workflow '%s' (%d steps)", workflow.name, len(workflow))
        return workflow

    def list_workflows(self) -> list[str]:
        return list(self._workflows.keys())

    def get_workflow(self, name: str) -> Workflow | None:
        return self._workflows.get(name)

    def list_tasks(self) -> list[str]:
        return [t.name for t in self._scheduler.tasks]

    def get_task(self, name: str) -> AutomationTask | None:
        """Return a registered task by name, or None."""
        return self._scheduler.get_task(name)

    def unregister_task(self, name: str) -> None:
        """Remove a scheduled task. Safe to call for non-existent tasks."""
        self._scheduler.unregister(name)
        if self._event_bus is not None:
            self._event_bus.publish(
                "AUTOMATION_TASK_DELETED", data={"task": name}
            )

    def update_task(self, task: AutomationTask) -> AutomationTask:
        """Replace an existing task or register a new one."""
        self._scheduler.update_task(task)
        if self._event_bus is not None:
            self._event_bus.publish(
                "AUTOMATION_TASK_UPDATED",
                data={"task": task.name, "target_type": task.target_type},
            )
        return task

    def run_workflow(self, name: str) -> str:
        workflow = self._workflows.get(name)
        if workflow is None:
            return f"No workflow '{name}'. Available: {', '.join(self.list_workflows()) or 'none'}"
        if not workflow.enabled:
            return f"Workflow '{name}' is disabled."
        results = workflow.run(self._registry)
        executed = sum(1 for r in results if r.success)
        blocked = sum(1 for r in results if r.error == "ConfirmationRequired")
        self._task_history.append({
            "workflow": name,
            "executed": executed,
            "blocked": blocked,
            "failed": len(results) - executed - blocked,
            "timestamp": datetime.now(UTC).isoformat(),
        })
        return f"Workflow '{name}': {executed} succeeded, {blocked} blocked, {len(results) - executed - blocked} failed"

    def run_scheduled(self, now: datetime | None = None) -> list[str]:
        """Execute all due tasks through the scheduler.

        Workflow-targeted tasks are dispatched to ``run_workflow`` so they
        reuse the existing secured execution path.  Tool-targeted tasks use
        the scheduler's default ``execute`` (direct ``ToolRegistry.execute``).
        """
        def _execute(task: AutomationTask, registry: ToolRegistry):
            if task.target_type == "workflow":
                return self._execute_workflow_task(task, registry)
            return self._scheduler.execute(task, registry)

        outcomes = self._scheduler.tick(self._registry, now, execute_fn=_execute)
        return [f"{t.name}: {outcome}" for t, outcome in outcomes]

    def _execute_workflow_task(self, task: AutomationTask, registry: ToolRegistry):
        """Execute a workflow-targeted task through the secured registry.

        Never raises — returns a ToolResult-compatible error on failure.
        """
        from tools.base import ToolResult

        task.status = TaskStatus.RUNNING
        workflow = self._workflows.get(task.tool_name)
        if workflow is None:
            return ToolResult(
                False, f"Workflow '{task.tool_name}' not found",
                tool_name=task.tool_name, error="WorkflowNotFound",
            )
        if not workflow.enabled:
            return ToolResult(
                False, f"Workflow '{task.tool_name}' is disabled",
                tool_name=task.tool_name, error="WorkflowDisabled",
            )
        try:
            results = workflow.run(registry)
            executed = sum(1 for r in results if r.success)
            failed = sum(1 for r in results if not r.success and r.error != "ConfirmationRequired")
            blocked = sum(1 for r in results if r.error == "ConfirmationRequired")

            if blocked > 0:
                return ToolResult(
                    False,
                    f"{executed} ok, {blocked} blocked, {failed} failed",
                    tool_name=task.tool_name, error="ConfirmationRequired",
                )
            if failed > 0:
                return ToolResult(
                    False,
                    f"{executed} ok, {failed} failed",
                    tool_name=task.tool_name, error="ExecutionFailed",
                )
            return ToolResult(
                True,
                f"{executed} step(s) completed",
                tool_name=task.tool_name,
            )
        except Exception as exc:
            logger.exception("Workflow task '%s' execution raised", task.name)
            return ToolResult(False, str(exc), tool_name=task.tool_name, error=type(exc).__name__)

    def run_task_now(self, name: str, now: datetime | None = None) -> ToolResult:
        """Execute a single scheduled task immediately (Run Now).

        Reuses the same execution dispatch as :meth:`run_scheduled` so that
        workflow and tool targets both flow through the secured registry.
        Updates the task's runtime state (``status``, ``last_run``, ``result``,
        ``next_run``) consistently with scheduler semantics.

        Returns a :class:`ToolResult` describing the outcome.
        """
        from tools.base import ToolResult

        now = now or datetime.now()  # noqa: DTZ005
        task = self._scheduler.get_task(name)
        if task is None:
            return ToolResult(
                False, f"Task '{name}' not found",
                tool_name=name, error="TaskNotFound",
            )

        if not task.enabled:
            return ToolResult(
                False, f"Task '{name}' is disabled",
                tool_name=task.tool_name, error="TaskDisabled",
            )

        def _execute(t: AutomationTask, registry: ToolRegistry):
            if t.target_type == "workflow":
                return self._execute_workflow_task(t, registry)
            return self._scheduler.execute(t, registry)

        result = _execute(task, self._registry)
        if result.success:
            task.status = TaskStatus.SUCCESS
        elif result.error == "ConfirmationRequired":
            task.status = TaskStatus.BLOCKED
        else:
            task.status = TaskStatus.FAILED
        task.result = result.message if result.success else (result.error or "neuspeh")
        task.last_run = now
        task.schedule_next(now)
        if self._event_bus is not None:
            self._event_bus.publish(
                "AUTOMATION_TASK_COMPLETED",
                data={"task": task.name, "success": result.success},
            )
        return result

    def tick(self, now: datetime | None = None) -> list[str]:
        return self.run_scheduled(now)

    @property
    def task_history(self) -> list[dict[str, Any]]:
        return list(self._task_history)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    _PERSISTENCE_VERSION = 1

    def save_file(self, path: str | Path) -> None:
        """Save user workflows to a JSON file for persistence.

        Excludes the built-in system_check workflow.
        Uses atomic write: writes to temp file then renames to target.
        """
        import os

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        user_workflows = [
            w.to_dict()
            for w in self._workflows.values()
            if w.name != "system_check"
        ]

        data = {
            "version": self._PERSISTENCE_VERSION,
            "workflows": user_workflows,
        }

        fd, temp_path = tempfile.mkstemp(
            dir=path_obj.parent, prefix=".wf_temp_", suffix=".json"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(temp_path).replace(path_obj)
        except Exception:
            os.unlink(temp_path)
            raise

    def load_file(self, path: str | Path) -> int:
        """Load user workflows from a JSON file.

        Skips the built-in 'system_check' workflow if present.
        Returns the number of user workflows successfully loaded.
        Does not crash on missing or malformed files.
        """
        path_obj = Path(path)

        if not path_obj.exists():
            return 0

        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse workflow persistence file %s: %s", path_obj, e)
            return 0

        if not isinstance(data, dict):
            logger.warning("Invalid workflow persistence format in %s", path_obj)
            return 0

        workflows_data = data.get("workflows", [])
        if not isinstance(workflows_data, list):
            logger.warning("Invalid workflows list in persistence file %s", path_obj)
            return 0

        loaded = 0
        for wf_data in workflows_data:
            if not isinstance(wf_data, dict):
                continue

            wf_name = wf_data.get("name", "")
            if not wf_name:
                continue

            if wf_name == "system_check":
                logger.debug("Skipping built-in workflow 'system_check' during load")
                continue

            try:
                workflow = Workflow.from_dict(wf_data, event_bus=self._event_bus)

                if workflow.name in self._workflows:
                    logger.debug(
                        "Workflow '%s' already exists, overwriting", workflow.name
                    )

                self._workflows[workflow.name] = workflow
                loaded += 1
            except Exception as e:
                logger.warning(
                    "Failed to load workflow '%s': %s", wf_name, e
                )

        return loaded

    # ------------------------------------------------------------------ #
    # Scheduled Task Persistence
    # ------------------------------------------------------------------ #
    def save_tasks(self, path: str | Path) -> None:
        """Save scheduled tasks to a JSON file for persistence.

        Uses atomic write: writes to temp file then renames to target.
        Runtime fields (last_run, next_run, status, result) are excluded.
        """
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)

        task_dicts = self._scheduler.save_tasks()
        data = {
            "version": self._PERSISTENCE_VERSION,
            "tasks": task_dicts,
        }

        fd, temp_path = tempfile.mkstemp(
            dir=path_obj.parent, prefix=".task_temp_", suffix=".json"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(temp_path).replace(path_obj)
        except Exception:
            os.unlink(temp_path)
            raise

    def load_tasks(self, path: str | Path) -> int:
        """Load scheduled tasks from a JSON file.

        Returns the number of tasks successfully loaded.
        Does not crash on missing or malformed files.
        """
        path_obj = Path(path)

        if not path_obj.exists():
            return 0

        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse tasks persistence file %s: %s", path_obj, e)
            return 0

        if not isinstance(data, dict):
            logger.warning("Invalid tasks persistence format in %s", path_obj)
            return 0

        tasks_data = data.get("tasks", [])
        if not isinstance(tasks_data, list):
            logger.warning("Invalid tasks list in persistence file %s", path_obj)
            return 0

        return self._scheduler.load_tasks(tasks_data)
