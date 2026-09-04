"""Workflow — ordered sequence of tool steps executed via the secured registry."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.logger import get_logger
from tools.base import ToolResult

if TYPE_CHECKING:
    from core.event_bus import EventBus
    from tools.base import ToolRegistry

logger = get_logger("automation")

_ALLOWED_AST_NODES = frozenset({
    ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare,
    ast.Constant, ast.Name, ast.Load,
    ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.FloorDiv, ast.Pow,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Is, ast.IsNot, ast.In, ast.NotIn,
    ast.List, ast.Tuple, ast.Dict,
    ast.Subscript, ast.Attribute, ast.Call,
})

_ALLOWED_NAMES = frozenset({"x", "True", "False", "None"})


@dataclass
class WorkflowStep:
    tool_name: str
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    condition: str | None = None
    branch_true: list[WorkflowStep] = field(default_factory=list)
    branch_false: list[WorkflowStep] = field(default_factory=list)


class Workflow:
    """A named, ordered list of tool steps.  Each step routes through the
    Security Layer, so ASK/DENY still applies — a blocked step halts the run.
    """

    def __init__(
        self,
        name: str,
        steps: list[WorkflowStep] | None = None,
        description: str = "",
        enabled: bool = True,
        event_bus: EventBus | None = None,
    ) -> None:
        self._name = name
        self._description = description
        self._enabled = enabled
        self._steps: list[WorkflowStep] = steps or []
        self._event_bus = event_bus

    @classmethod
    def of(
        cls,
        name: str,
        steps: list[dict[str, Any]],
        description: str = "",
        enabled: bool = True,
        event_bus: EventBus | None = None,
    ) -> Workflow:
        parsed: list[WorkflowStep] = []
        for item in steps:
            step = WorkflowStep(
                tool_name=item.get("tool") or item.get("tool_name", ""),
                params=item.get("params", {}),
                description=item.get("description", ""),
                condition=item.get("condition"),
                branch_true=[
                    WorkflowStep(
                        tool_name=b.get("tool") or b.get("tool_name", ""),
                        params=b.get("params", {}),
                        description=b.get("description", ""),
                    )
                    for b in item.get("branch_true", [])
                ],
                branch_false=[
                    WorkflowStep(
                        tool_name=b.get("tool") or b.get("tool_name", ""),
                        params=b.get("params", {}),
                        description=b.get("description", ""),
                    )
                    for b in item.get("branch_false", [])
                ],
            )
            parsed.append(step)
        return cls(name, parsed, description=description, enabled=enabled, event_bus=event_bus)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def steps(self) -> list[WorkflowStep]:
        return list(self._steps)

    def __len__(self) -> int:
        return len(self._steps)

    def run(self, tool_registry: ToolRegistry) -> list[ToolResult]:
        """Execute steps sequentially. Stops on the first blocked/failed step."""
        if self._event_bus is not None:
            self._event_bus.publish(
                "WORKFLOW_STARTED", data={"workflow": self._name, "steps": len(self._steps)}
            )
        results: list[ToolResult] = []
        last_result: ToolResult | None = None
        for step in self._steps:
            logger.info("Workflow '%s' → step: %s(%s)", self._name, step.tool_name, step.params)
            if step.condition:
                branch = step.branch_true if self._evaluate_condition(step.condition, last_result) else step.branch_false
                for branch_step in branch:
                    logger.info("Workflow '%s' → branch step: %s(%s)", self._name, branch_step.tool_name, branch_step.params)
                    result = tool_registry.execute(branch_step.tool_name, branch_step.params or {})
                    results.append(result)
                    last_result = result
                    if not result.success or result.error == "ConfirmationRequired":
                        if self._event_bus is not None:
                            self._event_bus.publish(
                                "WORKFLOW_COMPLETED",
                                data={
                                    "workflow": self._name,
                                    "stopped_early": True,
                                    "steps_run": len(results),
                                },
                            )
                        return results
                continue
            result = tool_registry.execute(step.tool_name, step.params or {})
            results.append(result)
            last_result = result
            if not result.success or result.error == "ConfirmationRequired":
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "WORKFLOW_COMPLETED",
                        data={
                            "workflow": self._name,
                            "stopped_early": True,
                            "steps_run": len(results),
                        },
                    )
                return results
        if self._event_bus is not None:
            self._event_bus.publish(
                "WORKFLOW_COMPLETED",
                data={"workflow": self._name, "stopped_early": False, "steps_run": len(results)},
            )
        return results

    def _evaluate_condition(
        self, condition: str, previous_result: ToolResult | None = None
    ) -> bool:
        """Evaluate a condition expression with the previous step's result bound as ``x``.

        Two-layer sandbox:

        1. **AST validation** — the expression is parsed and every node is
           checked against an allowlist.  Attribute access to names starting
           with ``_`` (``__class__``, ``__subclasses__``, ``__globals__``,
           etc.) is rejected, blocking the well-known
           ``x.__class__.__subclasses__()`` escape even when ``__builtins__``
           is already stripped.
        2. **Runtime namespace** — ``__builtins__`` is set to ``{}`` and the
           only named value available is ``x`` (the previous :class:`ToolResult`).
        """
        try:
            tree = ast.parse(condition, mode="eval")
        except SyntaxError:
            return False

        if not self._is_safe_ast(tree):
            logger.warning("Unsafe workflow condition rejected: %s", condition)
            return False

        sandbox: dict[str, Any] = {"__builtins__": {}}
        if previous_result is not None:
            sandbox["x"] = previous_result
        try:
            return bool(eval(compile(tree, "<condition>", "eval"), sandbox, {}))
        except (NameError, TypeError, AttributeError, KeyError, ValueError):
            return False

    @staticmethod
    def _is_safe_ast(tree: ast.Expression) -> bool:
        """Return ``True`` only if every node in *tree* is on the allowlist."""
        for node in ast.walk(tree):
            if type(node) not in _ALLOWED_AST_NODES:
                return False
            if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
                return False
            if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self._name,
            "description": self._description,
            "enabled": self._enabled,
            "steps": [
                {
                    "tool": step.tool_name,
                    "params": step.params,
                    "description": step.description,
                    "condition": step.condition,
                    "branch_true": [
                        {"tool": b.tool_name, "params": b.params, "description": b.description}
                        for b in step.branch_true
                    ],
                    "branch_false": [
                        {"tool": b.tool_name, "params": b.params, "description": b.description}
                        for b in step.branch_false
                    ],
                }
                for step in self._steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], event_bus: EventBus | None = None) -> Workflow:
        return cls.of(
            name=data.get("name", ""),
            steps=data.get("steps", []),
            description=data.get("description", ""),
            enabled=data.get("enabled", True),
            event_bus=event_bus,
        )
