"""Automation task model — scheduled unit of work for the scheduler."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class ScheduleType(str, Enum):
    INTERVAL = "interval"
    ONCE = "once"
    CRON = "cron"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    DISABLED = "disabled"


@dataclass
class AutomationTask:
    """A task scheduled for periodic or one-shot execution.

    Tasks run through the secured :class:`ToolRegistry`, so Security Layer
    ASK/DENY policies still apply.
    """

    name: str
    tool_name: str
    params: dict[str, Any] = field(default_factory=dict)
    schedule: ScheduleType = ScheduleType.INTERVAL
    interval_seconds: float = 60.0
    run_at: datetime | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    target_type: str = "tool"
    description: str = ""

    def is_due(self, now: datetime) -> bool:
        if not self.enabled:
            return False
        if self.status == TaskStatus.RUNNING:
            return False
        if self.run_at is not None:
            return now >= self.run_at
        if self.next_run is not None:
            return now >= self.next_run
        return True

    def schedule_next(self, now: datetime) -> None:
        if self.schedule == ScheduleType.ONCE:
            self.next_run = None
            # A successfully completed one-shot must never auto-run again.
            # Keep status=SUCCESS (do NOT call disable() — it would overwrite
            # the SUCCESS status with DISABLED) and keep run_at intact for
            # display purposes; only the enabled flag flips to False.
            if self.status == TaskStatus.SUCCESS:
                self.enabled = False
        elif self.schedule == ScheduleType.INTERVAL:
            self.next_run = now + timedelta(seconds=self.interval_seconds)
        else:
            self.next_run = now + timedelta(seconds=self.interval_seconds)

    def disable(self) -> TaskStatus:
        self.enabled = False
        self.status = TaskStatus.DISABLED
        return self.status

    def to_dict(self) -> dict[str, Any]:
        """Serialize task to a persistence-safe dictionary.

        Runtime fields (last_run, next_run, status, result) are excluded —
        they are reconstructed on load.
        """
        return {
            "name": self.name,
            "target_type": self.target_type,
            "tool_name": self.tool_name,
            "params": self.params,
            "schedule": self.schedule.value,
            "interval_seconds": self.interval_seconds,
            "run_at": self.run_at.isoformat() if self.run_at else None,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutomationTask:
        """Reconstruct an AutomationTask from a persisted dictionary."""
        schedule_val = data.get("schedule", ScheduleType.INTERVAL.value)
        try:
            schedule = ScheduleType(schedule_val)
        except ValueError:
            schedule = ScheduleType.INTERVAL

        run_at_raw = data.get("run_at")
        run_at: datetime | None = None
        if run_at_raw is not None:
            try:
                run_at = datetime.fromisoformat(run_at_raw)
            except (ValueError, TypeError):
                run_at = None

        return cls(
            name=data.get("name", ""),
            tool_name=data.get("tool_name", ""),
            params=data.get("params", {}),
            schedule=schedule,
            interval_seconds=data.get("interval_seconds", 60.0),
            run_at=run_at,
            enabled=data.get("enabled", True),
            target_type=data.get("target_type", "tool"),
            description=data.get("description", ""),
        )
