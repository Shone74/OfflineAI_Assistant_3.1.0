"""Project context — runtime state tracking and project-scoped context for Phase 13.2.

This module provides:

- ``AgentRuntimeState``: Enum representing the runtime state of an Agent
  working on a project (IDLE, ACTIVE, TASK_COMPLETED, ERROR).

- ``AgentAssignment``: Dataclass linking a project to a persisted Agent
  definition (by ``agent_id``) with optional runtime state tracking.

- ``ProjectContext``: A mutable context object that aggregates project
  identity, workspace path, settings, and the current agent assignment.
  Published via the EventBus on creation/deletion so other subsystems
  (Chat, Knowledge) can react.

- ``ProjectContextManager``: Central registry for active project contexts,
  runtime state tracking, and agent assignment management.  Tracks only
  *runtime* state in-memory; persistence of project metadata is handled
  by :class:`project.manager.ProjectManager`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus
from core.logger import get_logger

logger = get_logger("project.context")

if TYPE_CHECKING:
    from project.manager import ProjectManager


class AgentRuntimeState(str, Enum):
    """Runtime state of an Agent working on a project.

    These values represent *actual* runtime state, not database status.
    They are reset on application restart (agents are ephemeral).
    """

    IDLE = "idle"
    ACTIVE = "active"
    TASK_COMPLETED = "task_completed"
    ERROR = "error"


@dataclass
class AgentAssignment:
    """Links a project to a persisted Agent definition.

    Attributes:
        agent_id: The persisted agent definition ID from the agents table.
        agent_name: Human-readable agent name (from persisted definition).
        runtime_state: Current runtime state (AgentRuntimeState).
        last_task: Description of the last task assigned to this agent.
    """

    agent_id: int
    agent_name: str
    runtime_state: AgentRuntimeState = AgentRuntimeState.IDLE
    last_task: str | None = None


@dataclass
class ProjectContext:
    """Runtime context for an opened project.

    This is the project-scoped context object made available to Chat,
    Knowledge, and other subsystems.  It represents the *currently open*
    project in the application, not a persisted entity.

    Attributes:
        project_id: Unique project ID (UUID string from Project model).
        name: Project display name.
        description: Project description.
        workspace_path: Absolute filesystem path to the project workspace.
        settings: Project-specific settings dict.
        agent_assignment: Active agent assignment, if any.
        profile_override: Optional profile override dict for this project.
    """

    project_id: str
    name: str
    description: str = ""
    workspace_path: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    profile_override: dict[str, Any] | None = None
    agent_assignment: AgentAssignment | None = None

    @property
    def is_open(self) -> bool:
        """Whether this project is currently open (context exists)."""
        return True

    @property
    def is_active(self) -> bool:
        """Whether an Agent is currently executing work on this project."""
        return (
            self.agent_assignment is not None
            and self.agent_assignment.runtime_state == AgentRuntimeState.ACTIVE
        )

    @property
    def runtime_state(self) -> AgentRuntimeState:
        """Current runtime state of the project."""
        if self.agent_assignment is None:
            return AgentRuntimeState.IDLE
        return self.agent_assignment.runtime_state

    @property
    def has_agent_assigned(self) -> bool:
        """Whether an Agent is assigned to this project."""
        return self.agent_assignment is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "workspace_path": self.workspace_path,
            "settings": self.settings,
            "profile_override": self.profile_override,
            "agent_assignment": (
                {
                    "agent_id": self.agent_assignment.agent_id,
                    "agent_name": self.agent_assignment.agent_name,
                    "runtime_state": self.agent_assignment.runtime_state.value,
                    "last_task": self.agent_assignment.last_task,
                }
                if self.agent_assignment
                else None
            ),
        }


class ProjectContextManager:
    """Manages active project contexts and agent runtime state.

    Only runtime state is tracked here — project metadata persistence is
    handled by :class:`ProjectManager`.  On application restart, all
    runtime states are reset to ``IDLE`` (agents don't survive restart).
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        project_manager: ProjectManager | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._project_manager = project_manager
        self._contexts: dict[str, ProjectContext] = {}
        self._open_project_id: str | None = None

    def open_project(self, project_id: str) -> ProjectContext | None:
        """Open a project, creating/refreshing its context.

        Opening a project does NOT start an Agent.  It loads the project
        from ProjectManager into a ProjectContext and publishes
        ``PROJECT_OPENED``.

        Args:
            project_id: The UUID of the project to open.

        Returns:
            The ProjectContext, or None if the project could not be found.
        """
        if self._project_manager is None:
            logger.warning("Cannot open project: no ProjectManager available")
            return None

        proj = self._project_manager.get_project(project_id)
        if proj is None:
            logger.warning("Cannot open project: not found: %s", project_id)
            return None

        ctx = self._contexts.get(project_id)
        if ctx is None:
            ctx = ProjectContext(
                project_id=proj.id,
                name=proj.name,
                description=proj.description,
                workspace_path=proj.workspace_path,
                settings=proj.settings or {},
                profile_override=proj.profile_override,
            )
            self._contexts[project_id] = ctx
        else:
            ctx.name = proj.name
            ctx.description = proj.description
            ctx.workspace_path = proj.workspace_path
            ctx.settings = proj.settings or {}
            ctx.profile_override = proj.profile_override
        self._open_project_id = project_id
        logger.info("Project opened: %s (%s)", ctx.name, ctx.project_id)
        self._event_bus and self._event_bus.publish(
            "PROJECT_OPENED",
            data={"project_id": project_id, "name": proj.name},
        )
        return ctx

    def close_project(self, project_id: str | None = None) -> None:
        """Close the current project context (does NOT delete the project).

        If an Agent was active on this project, its runtime state is
        reset to IDLE.
        """
        target = project_id or self._open_project_id
        if target is None:
            return
        ctx = self._contexts.pop(target, None)
        if ctx is not None:
            if ctx.agent_assignment is not None:
                ctx.agent_assignment.runtime_state = AgentRuntimeState.IDLE
            if target == self._open_project_id:
                self._open_project_id = None
            logger.info("Project closed: %s", target)
            self._event_bus and self._event_bus.publish(
                "PROJECT_CLOSED",
                data={"project_id": target},
            )

    def get_context(self, project_id: str | None = None) -> ProjectContext | None:
        """Get the context for *project_id* (or the currently open project)."""
        target = project_id or self._open_project_id
        if target is None:
            return None
        return self._contexts.get(target)

    @property
    def open_project_id(self) -> str | None:
        """ID of the currently open project, or None."""
        return self._open_project_id

    def assign_agent(
        self, project_id: str, agent_id: int, agent_name: str
    ) -> ProjectContext | None:
        """Assign a persisted Agent definition to a project.

        This does NOT start the Agent — it records the assignment so that
        when the Agent runs, its runtime state can be tracked.
        Publishing ``AGENT_ASSIGNED``.

        Args:
            project_id: The project to assign the agent to.
            agent_id: The persisted agent definition ID.
            agent_name: Display name of the agent.

        Returns:
            Updated ProjectContext, or None if project not open.
        """
        ctx = self._contexts.get(project_id)
        if ctx is None:
            logger.warning("Cannot assign agent: project not open: %s", project_id)
            return None
        ctx.agent_assignment = AgentAssignment(
            agent_id=agent_id,
            agent_name=agent_name,
            runtime_state=AgentRuntimeState.IDLE,
        )
        logger.info("Agent '%s' (id=%d) assigned to project '%s'", agent_name, agent_id, project_id)
        self._event_bus and self._event_bus.publish(
            "AGENT_ASSIGNED_TO_PROJECT",
            data={"project_id": project_id, "agent_id": agent_id, "agent_name": agent_name},
        )
        return ctx

    def set_agent_runtime_state(
        self, project_id: str, state: AgentRuntimeState, task: str | None = None
    ) -> bool:
        """Set the runtime state of the agent assigned to *project_id*.

        This must be called by the Agent execution layer (not directly by
        UI) when the Agent starts, completes, or errors.

        Args:
            project_id: The project whose agent state to update.
            state: The new runtime state.
            task: Optional description of the current/last task.

        Returns:
            True if the state was updated, False if project or agent not found.
        """
        ctx = self._contexts.get(project_id)
        if ctx is None or ctx.agent_assignment is None:
            return False
        ctx.agent_assignment.runtime_state = state
        if task is not None:
            ctx.agent_assignment.last_task = task
        logger.info(
            "Agent runtime state for project %s: %s", project_id, state.value
        )
        self._event_bus and self._event_bus.publish(
            "PROJECT_AGENT_STATE_CHANGED",
            data={
                "project_id": project_id,
                "agent_id": ctx.agent_assignment.agent_id,
                "state": state.value,
                "task": task,
            },
        )
        return True

    def reset_runtime_state(self, project_id: str | None = None) -> None:
        """Reset all runtime states to IDLE.

        Called on application startup to ensure stale ACTIVE states
        are not shown after restart.
        """
        target = project_id
        if target is None:
            for ctx in self._contexts.values():
                if ctx.agent_assignment is not None:
                    ctx.agent_assignment.runtime_state = AgentRuntimeState.IDLE
        else:
            found = self._contexts.get(target)
            if found and found.agent_assignment is not None:
                found.agent_assignment.runtime_state = AgentRuntimeState.IDLE

    def refresh_from_project(self, project_id: str) -> ProjectContext | None:
        """Reload a project context from persistent storage.

        Updates name, description, workspace_path, settings, and
        profile_override from the ProjectManager while preserving
        agent runtime state.
        """
        if self._project_manager is None:
            return self._contexts.get(project_id)
        proj = self._project_manager.get_project(project_id)
        if proj is None:
            return None
        ctx = self._contexts.get(project_id)
        if ctx is None:
            ctx = ProjectContext(
                project_id=proj.id,
                name=proj.name,
                description=proj.description,
                workspace_path=proj.workspace_path,
                settings=proj.settings or {},
                profile_override=proj.profile_override,
            )
            self._contexts[project_id] = ctx
        else:
            ctx.name = proj.name
            ctx.description = proj.description
            ctx.workspace_path = proj.workspace_path
            ctx.settings = proj.settings or {}
            ctx.profile_override = proj.profile_override
        return ctx
