"""Tool metadata and classification models for the Tool Arsenal.

This module provides the data structures that describe tools independently of
any individual model.  Tools belong to the **application**, not to a model.
Model capabilities only determine *compatibility* — they do not determine
existence.

Dependency note: imports ``security.models.ToolCategory`` (backward-compatible
enum) and ``tools.base.RiskLevel``.  No circular import because
``tools/base.py`` uses ``TYPE_CHECKING`` for ``ToolMetadata``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from security.models import ToolCategory


class ToolSource(Enum):
    """Where a tool originates from — distinguishes built-in from external."""

    BUILTIN = "builtin"
    PLUGIN = "plugin"
    INSTALLED_PACKAGE = "installed_package"
    USER = "user"

    @property
    def display_name(self) -> str:
        names = {
            ToolSource.BUILTIN: "Built-in",
            ToolSource.PLUGIN: "Plugin",
            ToolSource.INSTALLED_PACKAGE: "Installed Package",
            ToolSource.USER: "User",
        }
        return names.get(self, self.value)


class ToolTrust(Enum):
    """Trust level for a tool — never auto-escalates."""

    TRUSTED = "trusted"
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    BLOCKED = "blocked"

    @property
    def display_name(self) -> str:
        names = {
            ToolTrust.TRUSTED: "Trusted",
            ToolTrust.VERIFIED: "Verified",
            ToolTrust.UNVERIFIED: "Unverified",
            ToolTrust.BLOCKED: "Blocked",
        }
        return names.get(self, self.value)


class ToolStatus(Enum):
    """Runtime status of a tool in the arsenal."""

    INSTALLED = "installed"
    AVAILABLE = "available"
    DISABLED = "disabled"
    MISSING_DEPS = "missing_deps"
    NOT_INSTALLED = "not_installed"
    UNSUPPORTED_BY_MODEL = "unsupported_by_model"
    INVALID = "invalid"
    FAILED = "failed"

    @property
    def display_name(self) -> str:
        names = {
            ToolStatus.INSTALLED: "Installed",
            ToolStatus.AVAILABLE: "Available",
            ToolStatus.DISABLED: "Disabled",
            ToolStatus.MISSING_DEPS: "Missing Dependencies",
            ToolStatus.NOT_INSTALLED: "Not Installed",
            ToolStatus.UNSUPPORTED_BY_MODEL: "Unsupported by Model",
            ToolStatus.INVALID: "Invalid",
            ToolStatus.FAILED: "Failed",
        }
        return names.get(self, self.value)


@dataclass(frozen=True)
class ToolMetadata:
    """First-class metadata describing a tool in the arsenal.

    Fields use safe immutable defaults.  ``from_dict`` handles missing
    optional fields gracefully for backward compatibility.
    """

    tool_id: str
    name: str
    description: str = ""
    version: str = "0.0.0"
    category: ToolCategory = ToolCategory.GENERAL
    source: ToolSource = ToolSource.BUILTIN
    risk_level: str = "info"
    installed: bool = True
    enabled: bool = True
    offline: bool = True
    requires_network: bool = False
    dependencies: tuple[str, ...] = ()
    supported_platforms: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    model_requirements: tuple[str, ...] = ()
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    icon: str = ""
    author: str = ""
    homepage: str = ""
    trust_level: ToolTrust = ToolTrust.TRUSTED
    installation_source: str = ""
    supports_llm_schema: bool = False

    def __post_init__(self) -> None:
        if not self.tool_id:
            object.__setattr__(self, "tool_id", self.name.lower().replace(" ", "_"))

    @classmethod
    def _detect_platforms(cls) -> tuple[str, ...]:
        """Return all supported platforms.

        All built-in tools use cross-platform Python stdlib APIs or
        ``psutil``, so they are available on all supported platforms:
        windows, linux, and macOS.  This is intentionally unconditional
        — platform-specific filtering is handled at runtime by
        :class:`ToolCompatibilityEvaluator` via ``model_requirements``,
        not by platform tags.
        """
        return ("windows", "linux", "macos")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category.value if self.category else "general",
            "source": self.source.value if self.source else "builtin",
            "risk_level": self.risk_level,
            "installed": self.installed,
            "enabled": self.enabled,
            "offline": self.offline,
            "requires_network": self.requires_network,
            "dependencies": list(self.dependencies),
            "supported_platforms": list(self.supported_platforms),
            "permissions": list(self.permissions),
            "model_requirements": list(self.model_requirements),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "icon": self.icon,
            "author": self.author,
            "homepage": self.homepage,
            "trust_level": self.trust_level.value if self.trust_level else "trusted",
            "installation_source": self.installation_source,
            "supports_llm_schema": self.supports_llm_schema,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolMetadata:
        if not isinstance(data, dict):
            raise TypeError("ToolMetadata.from_dict requires a dict")

        cat_val = data.get("category", "general")
        if isinstance(cat_val, str):
            try:
                category = ToolCategory(cat_val)
            except ValueError:
                category = ToolCategory.GENERAL
        elif isinstance(cat_val, ToolCategory):
            category = cat_val
        else:
            category = ToolCategory.GENERAL

        source_val = data.get("source", "builtin")
        if isinstance(source_val, str):
            try:
                source = ToolSource(source_val)
            except ValueError:
                source = ToolSource.BUILTIN
        elif isinstance(source_val, ToolSource):
            source = source_val
        else:
            source = ToolSource.BUILTIN

        trust_val = data.get("trust_level")
        if trust_val is None:
            trust = ToolTrust.UNVERIFIED
        elif isinstance(trust_val, str):
            try:
                trust = ToolTrust(trust_val)
            except ValueError:
                trust = ToolTrust.UNVERIFIED
        elif isinstance(trust_val, ToolTrust):
            trust = trust_val
        else:
            trust = ToolTrust.UNVERIFIED

        deps_raw = data.get("dependencies", [])
        deps = tuple(str(d) for d in deps_raw) if isinstance(deps_raw, (list, tuple)) else ()

        plats_raw = data.get("supported_platforms", [])
        plats = tuple(str(p) for p in plats_raw) if isinstance(plats_raw, (list, tuple)) else ()

        perms_raw = data.get("permissions", [])
        perms = tuple(str(p) for p in perms_raw) if isinstance(perms_raw, (list, tuple)) else ()

        reqs_raw = data.get("model_requirements", [])
        reqs = tuple(str(r) for r in reqs_raw) if isinstance(reqs_raw, (list, tuple)) else ()

        in_schema = data.get("input_schema", {})
        out_schema = data.get("output_schema", {})

        return cls(
            tool_id=str(data.get("tool_id", "")),
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            version=str(data.get("version", "0.0.0")),
            category=category,
            source=source,
            risk_level=str(data.get("risk_level", "info")),
            installed=bool(data.get("installed", True)),
            enabled=bool(data.get("enabled", True)),
            offline=bool(data.get("offline", True)),
            requires_network=bool(data.get("requires_network", False)),
            dependencies=deps,
            supported_platforms=plats,
            permissions=perms,
            model_requirements=reqs,
            input_schema=dict(in_schema) if isinstance(in_schema, dict) else {},
            output_schema=dict(out_schema) if isinstance(out_schema, dict) else {},
            icon=str(data.get("icon", "")),
            author=str(data.get("author", "")),
            homepage=str(data.get("homepage", "")),
            trust_level=trust,
            installation_source=str(data.get("installation_source", "")),
            supports_llm_schema=bool(data.get("supports_llm_schema", False)),
        )
