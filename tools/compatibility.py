"""Tool compatibility — evaluates which tools a model can use.

The evaluator determines tool availability *relative to the current model*
but never removes tools from the registry.  Unsupported tools remain fully
registered and visible in the arsenal.

Dependency note: imports ``tools.base.ToolMetadata`` only at runtime (via
``TYPE_CHECKING``) to avoid circular imports with ``tools.base``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.logger import get_logger

if TYPE_CHECKING:
    from ai.models.model_loader import ModelCapabilities
    from tools.base import ToolRegistry
    from tools.catalog import ToolCatalog

logger = get_logger("tools.compatibility")


class ToolCompatibilityEvaluator:
    """Evaluates which registered tools a model can invoke.

    The evaluator maps each registered tool's ``model_requirements`` against
    the active model's :class:`ModelCapabilities`.  A tool with empty
    ``model_requirements`` is considered callable by *any* model (e.g. through
    heuristic/keyword-based invocation paths, agent planning, or application
    logic — not necessarily native LLM function calling).
    """

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry
        self._model_capabilities: ModelCapabilities | None = None
        self._catalog: ToolCatalog | None = None

    @property
    def registry(self) -> ToolRegistry | None:
        return self._registry

    def set_registry(self, registry: ToolRegistry | None) -> None:
        self._registry = registry

    def set_model_capabilities(self, caps: ModelCapabilities | None) -> None:
        """Set the currently loaded model's capabilities for evaluation."""
        self._model_capabilities = caps

    def clear_model(self) -> None:
        """Clear the model so all installed tools are treated as "no requirements check active"."""
        self._model_capabilities = None

    def set_catalog(self, catalog: ToolCatalog | None) -> None:
        """Inject the external tool catalog for discovered-tool visibility."""
        self._catalog = catalog

    def get_tool_availability(self, tool_id_or_name: str) -> str:
        """Return a :class:`ToolStatus` value name for a single tool.

        Returns one of: ``AVAILABLE``, ``UNSUPPORTED_BY_MODEL``, ``DISABLED``,
        ``NOT_INSTALLED``.
        """
        from tools.models import ToolStatus

        if self._registry is None:
            return ToolStatus.NOT_INSTALLED.value

        if not self._registry.is_installed(tool_id_or_name):
            return ToolStatus.NOT_INSTALLED.value

        if not self._registry.is_enabled(tool_id_or_name):
            return ToolStatus.DISABLED.value

        if not self._check_model_requirements(tool_id_or_name):
            return ToolStatus.UNSUPPORTED_BY_MODEL.value

        return ToolStatus.AVAILABLE.value

    def get_available_tools(self) -> list[str]:
        """Names of all installed, enabled, model-compatible tools."""
        if self._registry is None:
            return []
        result: list[str] = []
        for name in self._registry.list_all_tool_names():
            if self._registry.is_installed(name) and self._registry.is_enabled(name) and self._check_model_requirements(name):
                    result.append(name)
        return result

    def get_unsupported_tools(self) -> list[str]:
        """Names of installed, enabled tools the current model cannot use."""
        if self._registry is None:
            return []
        result: list[str] = []
        for name in self._registry.list_all_tool_names():
            if self._registry.is_installed(name) and self._registry.is_enabled(name) and not self._check_model_requirements(name):
                result.append(name)
        return result

    def get_disabled_tools(self) -> list[str]:
        """Names of all disabled tools."""
        if self._registry is None:
            return []
        return [n for n in self._registry.list_all_tool_names() if not self._registry.is_enabled(n)]

    def get_not_installed_tools(self, known_ids: list[str] | None = None) -> list[str]:
        """Return tool IDs that are expected but not installed.

        When *known_ids* is provided, the evaluator checks each against the
        registry.  This supports the future "tool not found" detection flow
        without requiring a full tool catalog in Phase 1.
        """
        if self._registry is None:
            return list(known_ids or [])
        result: list[str] = []
        for tid in known_ids or []:
            if not self._registry.is_installed(tid):
                result.append(tid)
        return result

    def get_all_tool_statuses(self) -> dict[str, str]:
        """Map every registered tool name → ToolStatus value.

        Tools not in the registry are not included (they are simply absent).
        """
        if self._registry is None:
            return {}
        statuses: dict[str, str] = {}
        for name in self._registry.list_all_tool_names():
            statuses[name] = self.get_tool_availability(name)
        return statuses

    def list_all_with_status(self) -> list[dict[str, Any]]:
        """Return full metadata + status for every registered tool.

        When a catalog is set, also includes discovered (not-yet-installed)
        external tools with ``status=NOT_INSTALLED`` so they remain visible
        in the Tools UI.  This is the primary API for the Tools Arsenal UI page.
        """
        from tools.models import ToolStatus

        result: list[dict[str, Any]] = []

        if self._registry is not None:
            for name in self._registry.list_all_tool_names():
                md = self._registry.get_metadata(name)
                if md is not None:
                    entry = md.to_dict()
                else:
                    entry = {
                        "tool_id": name,
                        "name": name,
                        "description": "",
                        "version": "0.0.0",
                        "category": "general",
                        "source": "builtin",
                        "risk_level": "info",
                        "installed": True,
                        "enabled": True,
                        "offline": True,
                        "requires_network": False,
                        "dependencies": [],
                        "supported_platforms": [],
                        "permissions": [],
                        "model_requirements": [],
                        "input_schema": {},
                        "output_schema": {},
                        "icon": "",
                        "author": "",
                        "homepage": "",
                        "trust_level": "trusted",
                        "installation_source": "",
                        "supports_llm_schema": False,
                    }
                entry["tool_name"] = name
                entry["enabled"] = self._registry.is_enabled(name)
                entry["installed"] = self._registry.is_installed(name)
                entry["status"] = self.get_tool_availability(name)
                entry["status_display"] = ToolStatus(entry["status"]).display_name
                result.append(entry)

        # Append discovered (not-yet-installed) external tools from catalog
        if self._catalog is not None:
            registered_ids = {
                entry["tool_id"] for entry in result
            } if self._registry is not None else set()
            for cat_entry in self._catalog.list_all():
                tool_id = cat_entry.get("tool_id", "")
                if tool_id in registered_ids:
                    continue  # already in the registry
                result.append(self._catalog_entry_to_dict(cat_entry))

        return result

    def _catalog_entry_to_dict(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Convert a catalog entry to the dict format used by the Tools UI."""
        from tools.manifest import ToolState
        from tools.models import ToolStatus

        tool_id = entry.get("tool_id", "")
        tool_state = entry.get("tool_state", ToolState.DISCOVERED.value)
        installed = entry.get("installed", False)
        enabled = entry.get("enabled", False)
        error = entry.get("error")

        if tool_state == ToolState.FAILED.value:
            status = ToolStatus.FAILED.value
        elif not installed:
            status = ToolStatus.NOT_INSTALLED.value
        elif not enabled:
            status = ToolStatus.DISABLED.value
        elif not self._check_model_requirements(tool_id):
            status = ToolStatus.UNSUPPORTED_BY_MODEL.value
        else:
            status = ToolStatus.AVAILABLE.value

        return {
            "tool_id": tool_id,
            "name": entry.get("name", tool_id),
            "description": entry.get("description", ""),
            "version": entry.get("version", "0.0.0"),
            "category": entry.get("category", "general"),
            "source": entry.get("source", "user"),
            "risk_level": entry.get("risk_level", "info"),
            "installed": installed,
            "enabled": enabled,
            "offline": entry.get("offline", True),
            "requires_network": entry.get("requires_network", False),
            "dependencies": entry.get("dependencies", []),
            "supported_platforms": entry.get("supported_platforms", []),
            "permissions": entry.get("permissions", []),
            "model_requirements": entry.get("model_requirements", []),
            "input_schema": entry.get("input_schema", {}),
            "output_schema": entry.get("output_schema", {}),
            "icon": entry.get("icon", ""),
            "author": entry.get("author", ""),
            "homepage": entry.get("homepage", ""),
            "trust_level": entry.get("trust_level", "unverified"),
            "installation_source": entry.get("entry_point", ""),
            "supports_llm_schema": entry.get("supports_llm_schema", False),
            "tool_name": tool_id,
            "status": status,
            "status_display": ToolStatus(status).display_name,
            "tool_state": tool_state,
            "error": error,
        }

    def _check_model_requirements(self, tool_name: str) -> bool:
        """Return True if the current model satisfies the tool's requirements.

        - No model set → no model requirements check → all tools pass.
        - Empty ``model_requirements`` → tool is compatible with any model.
        - Non-empty requirements → model must satisfy all.
        """
        if self._model_capabilities is None:
            return True

        if self._registry is None:
            return True

        md = self._registry.get_metadata(tool_name)
        if md is None:
            return True

        requirements = md.model_requirements
        if not requirements:
            return True

        return self._model_capabilities.is_compatible_with(list(requirements))
