"""Agent selector — matches goals to persisted Agent definitions.

Provides selection by explicit ID, by name, or by goal-keyword heuristics.
All selection is performed through :class:`AgentRepository` — no raw
``sqlite3`` connections are opened here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.logger import get_logger
from database.models import Agent

if TYPE_CHECKING:
    from agent.base import BaseAgent
    from agent.repository import AgentRepository
    from core.assistant import Assistant
    from core.event_bus import EventBus
    from tools.base import ToolRegistry

logger = get_logger("agent_selector")

_GOAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "coding": ("code", "program", "programming", "debug", "python", "javascript", "script", "develop"),
    "file": ("file", "read file", "write file", "save", "open file", "document"),
    "research": ("research", "search", "find", "look up", "investigate", "information"),
    "system": ("system", "system info", "cpu", "hardware", "specs", "specifications", "performance"),
    "automation": ("automate", "automation", "routine", "schedule", "task"),
}


class AgentSelector:
    """Selects a persisted :class:`Agent` based on ID, name, or goal heuristics."""

    def __init__(self, repository: AgentRepository | None = None) -> None:
        self._repo = repository

    @property
    def repository(self) -> AgentRepository | None:
        return self._repo

    def select_by_id(self, agent_id: int) -> Agent | None:
        """Return the enabled agent with *agent_id*, or ``None``."""
        if self._repo is None:
            return None
        agent = self._repo.get_agent(agent_id)
        if agent is None:
            return None
        if not agent.enabled:
            logger.info("Agent %d is disabled — skipping selection", agent_id)
            return None
        return agent

    def select_by_name(self, name: str) -> Agent | None:
        """Return the enabled agent named *name*, or ``None``."""
        if self._repo is None:
            return None
        agent = self._repo.get_agent_by_name(name)
        if agent is None:
            return None
        if not agent.enabled:
            logger.info("Agent '%s' is disabled — skipping selection", name)
            return None
        return agent

    def select_for_goal(self, goal: str) -> Agent | None:
        """Heuristically select an enabled agent that matches *goal*.

        Falls back to ``None`` when no persisted agent is available or no
        keyword matches — the caller is expected to handle the fallback.
        """
        if self._repo is None:
            return None
        lowered = goal.lower()
        enabled_agents = self._repo.list_agents(include_disabled=False)
        if not enabled_agents:
            return None

        for agent_type, keywords in _GOAL_KEYWORDS.items():
            for kw in keywords:
                if kw in lowered:
                    for agent in enabled_agents:
                        if agent_type in agent.name.lower():
                            logger.info(
                                "Selected agent '%s' for goal via keyword '%s'",
                                agent.name, kw,
                            )
                            return agent
        return None

    def to_base_agent(
        self,
        agent_def: Agent,
        goal: str,
        planner: Any,
        tool_registry: ToolRegistry | None,
        event_bus: EventBus,
        assistant: Assistant | None = None,
    ) -> BaseAgent:
        """Build a :class:`BaseAgent` from a persisted :class:`Agent` definition."""
        from agent.base import BaseAgent

        return BaseAgent(
            name=agent_def.name or "assistant-agent",
            role=agent_def.description or "executor",
            goal=goal,
            planner=planner,
            tool_registry=tool_registry,
            event_bus=event_bus,
            assistant=assistant,
            system_prompt=agent_def.system_prompt,
            model_name=agent_def.model_name,
            tool_whitelist=agent_def.tool_whitelist,
            permission_profile=agent_def.permission_profile,
            enabled=agent_def.enabled,
            agent_id=agent_def.id,
            verifier=getattr(assistant, "_verifier", None),
        )
