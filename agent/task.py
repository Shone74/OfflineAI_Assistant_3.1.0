"""Agent task model — discrete unit of work in an agent plan."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """A single executable step discovered by the :class:`Planner`."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    description: str = ""
    tool_name: str | None = None
    params: dict[str, Any] | None = None
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None

    @classmethod
    def of(
        cls,
        description: str,
        tool_name: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Task:
        return cls(description=description, tool_name=tool_name, params=params or {})
