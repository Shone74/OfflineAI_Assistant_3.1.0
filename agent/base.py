"""Base agent — ReAct loop over a plan of :class:`Task` objects.

Agents execute through the secured :class:`ToolRegistry` so every action is
subject to the Security Layer's ASK/DENY policy.  No system is reached
directly from here — tools are the only egress point.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from agent.task import Task, TaskStatus
from core.logger import get_logger
from tools.base import ToolResult

if TYPE_CHECKING:
    from agent.memory import AgentMemory
    from agent.verifier import VerificationResult
    from core.assistant import Assistant
    from core.event_bus import EventBus, EventCallback
    from tools.base import ToolRegistry

logger = get_logger("agent")


class BaseAgent:
    """A goal-driven agent that plans then executes tasks sequentially."""

    def __init__(
        self,
        name: str,
        role: str,
        goal: str,
        planner: Any,
        tool_registry: ToolRegistry | None,
        event_bus: EventBus,
        assistant: Assistant | None = None,
        system_prompt: str = "",
        model_name: str = "",
        tool_whitelist: list[str] | None = None,
        permission_profile: str = "default",
        enabled: bool = True,
        agent_id: int | None = None,
        verifier: Any = None,
        publish_fn: EventCallback | None = None,
    ) -> None:
        self._name = name
        self._role = role
        self._goal = goal
        self._planner = planner
        self._tool_registry = tool_registry
        self._event_bus = event_bus
        self._publish_fn: EventCallback = (
            publish_fn if publish_fn is not None else self._event_bus.publish
        )
        self._assistant = assistant
        self._system_prompt = system_prompt
        self._model_name = model_name
        self._tool_whitelist = tool_whitelist
        self._permission_profile = permission_profile
        self._enabled = enabled
        self._agent_id = agent_id
        self._agent_memory: AgentMemory | None = None
        self._verifier = verifier
        self._verification_result: VerificationResult | None = None
        self._tasks: list[Task] = []
        self._running: bool = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return self._role

    @property
    def is_ready(self) -> bool:
        return self._tool_registry is not None

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def tool_whitelist(self) -> list[str] | None:
        return self._tool_whitelist

    @property
    def permission_profile(self) -> str:
        return self._permission_profile

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def agent_id(self) -> int | None:
        return self._agent_id

    @property
    def agent_memory(self) -> AgentMemory | None:
        return self._agent_memory

    def set_agent_memory(self, memory: AgentMemory | None) -> None:
        """Attach an :class:`AgentMemory` integration layer to this agent."""
        self._agent_memory = memory

    def recall_memory(self, query: str, max_memories: int = 5) -> list[Any]:
        """Retrieve memories relevant to *query* for this Agent.

        Returns an empty list when Memory is disabled or the agent has no
        ``AgentMemory`` configured.
        """
        if self._agent_memory is None:
            return []
        return self._agent_memory.recall(query, max_memories=max_memories)

    def remember_memory(
        self, content: str, mem_type: str = "fact", importance: float = 0.5,
    ) -> int | None:
        """Create a memory entry associated with this Agent.

        This is a **controlled** operation — callers must decide what is
        worth persisting.  Returns ``None`` when Memory is disabled.
        """
        if self._agent_memory is None:
            return None
        return self._agent_memory.remember(content, mem_type=mem_type, importance=importance)

    @property
    def verifier(self) -> Any:
        return self._verifier

    @property
    def verification_result(self) -> VerificationResult | None:
        return self._verification_result

    def verify_execution(self, goal: str, result: str) -> VerificationResult | None:
        """Run verification on the execution result.

        Uses the attached :class:`AgentVerifier` if available.
        Returns ``None`` when no verifier is configured.
        """
        if self._verifier is None:
            return None
        vr = self._verifier.verify(goal=goal, agent_name=self._name, tasks=self._tasks, result=result)
        self._verification_result = vr
        return vr

    def plan(self, goal: str | None = None) -> list[Task]:
        goal = goal or self._goal
        self._tasks = self._planner.plan(goal)
        self._publish_fn(
            "PLAN_CREATED", data={"agent": self._name, "tasks": len(self._tasks)}
        )
        logger.info(
            "Agent '%s' planned %d task(s) for goal: %s", self._name, len(self._tasks), goal
        )
        return self._tasks

    def act(self, task: Task) -> Task:
        """Execute a single task through the secured tool registry."""
        if task.tool_name is None:
            task.status = TaskStatus.DONE
            task.result = f"Odgovor: {task.description}"
            self._publish_fn(
                "AGENT_TASK_COMPLETED",
                data={"agent": self._name, "task": task.id, "tool": None},
            )
            return task

        if self._tool_registry is None:
            task.status = TaskStatus.BLOCKED
            task.result = "Nema konfigurisan tool registry"
            self._publish_fn(
                "AGENT_TASK_COMPLETED",
                data={
                    "agent": self._name,
                    "task": task.id,
                    "tool": task.tool_name,
                    "success": False,
                },
            )
            return task

        # Agent-level tool whitelist enforcement (before SecurityLayer execution).
        # None / empty whitelist preserves existing backward-compatible behaviour.
        if self._tool_whitelist is not None and task.tool_name not in self._tool_whitelist:
            task.status = TaskStatus.BLOCKED
            task.result = f"Tool '{task.tool_name}' not in agent whitelist"
            self._publish_fn(
                "AGENT_TASK_COMPLETED",
                data={
                    "agent": self._name,
                    "task": task.id,
                    "tool": task.tool_name,
                    "success": False,
                    "reason": "whitelist_denied",
                },
            )
            logger.info(
                "Agent '%s' blocked tool '%s' (not in whitelist)",
                self._name, task.tool_name,
            )
            return task

        task.status = TaskStatus.RUNNING
        self._publish_fn(
            "AGENT_TASK_STARTED",
            data={"agent": self._name, "task": task.id, "tool": task.tool_name},
        )
        result: ToolResult = self._tool_registry.execute(
            task.tool_name, task.params or {}, permission_profile=self._permission_profile,
        )
        if not result.success:
            if result.error == "ConfirmationRequired":
                task.status = TaskStatus.BLOCKED
            else:
                task.status = TaskStatus.FAILED
            task.result = result.error or "Nije uspelo"
            self._publish_fn(
                "AGENT_TASK_COMPLETED",
                data={
                    "agent": self._name,
                    "task": task.id,
                    "tool": task.tool_name,
                    "success": False,
                },
            )
            return task

        task.status = TaskStatus.DONE
        task.result = result.message
        self._publish_fn(
            "AGENT_TASK_COMPLETED",
            data={"agent": self._name, "task": task.id, "tool": task.tool_name, "success": True},
        )
        return task

    def run(
        self,
        goal: str | None = None,
        max_steps: int = 10,
        cancel_event: threading.Event | None = None,
    ) -> str:
        """Plan a goal and execute every task. Returns a summary string."""
        if not self.is_ready:
            return ""
        if self._running:
            logger.warning("Agent '%s' is already running; ignoring concurrent run", self._name)
            return ""
        self._running = True
        self._verification_result = None
        actual_goal = goal or self._goal
        summary = ""
        self._publish_fn("AGENT_STARTED", data={"agent": self._name, "goal": actual_goal})
        error_published = False
        try:
            plan = self.plan(actual_goal)
            for i, task in enumerate(plan[:max_steps]):
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("Agent '%s' cancelled by cancel_event", self._name)
                    break
                self.act(task)
                self._publish_fn(
                    "AGENT_STEP",
                    data={"agent": self._name, "step": i + 1, "task": task.id, "tool": task.tool_name},
                )
        except Exception:
            logger.exception("Agent '%s' run failed", self._name)
            self._publish_fn("AGENT_ERROR", data={"agent": self._name})
            error_published = True
        finally:
            self._running = False
            self._publish_fn("AGENT_FINISHED", data={"agent": self._name})
        summary = self.summarize()

        # Step 8: verify execution result
        try:
            self.verify_execution(actual_goal, summary)
        except Exception:
            logger.exception("Agent '%s' verification failed", self._name)
            if not error_published:
                self._publish_fn("AGENT_ERROR", data={"agent": self._name})
                error_published = True

        return summary

    def summarize(self) -> str:
        done = [t for t in self._tasks if t.status == TaskStatus.DONE]
        failed = [t for t in self._tasks if t.status == TaskStatus.FAILED]
        blocked = [t for t in self._tasks if t.status == TaskStatus.BLOCKED]
        parts = [
            f"Agent {self._name}: {len(done)} gotovo, {len(failed)} neuspeh-a, {len(blocked)} blokirano"
        ]
        for t in done:
            parts.append(f"  ✓ {t.description}")
        for t in failed:
            parts.append(f"  ✗ {t.description} — {t.result}")
        for t in blocked:
            parts.append(f"  ⧖ {t.description} — potrebna potvrda")
        return "\n".join(parts)
