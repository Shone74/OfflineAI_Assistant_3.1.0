"""Native LLM tool-calling infrastructure.

This module provides the data types and helpers needed for the Assistant
and Agent paths to use native LLM tool/function calling when the active
model supports it.

Key types:

* :class:`ToolCall`        — a single tool call requested by the model.
* :class:`ToolCallResponse` — model response that may contain both text
  and tool calls.
* :class:`ToolCallParser`   — extracts structured tool calls from raw
  model text output (supports JSON-array and XML-tag formats).
* :class:`ToolSchemaExporter` — builds OpenAI-compatible function schemas
  from the :class:`ToolRegistry` metadata.

Design rules:
  * All schema generation goes through ``ToolSchemaExporter`` — the single
    source of truth shared by Chat and Agent paths.
  * Parsing logic lives in the engine layer, not in ``Assistant``.
  * ``format_tool_result`` produces a text observation the model can read.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from core.logger import get_logger
from tools.models import ToolMetadata, ToolStatus

logger = get_logger("engine.tool_calling")

if TYPE_CHECKING:
    from tools.base import ToolRegistry


_MAX_ITERATIONS = 5


@dataclass
class ToolCall:
    """A single tool call requested by the model.

    Mirrors the OpenAI *chat-completion-tool-call* shape so the format
    can be reused by future OpenAI-compatible engine backends.
    """

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCallResponse:
    """Result of an LLM generation that may contain tool calls.

    ``text`` holds any natural-language content the model emitted
    alongside (or before) tool calls.  ``tool_calls`` holds the parsed
    structured calls.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def add_text(self, chunk: str) -> None:
        self.text += chunk

    def add_tool_call(self, name: str, arguments: dict[str, Any] | None = None) -> None:
        self.tool_calls.append(
            ToolCall(
                id=f"call_{len(self.tool_calls) + 1}",
                name=name,
                arguments=arguments or {},
            )
        )


class ToolCallParser:
    """Extract structured tool calls from raw model text output.

    Supports three formats:

    1. **JSON array** (preferred):
       ``[{"name": "read_file", "arguments": {"path": "x.txt"}}]``

    2. **Single JSON object** (no array wrapper — emitted by some models):
       ``{"name": "read_file", "arguments": {"path": "x.txt"}}``

    3. **XML-tag style**:
       ``[TOOL_CALL: read_file(path="x.txt")]``

    The parser returns the first format it recognises.  If no tool-call
    pattern is found the full text is returned as a plain response.
    """

    _JSON_ARRAY_RE = re.compile(
        r'\[\s*\{.*\}\s*\]', re.DOTALL
    )

    # Single JSON object with "name" and "arguments" keys
    _JSON_OBJECT_RE = re.compile(
        r'\{"name"\s*:.*?"arguments"\s*:.*\}', re.DOTALL
    )

    # [TOOL_CALL: tool_name(key=value, key2="value2")]
    _XML_TAG_RE = re.compile(
        r'\[TOOL_CALL:\s*(\w+)\s*\(([^)]*)\)\]', re.DOTALL
    )

    _PARAM_RE = re.compile(
        r'(\w+)=("(?:[^"\\]|\\.)*"|[^,\s]+)',
    )

    @classmethod
    def parse(cls, text: str) -> ToolCallResponse:
        """Parse *text* and return a :class:`ToolCallResponse`.

        If the text contains valid tool-call markers they are extracted
        into ``tool_calls``; the remaining text becomes ``text``.
        If no markers are found the entire input is treated as plain text.
        """
        if not text:
            return ToolCallResponse(text="")

        # Try JSON-array format first (most structured, highest fidelity).
        json_result = cls._try_parse_json_array(text)
        if json_result is not None:
            return json_result

        # Try single JSON-object format (some models omit the array wrapper).
        obj_result = cls._try_parse_json_object(text)
        if obj_result is not None:
            return obj_result

        # Fall back to XML-tag format.
        xml_result = cls._try_parse_xml(text)
        if xml_result is not None:
            return xml_result

        return ToolCallResponse(text=text.strip())

    @classmethod
    def _try_parse_json_array(cls, text: str) -> ToolCallResponse | None:
        """Attempt to parse a JSON array of tool calls from *text*."""
        match = cls._JSON_ARRAY_RE.search(text)
        if match is None:
            return None

        raw = match.group(0)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, list):
            return None

        calls: list[ToolCall] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("tool_name") or item.get("tool")
            if not name or not isinstance(name, str):
                continue
            arguments = item.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ToolCall(
                    id=item.get("id", f"call_{len(calls) + 1}"),
                    name=name,
                    arguments=arguments,
                )
            )

        if not calls:
            return None

        # Strip the consumed JSON from the surrounding text.
        remaining = (text[: match.start()] + text[match.end():]).strip()
        return ToolCallResponse(text=remaining, tool_calls=calls)

    @classmethod
    def _try_parse_json_object(cls, text: str) -> ToolCallResponse | None:
        """Attempt to parse a single JSON object tool call from *text*.

        Handles the format emitted by some models that omit the array
        wrapper: ``{"name": "tool", "arguments": {...}}``
        """
        match = cls._JSON_OBJECT_RE.search(text)
        if match is None:
            return None

        raw = match.group(0)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        name = data.get("name") or data.get("tool_name") or data.get("tool")
        if not name or not isinstance(name, str):
            return None

        arguments = data.get("arguments", {})
        if not isinstance(arguments, dict):
            arguments = {}

        calls = [
            ToolCall(
                id=data.get("id", "call_1"),
                name=name,
                arguments=arguments,
            )
        ]

        remaining = (text[: match.start()] + text[match.end():]).strip()
        return ToolCallResponse(text=remaining, tool_calls=calls)

    @classmethod
    def _try_parse_xml(cls, text: str) -> ToolCallResponse | None:
        """Attempt to parse XML-tag-style tool calls from *text*."""
        matches = list(cls._XML_TAG_RE.finditer(text))
        if not matches:
            return None

        calls: list[ToolCall] = []
        for m in matches:
            name = m.group(1)
            params_str = m.group(2).strip()
            arguments: dict[str, Any] = {}
            if params_str:
                for pm in cls._PARAM_RE.finditer(params_str):
                    key = pm.group(1)
                    val = pm.group(2)
                    if val.startswith('"') and val.endswith('"'):
                        val = val[1:-1]
                    arguments[key] = val
            calls.append(
                ToolCall(
                    id=f"call_{len(calls) + 1}",
                    name=name,
                    arguments=arguments,
                )
            )

        remaining = cls._XML_TAG_RE.sub("", text).strip()
        return ToolCallResponse(text=remaining, tool_calls=calls)


class ToolSchemaExporter:
    """Builds OpenAI-compatible function schemas from a :class:`ToolRegistry`.

    This is the **single source of truth** for tool schemas shared by
    the Chat path, the Agent path, and any future provider backends.
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry

    @property
    def registry(self) -> ToolRegistry | None:
        return self._registry

    def set_registry(self, registry: ToolRegistry | None) -> None:
        self._registry = registry

    def export_schemas(
        self,
        *,
        include_disabled: bool = False,
        include_unsupported: bool = True,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-style function schemas for all compatible tools.

        Parameters
        ----------
        include_disabled
            When False (default), disabled tools are excluded — they
            cannot be called by the model.
        include_unsupported
            When True (default), tools that are unsupported by the
            current model are still included (the model may reference
            them even if it cannot use them).  Set to False to strictly
            limit schemas to model-compatible tools only.
        """
        if self._registry is None:
            return []

        from tools.compatibility import ToolCompatibilityEvaluator

        eval_ = ToolCompatibilityEvaluator(registry=self._registry)
        schemas: list[dict[str, Any]] = []
        for tool_name in self._registry.list_all_tool_names():
            if not self._registry.is_installed(tool_name):
                continue
            if not include_disabled and not self._registry.is_enabled(tool_name):
                continue
            if not include_unsupported:
                status = eval_.get_tool_availability(tool_name)
                if status == ToolStatus.UNSUPPORTED_BY_MODEL.value:
                    continue
            schema = self._build_schema(self._registry.get(tool_name))
            if schema is not None:
                schemas.append(schema)
        return schemas

    def export_schemas_for_llm(self) -> list[dict[str, Any]]:
        """Convenience: schemas for all enabled, installed tools.

        This is the default view used by both the Chat and Agent paths.
        """
        return self.export_schemas(include_disabled=False, include_unsupported=True)

    @staticmethod
    def _build_schema(tool: Any) -> dict[str, Any] | None:
        """Build an OpenAI-style ``{"type":"function","function":{...}}`` dict."""
        if tool is None:
            return None

        input_schema = tool.get_input_schema()
        schema_properties = input_schema.get("properties", {})
        schema_required = input_schema.get("required", [])

        md: ToolMetadata | None = tool.get_metadata()

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": md.description if md else tool.description,
                "parameters": {
                    "type": "object",
                    "properties": schema_properties,
                    "required": schema_required,
                },
            },
        }


_MAX_TOOL_CALL_ITERATIONS = _MAX_ITERATIONS


def format_tool_result(tool_name: str, result: Any) -> str:
    """Format a :class:`ToolResult` as an LLM-readable observation block.

    The format is designed to be human-readable yet structured enough
    that the model can parse and act on it.
    """
    import json

    result_dict = {
        "tool_name": tool_name,
        "success": result.success,
        "message": result.message,
        "data": result.data,
        "error": result.error,
    }
    json_str = json.dumps(result_dict, ensure_ascii=False, default=str)
    return f"[TOOL_RESULT] {json_str}"


def format_tool_instructions(schemas: list[dict[str, Any]]) -> str:
    """Build the instruction text injected into the system prompt."""
    if not schemas:
        return ""

    lines: list[str] = ["Available tools:"]
    for s in schemas:
        fn = s.get("function", {})
        name = fn.get("name", "?")
        desc = fn.get("description", "")
        params = fn.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])

        if props:
            param_strs = []
            for pname, pinfo in props.items():
                ptype = pinfo.get("type", "string")
                req = " (required)" if pname in required else " (optional)"
                param_strs.append(f"  {pname}: {ptype}{req}")
            param_desc = "; ".join(param_strs)
        else:
            param_desc = "no parameters"

        lines.append(f"- {name}: {desc} | params: {param_desc}")

    lines.append("")
    lines.append(
        "To call a tool, emit a JSON array on a single line "
        '[{"name": "tool_name", "arguments": {"key": "value"}}]. '
        "Wait for the tool result before making additional calls."
    )
    return "\n".join(lines)
