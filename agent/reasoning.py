"""Reasoning layer for agents — decides whether to continue after an action.

* :class:`StubReasoner`   — fixed iteration/terminal rules (no dependencies).
* :class:`LLMReasoner`    — asks the engine for a next-step decision; falls
                            back to the stub when unavailable.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agent.task import TaskStatus

if TYPE_CHECKING:
    from ai.engine.llm_engine import GenerationConfig, LLMEngine
    from core.event_bus import EventBus


# Clear affirmative/negative first-words for the continue/stop decision.
# Word-boundary matching prevents the classic substring false positives
# ("know", "nothing", "now" must NOT read as "no").
_YES_RE = re.compile(r"\b(yes|yeah|yep|sure|ok|okay|continue|proceed|go ahead)\b", re.IGNORECASE)
_NO_RE = re.compile(r"\b(no|nope|stop|halt|done|finished|complete|enough)\b", re.IGNORECASE)


def _classify_llm_answer(answer: str) -> bool | None:
    """Interpret the LLM's yes/no answer.

    Returns ``True`` (continue), ``False`` (stop), or ``None`` when the
    answer carries no clear signal — the caller then falls back to the
    deterministic stub rules instead of guessing.

    The decision signal must come from the FIRST sentence/word of the answer
    (LLMs answer "Yes." / "No." first, then explain).  Scanning the whole
    answer would misread explanations like "yes — the previous run had no
    errors".
    """
    if not answer:
        return None
    # First sentence only: the decision token comes before any explanation.
    first_sentence = re.split(r"[.!?\n]", answer.strip(), maxsplit=1)[0].lower()
    no_match = _NO_RE.search(first_sentence)
    yes_match = _YES_RE.search(first_sentence)
    if no_match and yes_match:
        # Whichever signal appears first wins ("no, but yes..." → stop).
        return no_match.start() > yes_match.start()
    if no_match:
        return False
    if yes_match:
        return True
    return None


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
            decision = _classify_llm_answer(answer)
            if decision is False:
                return False
            if decision is None:
                # Ambiguous answer — do not guess; use the deterministic
                # iteration-bounded rules (same fallback as engine failure).
                return self._fallback.should_continue(task_status, observation)
        except Exception:
            return self._fallback.should_continue(task_status, observation)
        self._iterations += 1
        return self._iterations < self._max_iterations

    def conclude(self, observations: list[str]) -> str:
        return self._fallback.conclude(observations)

    def reset(self) -> None:
        self._iterations = 0
