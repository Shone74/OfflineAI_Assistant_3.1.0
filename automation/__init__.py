"""Automation package — Phase 10: scheduler, workflow, automation manager.

Public API:
    AutomationTask, TaskStatus, ScheduleType
    StubScheduler
    Workflow, WorkflowStep
    AutomationManager
"""

from automation.manager import AutomationManager
from automation.scheduler import StubScheduler
from automation.task import AutomationTask, ScheduleType, TaskStatus
from automation.workflow import Workflow, WorkflowStep

__all__ = [
    "AutomationManager",
    "AutomationTask",
    "ScheduleType",
    "StubScheduler",
    "TaskStatus",
    "Workflow",
    "WorkflowStep",
]
