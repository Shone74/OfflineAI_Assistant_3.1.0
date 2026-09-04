"""Agent execution verification — evaluates whether an Agent's result satisfies the goal.

This is a dedicated, clearly separated verification layer over the existing
Agent execution.  It performs deterministic objective checks first, and only
optionally consults a local LLM for structured self-evaluation.

It does NOT replace the execution security chain:

    Planner -> BaseAgent -> tool_whitelist -> ToolRegistry -> SecurityLayer -> Tool

Verification observes the result; it never grants permissions or bypasses
SecurityLayer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from ai.engine.llm_engine import GenerationConfig
from core.logger import get_logger

logger = get_logger("verifier")

if TYPE_CHECKING:
    from agent.task import Task
    from ai.engine.llm_engine import LLMEngine


class VerificationStatus(str, Enum):
    """Outcome of verifying an Agent execution."""

    PASSED = "passed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


@dataclass
class VerificationResult:
    """Structured result of verifying an Agent execution."""

    status: VerificationStatus
    summary: str
    checks: list[dict[str, Any]] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    ai_evaluation: dict[str, Any] | None = None

    @property
    def is_passed(self) -> bool:
        return self.status == VerificationStatus.PASSED

    @property
    def is_failed(self) -> bool:
        return self.status == VerificationStatus.FAILED


class AgentVerifier:
    """Evaluate whether an Agent execution result satisfies the goal.

    Objective checks are always performed.  Optional AI evaluation is only
    attempted when an LLM engine is provided and is ready, and never
    overrides a clear objective FAILED status.
    """

    def __init__(self, llm_engine: LLMEngine | None = None, config: GenerationConfig | None = None) -> None:
        self._llm_engine = llm_engine
        self._generation_config: GenerationConfig = config or GenerationConfig(
            max_tokens=256, temperature=0.1
        )

    def verify(
        self,
        goal: str,
        agent_name: str,
        tasks: list[Task],
        result: str,
    ) -> VerificationResult:
        """Run objective checks on the execution, then optionally AI evaluation."""
        checks: list[dict[str, Any]] = []
        issues: list[str] = []

        # --- Objective checks ---
        execution_completed = self._check_execution_completed(tasks, checks, issues)
        result_produced = self._check_result_produced(result, checks, issues)
        no_errors = self._check_no_task_errors(tasks, checks, issues)
        plan_non_empty = self._check_plan_non_empty(tasks, checks, issues)
        non_trivial_result = self._check_result_non_trivial(result, checks, issues)

        # --- Determine status from objective checks ---
        if not execution_completed or not result_produced or not non_trivial_result or not no_errors:
            status = VerificationStatus.FAILED
        elif not plan_non_empty:
            status = VerificationStatus.NEEDS_REVIEW
        else:
            status = VerificationStatus.PASSED

        summary = self._build_summary(status, checks, issues)

        result_obj = VerificationResult(
            status=status,
            summary=summary,
            checks=checks,
            issues=issues,
        )

        # --- Optional AI evaluation (never overrides objective FAILED) ---
        if status != VerificationStatus.FAILED:
            result_obj.ai_evaluation = self._optional_ai_evaluation(goal, result)

        return result_obj

    # ------------------------------------------------------------------ #
    # Objective checks
    # ------------------------------------------------------------------ #
    def _check_execution_completed(
        self, tasks: list[Task], checks: list[dict[str, Any]], issues: list[str],
    ) -> bool:
        from agent.task import TaskStatus

        running = [t for t in tasks if t.status == TaskStatus.RUNNING]
        completed = True
        if running:
            completed = False
            issues.append(f"{len(running)} task(s) still running")
        checks.append({
            "check": "execution_completed",
            "passed": completed,
            "detail": f"{len(tasks) - len(running)}/{len(tasks)} tasks finished" if tasks else "no tasks",
        })
        return completed

    def _check_result_produced(
        self, result: str, checks: list[dict[str, Any]], issues: list[str],
    ) -> bool:
        produced = bool(result and result.strip())
        if not produced:
            issues.append("Result is empty or contains only whitespace")
        checks.append({
            "check": "result_produced",
            "passed": produced,
            "detail": f"result length: {len(result)}",
        })
        return produced

    def _check_no_task_errors(
        self, tasks: list[Task], checks: list[dict[str, Any]], issues: list[str],
    ) -> bool:
        from agent.task import TaskStatus

        failed = [t for t in tasks if t.status == TaskStatus.FAILED]
        no_errors = len(failed) == 0
        if not no_errors:
            for t in failed:
                issues.append(f"Task failed: {t.description} — {t.result}")
        checks.append({
            "check": "no_task_errors",
            "passed": no_errors,
            "detail": f"{len(failed)} failed task(s) out of {len(tasks)}",
        })
        return no_errors

    def _check_plan_non_empty(
        self, tasks: list[Task], checks: list[dict[str, Any]], issues: list[str],
    ) -> bool:
        non_empty = len(tasks) > 0
        if not non_empty:
            issues.append("Agent produced an empty plan")
        checks.append({
            "check": "plan_non_empty",
            "passed": non_empty,
            "detail": f"{len(tasks)} task(s) in plan",
        })
        return non_empty

    def _check_result_non_trivial(
        self, result: str, checks: list[dict[str, Any]], issues: list[str],
    ) -> bool:
        truncated = result.strip()
        non_trivial = (
            len(truncated) >= 10
            and truncated.lower() != truncated.upper()
            and not all(c in " \t\n" for c in truncated)
        )
        if not non_trivial:
            issues.append("Result appears trivial or incomplete")
        checks.append({
            "check": "result_non_trivial",
            "passed": non_trivial,
            "detail": f"result length after strip: {len(truncated)}",
        })
        return non_trivial

    # ------------------------------------------------------------------ #
    # Optional AI-based evaluation
    # ------------------------------------------------------------------ #
    def _optional_ai_evaluation(self, goal: str, result: str) -> dict[str, Any] | None:
        """Attempt an LLM-based evaluation pass.

        Never raises — any failure is logged and ``None`` is returned.
        Only used when an engine is provided and ready.
        """
        if self._llm_engine is None or not self._llm_engine.is_ready:
            return None

        if self._llm_engine.model_name == "stub":
            return None

        try:
            prompt = self._build_ai_eval_prompt(goal, result)
            raw = self._llm_engine.generate(prompt, config=self._generation_config)
            return self._parse_ai_eval_response(raw)
        except Exception:  # noqa: BLE001 — best-effort AI evaluation must never break verification
            logger.warning("AI evaluation failed — returning objective-only result")
            return None

    def _build_ai_eval_prompt(self, goal: str, result: str) -> str:
        """Structured prompt for the optional AI evaluation pass."""
        return (
            f"Evaluate whether the following Agent result satisfies the requested goal.\n\n"
            f"Goal: {goal}\n\n"
            f"Result:\n{result}\n\n"
            f"Answer with only a JSON object containing exactly these keys:\n"
            f'{{"addresses_goal": "yes|no", '
            f'"obvious_issues": "yes|no", '
            f'"appears_complete": "yes|no", '
            f'"summary": "brief one-sentence assessment"}}\n'
        )

    def _parse_ai_eval_response(self, raw: str) -> dict[str, Any]:
        """Parse the AI evaluation response, handling malformed JSON gracefully."""
        import json

        text = raw.strip()
        try:
            data: dict[str, Any] = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            text = text.removeprefix("```json").removesuffix("```").strip()
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                return {
                    "addresses_goal": None,
                    "obvious_issues": None,
                    "appears_complete": None,
                    "summary": "Could not parse AI evaluation response",
                    "raw": raw[:500],
                }

        return {
            "addresses_goal": data.get("addresses_goal"),
            "obvious_issues": data.get("obvious_issues"),
            "appears_complete": data.get("appears_complete"),
            "summary": data.get("summary", "No summary provided"),
        }

    # ------------------------------------------------------------------ #
    def _build_summary(self, status: VerificationStatus, checks: list[dict[str, Any]], issues: list[str]) -> str:
        """Build a human-readable summary of the verification."""
        passed_checks = sum(1 for c in checks if c.get("passed"))
        total_checks = len(checks)
        parts = [
            f"Verification: {status.value.upper()}",
            f"Checks: {passed_checks}/{total_checks} passed",
        ]
        if issues:
            parts.append(f"Issues: {len(issues)}")
            for issue in issues[:3]:
                parts.append(f"  - {issue}")
        return "\n".join(parts)
