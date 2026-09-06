"""Reasoning layer for agents — decides whether to continue after an action.

* :class:`StubReasoner`   — fixed iteration/terminal rules (no dependencies).
* :class:`LLMReasoner`    — asks the engine for a next-step decision; falls
                            back to the stub when unavailable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.task import TaskStatus

if TYPE_CHECKING:
    from ai.engine.llm_engine import GenerationConfig, LLMEngine
    from core.event_bus import EventBus


class StubReasoner:
    """Iteration-bounded reasoning: stop on failure/blocked or after max loops."""

    def __init__(self, event_bus: EventBus | None = None, max_iterations: int = 5) -> None:
        self._event_bus = event_bus
        self._max_iterations = max_iterations
        self._iterations = 0

    def should_continue(self, task_status: TaskStatus, observation: str | None = None) -> bool:
        if task_status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
            return False
        self._iterations += 1
        return self._iterations < self._max_iterations

    def conclude(self, observations: list[str]) -> str:
        return "\n".join(observations) if observations else "No results."

    def reset(self) -> None:
        self._iterations = 0


class LLMReasoner:
    """LLM-backed reasoner with graceful fallback to :class:`StubReasoner`."""

    def __init__(
        self,
        llm_engine: LLMEngine | None,
        event_bus: EventBus | None = None,
        max_iterations: int = 5,
        generation_config: GenerationConfig | None = None,
    ) -> None:
        self._engine = llm_engine
        self._fallback = StubReasoner(event_bus, max_iterations)
        self._max_iterations = max_iterations
        self._iterations = 0
        self._generation_config = generation_config

    def should_continue(self, task_status: TaskStatus, observation: str | None = None) -> bool:
        if task_status in (TaskStatus.FAILED, TaskStatus.BLOCKED):
            return False
        if self._engine is None or not self._engine.is_ready:
            return self._fallback.should_continue(task_status, observation)
        try:
            prompt = (
                f"Observation:\n{observation or ''}\nShould the agent take another step? (yes/no)"
            )
            answer = "".join(self._engine.generate_stream(prompt, config=self._generation_config))
            if "no" in answer.strip().lower()[:12]:
                return False
        except Exception:
            return self._fallback.should_continue(task_status, observation)
        self._iterations += 1
        return self._iterations < self._max_iterations

    def conclude(self, observations: list[str]) -> str:
        return self._fallback.conclude(observations)

    def reset(self) -> None:
        self._iterations = 0
