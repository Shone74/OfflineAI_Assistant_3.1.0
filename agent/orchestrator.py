"""Agent orchestrator — multi-agent workflow coordination.

Runs a sequence of registered agents against a shared goal.  Each agent
receives the previous agent's summary as its refined goal, enabling simple
``research → execution`` style handoffs.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.event_bus import EventCallback
from core.logger import get_logger

if TYPE_CHECKING:
    from agent.base import BaseAgent
    from agent.repository import AgentRepository
    from core.event_bus import EventBus
    from tools.base import ToolRegistry

logger = get_logger("agent")


class AgentOrchestrator:
    """Coordinates a team of :class:`BaseAgent` instances."""

    def __init__(
        self,
        event_bus: EventBus,
        agent_repository: AgentRepository | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._agent_repository = agent_repository
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> BaseAgent:
        self._agents[agent.name] = agent
        self._event_bus.publish("AGENT_REGISTERED", data={"agent": agent.name, "role": agent.role})
        logger.info("Agent '%s' registered (role=%s)", agent.name, agent.role)
        return agent

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)

    @property
    def agent_names(self) -> list[str]:
        return list(self._agents.keys())

    def run(
        self,
        goal: str,
        agent_names: list[str] | None = None,
        publish_fn: EventCallback | None = None,
    ) -> str:
        """Execute the (optionally ordered) agents sequentially.

        When *publish_fn* is provided (e.g. by a QThread-based worker), all
        EventBus events are routed through it instead of
        ``self._event_bus.publish`` directly, preserving GUI thread-affinity
        (NEXT-D-66 contract extended to the multi-agent path).
        """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            pub = self._event_bus.publish
        selected: list[BaseAgent] = []
        ordered = agent_names or list(self._agents.keys())
        for name in ordered:
            agent = self._agents.get(name)
            if agent is not None:
                selected.append(agent)

        if not selected:
            pub("AGENT_ERROR", data={"message": "no agents registered"})
            return ""

        pub(
            "WORKFLOW_STARTED",
            data={"goal": goal, "agents": [a.name for a in selected]},
        )
        observation = goal
        results: list[str] = []
        for agent in selected:
            observation = agent.run(observation)
            results.append(observation)
            if agent.verification_result is not None:
                vr = agent.verification_result
                pub(
                    "AGENT_VERIFICATION",
                    data={
                        "agent_name": agent.name,
                        "agent_id": agent.agent_id,
                        "status": vr.status.value,
                        "summary": vr.summary,
                        "issues": vr.issues,
                    },
                )
            pub(
                "WORKFLOW_STEP",
                data={"agent": agent.name, "summary": observation},
            )
        pub("WORKFLOW_COMPLETED", data={"agents": len(selected), "goal": goal})
        return "\n---\n".join(results)

    def load_persisted_agents(
        self,
        tool_registry: ToolRegistry,
        planner_factory: Callable[[str], Any],
        assistant: Any | None = None,
    ) -> int:
        """Load all enabled persisted agents and register them as :class:`BaseAgent`.

        ``planner_factory`` receives the agent's ``system_prompt`` and must return
        a configured :class:`Planner` instance — this allows per-agent system
        prompts without sharing mutable planner state.
        """
        from agent.base import BaseAgent

        if self._agent_repository is None:
            return 0
        agents = self._agent_repository.list_agents(include_disabled=False)
        count = 0
        for agent_def in agents:
            planner = planner_factory(agent_def.system_prompt or "")
            if hasattr(planner, "tool_whitelist"):
                planner.tool_whitelist = agent_def.tool_whitelist
            agent = BaseAgent(
                name=agent_def.name or "assistant-agent",
                role=agent_def.description or "executor",
                goal="",
                planner=planner,
                tool_registry=tool_registry,
                event_bus=self._event_bus,
                assistant=assistant,
                system_prompt=agent_def.system_prompt,
                model_name=agent_def.model_name,
                tool_whitelist=agent_def.tool_whitelist,
                permission_profile=agent_def.permission_profile,
                enabled=agent_def.enabled,
                agent_id=agent_def.id,
                verifier=getattr(assistant, "_verifier", None),
            )
            self.register(agent)
            count += 1
        logger.info("Loaded %d persisted agent(s) into orchestrator", count)
        return count
