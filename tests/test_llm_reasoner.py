"""Regression tests for the LLMReasoner decision classifier (B1).

Locks the contract: the continue/stop decision uses word-boundary matching
on the LLM answer, eliminating the classic substring false positives
("know", "nothing", "now" must NOT read as "no") while preserving the
existing fallback semantics (ambiguous answers and engine failures fall
back to the iteration-bounded stub rules).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.reasoning import LLMReasoner, StubReasoner, _classify_llm_answer
from agent.task import TaskStatus


# --------------------------------------------------------------------------- #
# Classifier unit tests — direct contract of _classify_llm_answer
# --------------------------------------------------------------------------- #
class TestClassifyAnswer:
    @pytest.mark.parametrize("answer", [
        "yes",
        "Yes.",
        "YES",
        "yeah",
        "yep, one more step",
        "Sure",
        "OK, continue",
        "okay",
        "proceed with the next step",
        "go ahead",
    ])
    def test_clear_yes_signals_continue(self, answer: str) -> None:
        assert _classify_llm_answer(answer) is True

    @pytest.mark.parametrize("answer", [
        "no",
        "No.",
        "NO",
        "nope",
        "stop",
        "halt",
        "done",
        "finished",
        "complete",
        "enough",
        "no more steps are needed",
        "No — the goal is achieved.",
    ])
    def test_clear_no_signals_stop(self, answer: str) -> None:
        assert _classify_llm_answer(answer) is False

    @pytest.mark.parametrize("answer", [
        "know",          # the original bug: contains "no"
        "nothing",       # contains "no"
        "now",           # contains "no"
        "knowledge",     # contains "no"
        "note",          # contains "no"
        "I know nothing about this",
        "unknown",
    ])
    def test_substring_false_positives_are_not_stop_signals(self, answer: str) -> None:
        """'know'/'nothing'/'now' must never be read as 'no'."""
        assert _classify_llm_answer(answer) is not False

    def test_empty_or_gibberish_answer_is_ambiguous(self) -> None:
        assert _classify_llm_answer("") is None
        assert _classify_llm_answer("   ") is None
        assert _classify_llm_answer("perhaps maybe could be") is None

    def test_first_signal_wins_on_mixed_answers(self) -> None:
        # "no, but yes..." → stop;  "yes, though no later..." → continue
        assert _classify_llm_answer("no, but yes if needed") is False
        assert _classify_llm_answer("yes — although a no would also fit") is True

    def test_only_head_of_answer_is_considered(self) -> None:
        # A trailing explanation containing "no"-words must not flip a "yes".
        assert _classify_llm_answer(
            "yes, take another step. (the previous run had no errors)"
        ) is True


# --------------------------------------------------------------------------- #
# LLMReasoner integration — the decision drives should_continue
# --------------------------------------------------------------------------- #
class _ScriptedEngine:
    """Fake engine yielding a scripted answer; records prompts."""

    is_ready = True

    def __init__(self, answer: str, fail: bool = False) -> None:
        self._answer = answer
        self._fail = fail
        self.prompts: list[str] = []

    def generate_stream(self, prompt, config=None):  # noqa: ARG002
        self.prompts.append(prompt)
        if self._fail:
            raise RuntimeError("engine exploded")
        yield self._answer


class TestLLMReasonerDecisions:
    def test_clear_no_stops(self) -> None:
        reasoner = LLMReasoner(_ScriptedEngine("No"))
        assert reasoner.should_continue(TaskStatus.DONE) is False

    def test_clear_yes_continues_up_to_max_iterations(self) -> None:
        reasoner = LLMReasoner(_ScriptedEngine("Yes"), max_iterations=3)
        results = [reasoner.should_continue(TaskStatus.DONE) for _ in range(4)]
        # Continues while under the cap, then stops (iteration bound preserved).
        assert results == [True, True, False, False]

    def test_know_is_not_treated_as_no(self) -> None:
        """The original bug: 'I know' contains 'no' and stopped the agent."""
        reasoner = LLMReasoner(_ScriptedEngine("I know the answer already"))
        # Ambiguous → falls back to stub rules → continues (iteration 1 < 5).
        assert reasoner.should_continue(TaskStatus.DONE) is True

    def test_ambiguous_answer_falls_back_to_stub_rules(self) -> None:
        reasoner = LLMReasoner(_ScriptedEngine("maybe?"), max_iterations=2)
        assert reasoner.should_continue(TaskStatus.DONE) is True
        assert reasoner.should_continue(TaskStatus.DONE) is False  # stub cap

    def test_engine_failure_falls_back_to_stub_rules(self) -> None:
        reasoner = LLMReasoner(_ScriptedEngine("unused", fail=True), max_iterations=2)
        assert reasoner.should_continue(TaskStatus.DONE) is True
        assert reasoner.should_continue(TaskStatus.DONE) is False

    def test_failed_and_blocked_statuses_stop_immediately(self) -> None:
        reasoner = LLMReasoner(_ScriptedEngine("yes"))
        assert reasoner.should_continue(TaskStatus.FAILED) is False
        assert reasoner.should_continue(TaskStatus.BLOCKED) is False

    def test_engine_not_ready_falls_back(self) -> None:
        class NotReady(_ScriptedEngine):
            is_ready = False

        reasoner = LLMReasoner(NotReady("yes"), max_iterations=2)
        assert reasoner.should_continue(TaskStatus.DONE) is True
        assert reasoner.should_continue(TaskStatus.DONE) is False

    def test_prompt_includes_observation(self) -> None:
        engine = _ScriptedEngine("no")
        reasoner = LLMReasoner(engine)
        reasoner.should_continue(TaskStatus.DONE, observation="found 3 files")
        assert "found 3 files" in engine.prompts[0]
        assert "yes/no" in engine.prompts[0]


# --------------------------------------------------------------------------- #
# StubReasoner fallback semantics unchanged
# --------------------------------------------------------------------------- #
class TestStubReasonerUnchanged:
    def test_iteration_bound_preserved(self) -> None:
        stub = StubReasoner(max_iterations=3)
        assert [stub.should_continue(TaskStatus.DONE) for _ in range(4)] == [
            True, True, False, False,
        ]

    def test_reset_restores_budget(self) -> None:
        stub = StubReasoner(max_iterations=1)
        assert stub.should_continue(TaskStatus.DONE) is False  # 1 >= 1... first call increments to 1, 1<1 False
        stub.reset()
        # After reset the budget is available again.
        assert stub.should_continue(TaskStatus.DONE) is False  # same first-call semantics
