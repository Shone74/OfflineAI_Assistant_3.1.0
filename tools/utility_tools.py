"""Utility tools — calculate, date_time, clipboard_read, clipboard_write.

These tools provide everyday utilities for the assistant:
  * ``calculate``       — safe maths evaluation (no ``eval``)
  * ``date_time``       — current local date/time information
  * ``clipboard_read``  — read clipboard text
  * ``clipboard_write`` — write text to clipboard

All tools are offline-first, model-independent, and go through the
same ToolRegistry → SecurityLayer execution path.
"""

from __future__ import annotations

import ast
import datetime
import math
import operator
from typing import Any, ClassVar

from core.logger import get_logger
from security.models import ToolCategory
from tools.base import ParameterSpec, RiskLevel, Tool, ToolResult
from tools.models import ToolMetadata, ToolSource, ToolTrust

logger = get_logger("tools.utility")


# --------------------------------------------------------------------------- #
# Safe math evaluation
# --------------------------------------------------------------------------- #
_SAFE_BIN_OPS: dict[type, Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_SAFE_UNARY_OPS: dict[type, Any] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_SAFE_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
    "tau": math.tau,
    "inf": math.inf,
    "nan": math.nan,
}

_SAFE_FUNCS: dict[str, Any] = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sum": sum,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
    "log": math.log,
    "log10": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "radians": math.radians,
    "degrees": math.degrees,
    "hypot": math.hypot,
    "pow": pow,
}


def _safe_eval(node: ast.AST) -> Any:
    """Recursively evaluate an AST node using only safe operators."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise ValueError(f"Unsupported constant type: {type(node.value)}")

    if isinstance(node, ast.Num):  # legacy Python
        return node.n

    if isinstance(node, ast.BinOp):
        bin_op_type = type(node.op)
        if bin_op_type not in _SAFE_BIN_OPS:
            raise ValueError(f"Unsupported operator: {bin_op_type.__name__}")
        return _SAFE_BIN_OPS[bin_op_type](_safe_eval(node.left), _safe_eval(node.right))

    if isinstance(node, ast.UnaryOp):
        unary_op_type = type(node.op)
        if unary_op_type not in _SAFE_UNARY_OPS:
            raise ValueError(f"Unsupported unary operator: {unary_op_type.__name__}")
        return _SAFE_UNARY_OPS[unary_op_type](_safe_eval(node.operand))

    if isinstance(node, ast.Name):
        if node.id in _SAFE_CONSTANTS:
            return _SAFE_CONSTANTS[node.id]
        if node.id in _SAFE_FUNCS:
            return _SAFE_FUNCS[node.id]
        raise ValueError(f"Unknown name: {node.id}")

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise TypeError("Only named functions are supported")
        func = _SAFE_FUNCS.get(node.func.id)
        if func is None:
            raise ValueError(f"Function not allowed: {node.func.id}")
        args = [_safe_eval(a) for a in node.args]
        kwargs = {kw.arg: _safe_eval(kw.value) for kw in node.keywords if kw.arg is not None}
        return func(*args, **kwargs)

    if isinstance(node, ast.Compare):
        left = _safe_eval(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            cmp_op_type = type(op)
            ops_map: dict[type, Any] = {
                ast.Eq: operator.eq,
                ast.NotEq: operator.ne,
                ast.Lt: operator.lt,
                ast.LtE: operator.le,
                ast.Gt: operator.gt,
                ast.GtE: operator.ge,
            }
            if cmp_op_type not in ops_map:
                raise ValueError(f"Unsupported comparison: {cmp_op_type.__name__}")
            left = ops_map[cmp_op_type](left, _safe_eval(comparator))
        return left

    if isinstance(node, ast.BoolOp):
        values = [_safe_eval(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError("Unsupported boolean operator")

    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def _safe_calculate(expression: str) -> float | int:
    """Evaluate a mathematical expression safely without ``eval``."""
    if not expression or not expression.strip():
        raise ValueError("Empty expression")
    if len(expression) > 1000:
        raise ValueError("Expression too long (max 1000 characters)")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid syntax: {exc}") from exc
    return _safe_eval(tree)


# --------------------------------------------------------------------------- #
# Clipboard helpers
# --------------------------------------------------------------------------- #
def _read_clipboard() -> str:
    """Read text from the system clipboard."""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()  # hide the root window
        try:
            text = root.clipboard_get()
        finally:
            root.destroy()
        return text
    except Exception as exc:
        raise RuntimeError(f"Cannot read clipboard: {exc}") from exc


def _write_clipboard(text: str) -> None:
    """Write text to the system clipboard."""
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
    except Exception as exc:
        raise RuntimeError(f"Cannot write clipboard: {exc}") from exc


# --------------------------------------------------------------------------- #
# Metadata builders
# --------------------------------------------------------------------------- #
def _build_calculate_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="calculate",
        name="Calculate",
        description="Perform a mathematical calculation safely.",
        version="1.0.0",
        category=ToolCategory.UTILITY,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.INFO.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=(),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression (e.g. 2+2, sqrt(16), 3*4/2)",
                },
            },
            "required": ["expression"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "expression": {"type": "string"},
                "result": {"type": "number"},
            },
        },
        icon="calc",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_date_time_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="date_time",
        name="Date & Time",
        description="Return current local date and time information.",
        version="1.0.0",
        category=ToolCategory.UTILITY,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.INFO.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=(),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "description": "Output format: iso (default), date, time, weekday, full",
                },
            },
            "required": [],
        },
        output_schema={
            "type": "object",
            "properties": {
                "iso": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
                "weekday": {"type": "string"},
                "timestamp": {"type": "number"},
            },
        },
        icon="clock",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_clipboard_read_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="clipboard_read",
        name="Clipboard Read",
        description="Read current text content from the system clipboard.",
        version="1.0.0",
        category=ToolCategory.UTILITY,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.READ_ONLY.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("system.clipboard",),
        model_requirements=(),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        icon="clipboard",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_clipboard_write_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="clipboard_write",
        name="Clipboard Write",
        description="Write text content to the system clipboard.",
        version="1.0.0",
        category=ToolCategory.UTILITY,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("system.clipboard",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to write to the clipboard",
                },
            },
            "required": ["text"],
        },
        output_schema={"type": "object", "properties": {"success": {"type": "boolean"}}},
        icon="clipboard_pen",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


# --------------------------------------------------------------------------- #
# Tool implementations
# --------------------------------------------------------------------------- #
class CalculateTool(Tool):
    """Performs mathematical calculations safely."""

    name = "calculate"
    description = "Calculate a mathematical expression"
    category: ToolCategory = ToolCategory.UTILITY
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="expression", description="Mathematical expression (e.g. 2+2, sqrt(16))"),
    ]
    risk_level = RiskLevel.INFO

    def get_metadata(self) -> ToolMetadata:
        return _build_calculate_metadata()

    def execute(self, **params: Any) -> ToolResult:
        expression = str(params.get("expression", ""))
        if not expression.strip():
            return ToolResult(
                success=False, message="No expression given", error="MissingExpression"
            )

        try:
            result = _safe_calculate(expression)
            if isinstance(result, float) and result.is_integer():
                result = int(result)
            logger.debug("Calculate: %s = %s", expression, result)
            return ToolResult(
                success=True,
                message=f"Result: {result}",
                data={"expression": expression, "result": result},
            )
        except ValueError as exc:
            return ToolResult(
                success=False, message=str(exc), error="InvalidExpression"
            )
        except ZeroDivisionError:
            return ToolResult(
                success=False, message="Division by zero", error="DivisionByZero"
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=str(exc), error="CalculationError"
            )


class DateTimeTool(Tool):
    """Returns current local date and time information."""

    name = "date_time"
    description = "Show the current date and time"
    category: ToolCategory = ToolCategory.UTILITY
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(
            name="format",
            description="Format: iso (default), date, time, weekday, full",
            required=False,
        ),
    ]
    risk_level = RiskLevel.INFO

    def get_metadata(self) -> ToolMetadata:
        return _build_date_time_metadata()

    def execute(self, **params: Any) -> ToolResult:
        fmt = str(params.get("format", "iso")).lower()
        now = datetime.datetime.now(tz=datetime.UTC).astimezone()
        data = {
            "iso": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "weekday": now.strftime("%A"),
            "timestamp": now.timestamp(),
        }

        if fmt == "date":
            text = data["date"]
        elif fmt == "time":
            text = data["time"]
        elif fmt == "weekday":
            text = data["weekday"]
        elif fmt == "full":
            text = f"{data['weekday']}, {data['date']} {data['time']}"
        else:
            text = data["iso"]

        logger.debug("DateTime: %s", text)
        return ToolResult(
            success=True,
            message=f"Current: {text}",
            data=data,
        )


class ClipboardReadTool(Tool):
    """Reads text from the system clipboard."""

    name = "clipboard_read"
    description = "Read the clipboard contents"
    category: ToolCategory = ToolCategory.UTILITY
    parameters: ClassVar[list[ParameterSpec]] = []
    risk_level = RiskLevel.READ_ONLY

    def get_metadata(self) -> ToolMetadata:
        return _build_clipboard_read_metadata()

    def execute(self, **params: Any) -> ToolResult:
        try:
            text = _read_clipboard()
            return ToolResult(
                success=True,
                message="Read from clipboard",
                data={"text": text},
            )
        except RuntimeError as exc:
            return ToolResult(
                success=False, message=str(exc), error="ClipboardError"
            )


class ClipboardWriteTool(Tool):
    """Writes text to the system clipboard."""

    name = "clipboard_write"
    description = "Write contents to the clipboard"
    category: ToolCategory = ToolCategory.UTILITY
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="text", description="Text to write to the clipboard"),
    ]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_clipboard_write_metadata()

    def execute(self, **params: Any) -> ToolResult:
        text = str(params.get("text", ""))
        try:
            _write_clipboard(text)
            return ToolResult(
                success=True,
                message="Written to clipboard",
                data={"success": True},
            )
        except RuntimeError as exc:
            return ToolResult(
                success=False, message=str(exc), error="ClipboardError"
            )
