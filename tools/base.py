"""Tool system base — abstract Tool, ToolResult, and a thread-safe registry.

Design rules (from Architecture_Design.md & Security_Design.md):
  * Every tool implements a uniform interface: ``name``, ``description``,
    ``parameters``, and ``execute``.
  * AI can **never** call system commands directly — it must go through a
    registered Tool.
  * Destructive actions (``risk_level >= 2``) require explicit user
    confirmation before the registry dispatches them.  This gate is the
    MVP version of the full Security Layer (Phase 6).

Phase 1 enhancements (Tool Arsenal Foundation):
  * Tools carry optional :class:`ToolMetadata` describing version, source,
    trust, dependencies, model requirements, and JSON schemas.
  * The registry tracks installed/enabled state and publishes lifecycle
    events (``TOOL_REGISTERED``, ``TOOL_UNREGISTERED``, ``TOOL_ENABLED``,
    ``TOOL_DISABLED``).
  * Disabled tools are refused execution with a clear ``ToolDisabled`` error.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, ClassVar

from core.event_bus import EventBus
from core.logger import get_logger
from security.models import ToolCategory

if TYPE_CHECKING:
    from tools.models import ToolMetadata

logger = get_logger("tools")

ConfirmCallback = Callable[[str, str, str | None], bool]


class RiskLevel(IntEnum):
    """How dangerous a tool action is (0 = read-only info, 3 = irreversible)."""

    INFO = 0
    READ_ONLY = 1
    WRITE = 2
    DESTRUCTIVE = 3


@dataclass
class ParameterSpec:
    """Metadata describing a single tool parameter."""

    name: str
    type: str = "string"
    description: str = ""
    required: bool = True


@dataclass
class ToolResult:
    """Structured return value for every tool execution."""

    success: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tool_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
            "error": self.error,
            "tool_name": self.tool_name,
        }


class Tool(ABC):
    """Abstract base every tool must implement.

    Subclasses may override ``metadata`` (class-level :class:`ToolMetadata`)
    via ``get_metadata()`` or the ``_metadata`` instance hook.  When no
    metadata is provided the registry derives a sensible default from the
    tool's class attributes.
    """

    name: str = ""
    description: str = ""
    category: ToolCategory = ToolCategory.GENERAL
    parameters: ClassVar[list[ParameterSpec]] = []
    risk_level: RiskLevel = RiskLevel.INFO

    @abstractmethod
    def execute(self, **params: Any) -> ToolResult:
        """Run the tool.  Raises no raw exceptions — wrap in ToolResult."""

    def validate(self, params: dict[str, Any]) -> str | None:
        """Return an error message string if *params* are invalid, else None."""
        for spec in self.parameters:
            if spec.required and spec.name not in params:
                return f"Missing required parameter: {spec.name}"
        return None

    def requires_confirmation(self) -> bool:
        """True when the action is risky enough to need user approval."""
        return self.risk_level >= RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata | None:
        """Return the tool's metadata if declared, else None.

        Subclasses override this to return richer metadata.  The default
        implementation checks for a class-level ``_metadata`` attribute.
        """
        return getattr(self, "_metadata", None)

    def get_input_schema(self) -> dict[str, Any]:
        """Return a JSON Schema describing accepted parameters.

        Default implementation derives a schema from ``self.parameters``.
        Subclasses override for richer schemas.
        """
        if hasattr(self, "_metadata") and self._metadata and self._metadata.input_schema:
            return dict(self._metadata.input_schema)

        properties: dict[str, Any] = {}
        required: list[str] = []
        for spec in self.parameters:
            properties[spec.name] = {
                "type": spec.type,
                "description": spec.description,
            }
            if spec.required:
                required.append(spec.name)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    def get_output_schema(self) -> dict[str, Any]:
        """Return a JSON Schema describing the return value.

        Default: empty schema (no constraint).  Subclasses override.
        """
        if hasattr(self, "_metadata") and self._metadata and self._metadata.output_schema:
            return dict(self._metadata.output_schema)
        return {}


def _risk_level_name(risk: RiskLevel | int | str) -> str:
    """Normalize a risk_level value to a lowercase string name."""
    if isinstance(risk, RiskLevel):
        return risk.name.lower()
    if isinstance(risk, int):
        return RiskLevel(risk).name.lower()
    return str(risk).lower()


def _build_default_metadata(tool: Tool) -> ToolMetadata:
    """Construct ToolMetadata from a Tool's class attributes when none is set."""
    from tools.models import ToolMetadata, ToolSource, ToolTrust

    return ToolMetadata(
        tool_id=(tool.name or tool.__class__.__name__).lower().replace(" ", "_"),
        name=tool.name,
        description=tool.description,
        category=tool.category,
        source=ToolSource.BUILTIN,
        risk_level=_risk_level_name(tool.risk_level),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=ToolMetadata._detect_platforms(),
        permissions=(),
        model_requirements=(),
        input_schema=tool.get_input_schema(),
        output_schema=tool.get_output_schema(),
        trust_level=ToolTrust.TRUSTED,
        installation_source="",
        supports_llm_schema=False,
    )


class ToolRegistry:
    """Thread-safe registry + executor of all tools.

    The registry is the single execution gateway.  All tool invocations
    flow through :meth:`execute`, which enforces disabled-tool checks,
    parameter validation, confirmation callbacks, and event publishing.

    Phase 1 additions:
      * Tools track ``installed`` and ``enabled`` state.
      * ``list_tools()`` returns enabled tools only (backward compatible).
      * ``list_all_tools()`` returns all registered tools regardless of state.
      * Lifecycle events: ``TOOL_REGISTERED``, ``TOOL_UNREGISTERED``,
        ``TOOL_ENABLED``, ``TOOL_DISABLED``.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._tools: dict[str, Tool] = {}
        self._metadata: dict[str, ToolMetadata | None] = {}
        self._disabled: set[str] = set()
        self._event_bus = event_bus
        self._confirm_callback: ConfirmCallback | None = None

    # ------------------------------------------------------------------ #
    # Registration
    # ------------------------------------------------------------------ #
    def register(self, tool: Tool, metadata: ToolMetadata | None = None) -> None:
        """Register *tool* in the registry.

        If *metadata* is None, the tool's own ``get_metadata()`` is tried.
        Failing that, metadata is derived from the tool's class attributes.
        """
        self._tools[tool.name] = tool

        md = metadata or tool.get_metadata()
        if md is None:
            md = _build_default_metadata(tool)
        self._metadata[tool.name] = md

        if tool.name not in self._disabled:
            self._disabled.discard(tool.name)
        else:
            self._disabled.add(tool.name)

        logger.debug("Tool registered: %s (source=%s, trust=%s)",
                      tool.name, md.source.value, md.trust_level.value)
        self._publish("TOOL_REGISTERED", data={
            "tool": tool.name,
            "tool_id": md.tool_id,
            "source": md.source.value,
            "trust_level": md.trust_level.value,
        })

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)
        self._metadata.pop(name, None)
        self._disabled.discard(name)
        logger.debug("Tool unregistered: %s", name)
        self._publish("TOOL_UNREGISTERED", data={"tool": name})

    # ------------------------------------------------------------------ #
    # Lookup
    # ------------------------------------------------------------------ #
    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_metadata(self, name: str) -> ToolMetadata | None:
        return self._metadata.get(name)

    def list_tools(self) -> list[dict[str, Any]]:
        """Return *enabled* tools as dicts (backward-compatible API).

        Disabled tools are excluded so existing consumers (Agent whitelist,
        LLMPlanner tool exposure, etc.) automatically respect the disabled
        state.
        """
        result: list[dict[str, Any]] = []
        for t in self._tools.values():
            if t.name in self._disabled:
                continue
            md = self._metadata.get(t.name)
            entry: dict[str, Any] = {
                "name": t.name,
                "description": t.description,
                "parameters": [p.__dict__ for p in t.parameters],
                "risk_level": int(t.risk_level),
                "category": t.category.value if t.category else "general",
                "enabled": True,
                "installed": True,
            }
            if md is not None:
                entry["tool_id"] = md.tool_id
                entry["version"] = md.version
                entry["source"] = md.source.value if md.source else "builtin"
                entry["trust_level"] = md.trust_level.value if md.trust_level else "trusted"
                entry["offline"] = md.offline
                entry["requires_network"] = md.requires_network
                entry["model_requirements"] = list(md.model_requirements)
            result.append(entry)
        return result

    def list_all_tools(self) -> list[dict[str, Any]]:
        """Return *all* registered tools including disabled ones."""
        result: list[dict[str, Any]] = []
        for t in self._tools.values():
            md = self._metadata.get(t.name)
            is_disabled = t.name in self._disabled
            entry: dict[str, Any] = {
                "name": t.name,
                "description": t.description,
                "parameters": [p.__dict__ for p in t.parameters],
                "risk_level": int(t.risk_level),
                "category": t.category.value if t.category else "general",
                "enabled": not is_disabled,
                "installed": True,
            }
            if md is not None:
                entry["tool_id"] = md.tool_id
                entry["version"] = md.version
                entry["source"] = md.source.value if md.source else "builtin"
                entry["trust_level"] = md.trust_level.value if md.trust_level else "trusted"
                entry["offline"] = md.offline
                entry["requires_network"] = md.requires_network
                entry["model_requirements"] = list(md.model_requirements)
            result.append(entry)
        return result

    def list_all_tool_names(self) -> list[str]:
        """Return names of all registered tools regardless of enabled state."""
        return list(self._tools.keys())

    # ------------------------------------------------------------------ #
    # Enable / disable
    # ------------------------------------------------------------------ #
    def enable(self, name: str) -> bool:
        """Enable a previously disabled tool."""
        if name not in self._tools:
            return False
        was_disabled = name in self._disabled
        self._disabled.discard(name)
        if was_disabled:
            logger.info("Tool enabled: %s", name)
            self._publish("TOOL_ENABLED", data={"tool": name})
        return True

    def disable(self, name: str) -> bool:
        """Disable a tool — it remains registered but cannot execute."""
        if name not in self._tools:
            return False
        if name not in self._disabled:
            self._disabled.add(name)
            logger.info("Tool disabled: %s", name)
            self._publish("TOOL_DISABLED", data={"tool": name})
            return True
        return False

    def is_enabled(self, name: str) -> bool:
        """True when the tool is registered and not disabled."""
        return name in self._tools and name not in self._disabled

    def is_installed(self, name: str) -> bool:
        """True when the tool is registered in the registry."""
        return name in self._tools

    def export_tool_schemas(
        self,
        *,
        include_disabled: bool = False,
        include_unsupported: bool = True,
    ) -> list[dict[str, Any]]:
        """Return OpenAI-compatible function schemas for registered tools.

        Delegates to :class:`ToolSchemaExporter` — the single source of
        truth shared by the Chat path, Agent path, and provider backends.

        Parameters
        ----------
        include_disabled
            When False (default), disabled tools are excluded.
        include_unsupported
            When True (default), tools unsupported by the current model
            are still included.  Set to False to return only
            model-compatible schemas.
        """
        from ai.engine.tool_calling import ToolSchemaExporter

        return ToolSchemaExporter(registry=self).export_schemas(
            include_disabled=include_disabled,
            include_unsupported=include_unsupported,
        )

    def export_schemas_for_llm(self) -> list[dict[str, Any]]:
        """Convenience wrapper: enabled + installed tool schemas for LLM."""
        return self.export_tool_schemas(include_disabled=False, include_unsupported=True)

    # ------------------------------------------------------------------ #
    # Confirmation callback
    # ------------------------------------------------------------------ #
    def set_confirmation_callback(self, callback: ConfirmCallback) -> None:
        """Set a callback invoked for risky actions.  Returns True if allowed."""
        self._confirm_callback = callback

    # ------------------------------------------------------------------ #
    # Execution (single gateway — never bypass)
    # ------------------------------------------------------------------ #
    def execute(
        self,
        name: str,
        params: dict[str, Any] | None = None,
        permission_profile: str | None = None,
    ) -> ToolResult:
        params = params or {}

        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                success=False, message=f"Tool '{name}' not registered",
                tool_name=name, error="NotRegistered",
            )

        if name in self._disabled:
            return ToolResult(
                success=False, message=f"Tool '{name}' is disabled",
                tool_name=name, error="ToolDisabled",
            )

        validation_error = tool.validate(params)
        if validation_error:
            return ToolResult(
                success=False, message=validation_error, tool_name=name,
                error="InvalidParameters",
            )

        if tool.requires_confirmation():
            if self._confirm_callback is None:
                return ToolResult(
                    success=False,
                    message=(
                        f"'{name}' requires user confirmation but no callback is set"
                    ),
                    tool_name=name,
                    error="ConfirmationRequired",
                )
            allowed = self._confirm_callback(tool.name, tool.description, permission_profile)
            if not allowed:
                self._publish("TOOL_BLOCKED", data={"tool": name, "reason": "user_denied"})
                return ToolResult(
                    success=False, message="Action cancelled by user", tool_name=name,
                    error="UserDenied",
                )

        self._publish("TOOL_EXECUTING", data={"tool": name, "params": params})
        try:
            result = tool.execute(**params)
            result.tool_name = result.tool_name or name
            self._publish(
                "TOOL_EXECUTED",
                data={"tool": name, "success": result.success},
            )
            return result
        except Exception as exc:
            logger.exception("Tool '%s' raised an exception", name)
            return ToolResult(
                success=False, message=str(exc), tool_name=name,
                error=type(exc).__name__,
            )

    def _publish(self, event: str, data: dict[str, Any] | None = None) -> None:
        if self._event_bus is not None:
            self._event_bus.publish(event, data=data)
