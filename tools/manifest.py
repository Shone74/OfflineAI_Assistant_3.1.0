"""External tool manifest format and validation.

A manifest is a versioned JSON description of an external tool that can be
discovered, validated, and explicitly installed into the ToolRegistry.  The
manifest reuses :class:`~tools.models.ToolMetadata` concepts (category, risk
level, trust level, schemas, permissions, model requirements) so that
installed external tools carry the same metadata as built-in tools.

Design rules (Phase 2D security boundaries):
  * Manifests are **data only** — they never contain executable code.
  * The ``entry_point`` field is a ``module:attr`` string resolved via
    ``importlib`` only during explicit installation, never during discovery.
  * The ``format_version`` field is required and must be a known version
    (``"1.0"``).  Unknown versions are rejected, not silently downgraded.
  * Trust level and risk level are validated against their respective enums
    and are never auto-escalated.
  * Schemas are validated to be JSON objects (dicts).  Empty schemas are
    valid (meaning "accept any input").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import get_logger
from security.models import ToolCategory
from tools.models import ToolMetadata, ToolSource, ToolTrust

logger = get_logger("tools.manifest")

MANIFEST_FORMAT_VERSION = "1.0"
_SUPPORTED_FORMAT_VERSIONS: frozenset[str] = frozenset({MANIFEST_FORMAT_VERSION})

_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9._-]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].*)?$")
_VALID_RISK_LEVELS = frozenset({"info", "read_only", "write", "destructive"})
_VALID_TRUST_LEVELS = frozenset(t.value for t in ToolTrust)
_VALID_SOURCES = frozenset(s.value for s in ToolSource)
_VALID_CATEGORIES = frozenset(c.value for c in ToolCategory)
_VALID_PLATFORMS = frozenset({"windows", "linux", "macos"})
_ENTRY_POINT_RE = re.compile(r"^[_a-zA-Z][_a-zA-Z0-9.]*:[_a-zA-Z][_a-zA-Z0-9_]*$")


class ToolState(Enum):
    """Lifecycle states an external tool transitions through.

    Mirrors the PluginState pattern from the plugin system.  The key
    distinction from :class:`~tools.models.ToolStatus` is that ``ToolState``
    describes the *installation* lifecycle, while ``ToolStatus`` describes
    runtime *availability* relative to model capability.
    """

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    INSTALL_REQUESTED = "install_requested"
    INSTALLING = "installing"
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"


@dataclass
class ToolManifest:
    """Parsed and validated external tool manifest.

    The manifest is the source of truth for the tool's static metadata and
    the entry point used during explicit installation.  It is created from
    a raw JSON dict via :meth:`from_dict`, which performs validation.  A
    :class:`ManifestValidationError` is raised on any validation failure.
    """

    format_version: str
    tool_id: str
    name: str
    entry_point: str
    description: str = ""
    version: str = "0.0.0"
    category: str = "general"
    source: str = "user"
    risk_level: str = "info"
    trust_level: str = "verified"
    offline: bool = True
    requires_network: bool = False
    supported_platforms: list[str] = field(default_factory=lambda: ["windows", "linux", "macos"])
    permissions: list[str] = field(default_factory=list)
    model_requirements: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    author: str = ""
    homepage: str = ""
    license: str = ""
    icon: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_metadata(self) -> ToolMetadata:
        """Convert to a :class:`ToolMetadata` for registry registration."""
        try:
            category = ToolCategory(self.category)
        except ValueError:
            category = ToolCategory.GENERAL

        return ToolMetadata(
            tool_id=self.tool_id,
            name=self.name,
            description=self.description,
            version=self.version,
            category=category,
            source=ToolSource(self.source),
            risk_level=self.risk_level,
            installed=True,
            enabled=True,
            offline=self.offline,
            requires_network=self.requires_network,
            supported_platforms=tuple(self.supported_platforms),
            permissions=tuple(self.permissions),
            model_requirements=tuple(self.model_requirements),
            input_schema=dict(self.input_schema),
            output_schema=dict(self.output_schema),
            icon=self.icon,
            author=self.author,
            homepage=self.homepage,
            trust_level=ToolTrust(self.trust_level),
            installation_source=self.entry_point,
            supports_llm_schema=False,
        )


class ManifestValidationError(Exception):
    """Raised when a manifest fails validation.

    The ``reason`` attribute provides a machine-readable validation failure
    code for testing and UI display.
    """

    def __init__(self, message: str, reason: str = "validation_error") -> None:
        super().__init__(message)
        self.reason = reason


def _check_schema(schema: Any, field_path: str) -> None:
    """Validate that *schema* is a JSON object dict.

    Per the manifest format spec, schemas must be JSON objects (dicts).
    When non-empty, a ``type`` key is recommended for documentation but
    not strictly required — empty schemas (meaning "any input") are valid.
    """
    if not isinstance(schema, dict):
        raise ManifestValidationError(
            f"Manifest field '{field_path}' must be a JSON object, got {type(schema).__name__}",
            reason=f"invalid_{field_path}",
        )


def validate_manifest(raw: Any) -> ToolManifest:
    """Validate a raw manifest dict and return a :class:`ToolManifest`.

    Raises :class:`ManifestValidationError` with a descriptive message and
    a machine-readable ``reason`` code on any validation failure.

    This function **never imports or executes** the tool's entry point.
    """
    if not isinstance(raw, dict):
        raise ManifestValidationError(
            "Manifest root must be a JSON object", reason="manifest_not_object"
        )

    # --- format_version (required) ---
    format_version = str(raw.get("format_version", "")).strip()
    if not format_version:
        raise ManifestValidationError(
            "Manifest is missing required field 'format_version'",
            reason="missing_format_version",
        )
    if format_version not in _SUPPORTED_FORMAT_VERSIONS:
        raise ManifestValidationError(
            f"Unsupported manifest format_version '{format_version}'. "
            f"Supported versions: {sorted(_SUPPORTED_FORMAT_VERSIONS)}",
            reason="unsupported_format_version",
        )

    # --- tool_id (required) ---
    tool_id = str(raw.get("tool_id", "")).strip()
    if not tool_id:
        raise ManifestValidationError(
            "Manifest is missing required field 'tool_id'",
            reason="missing_tool_id",
        )
    if not _TOOL_ID_RE.match(tool_id):
        raise ManifestValidationError(
            f"Invalid tool_id '{tool_id}': must be lowercase identifier "
            "(letters, digits, dots, underscores, hyphens; starting with a letter)",
            reason="invalid_tool_id",
        )

    # --- name (required) ---
    name = str(raw.get("name", "")).strip()
    if not name:
        raise ManifestValidationError(
            f"Manifest for tool '{tool_id}' is missing required field 'name'",
            reason="missing_name",
        )

    # --- entry_point (required) ---
    entry_point = str(raw.get("entry_point", "")).strip()
    if not entry_point:
        raise ManifestValidationError(
            f"Manifest for tool '{tool_id}' is missing required field 'entry_point'",
            reason="missing_entry_point",
        )
    if not _ENTRY_POINT_RE.match(entry_point):
        raise ManifestValidationError(
            f"Invalid entry_point '{entry_point}': must be 'module:attr' format",
            reason="invalid_entry_point",
        )

    # --- version (optional, validated if present) ---
    version = str(raw.get("version", "0.0.0")).strip()
    if not _SEMVER_RE.match(version):
        raise ManifestValidationError(
            f"Invalid version '{version}' for tool '{tool_id}': expected semver (e.g. 1.0.0)",
            reason="invalid_version",
        )

    # --- category (optional, validated) ---
    category = str(raw.get("category", "general")).strip()
    if category not in _VALID_CATEGORIES:
        raise ManifestValidationError(
            f"Invalid category '{category}' for tool '{tool_id}': "
            f"must be one of {sorted(_VALID_CATEGORIES)}",
            reason="invalid_category",
        )

    # --- source (optional, validated) ---
    source = str(raw.get("source", "user")).strip()
    if source not in _VALID_SOURCES:
        raise ManifestValidationError(
            f"Invalid source '{source}' for tool '{tool_id}': "
            f"must be one of {sorted(_VALID_SOURCES)}",
            reason="invalid_source",
        )

    # --- risk_level (optional, validated) ---
    risk_level = str(raw.get("risk_level", "info")).strip().lower()
    if risk_level not in _VALID_RISK_LEVELS:
        raise ManifestValidationError(
            f"Invalid risk_level '{risk_level}' for tool '{tool_id}': "
            f"must be one of {sorted(_VALID_RISK_LEVELS)}",
            reason="invalid_risk_level",
        )

    # --- trust_level (optional, validated, NOT auto-elevated) ---
    trust_level = str(raw.get("trust_level", "unverified")).strip().lower()
    if trust_level not in _VALID_TRUST_LEVELS:
        raise ManifestValidationError(
            f"Invalid trust_level '{trust_level}' for tool '{tool_id}': "
            f"must be one of {sorted(_VALID_TRUST_LEVELS)}",
            reason="invalid_trust_level",
        )

    # --- supported_platforms (optional, validated) ---
    platforms_raw = raw.get("supported_platforms", ["windows", "linux", "macos"])
    if not isinstance(platforms_raw, list):
        raise ManifestValidationError(
            f"Invalid supported_platforms for tool '{tool_id}': must be a list",
            reason="invalid_platforms",
        )
    for p in platforms_raw:
        if str(p) not in _VALID_PLATFORMS:
            raise ManifestValidationError(
                f"Invalid platform '{p}' for tool '{tool_id}': "
                f"must be one of {sorted(_VALID_PLATFORMS)}",
                reason="invalid_platform",
            )

    # --- schemas (optional, validated for type) ---
    input_schema = raw.get("input_schema", {})
    _check_schema(input_schema, "input_schema")
    output_schema = raw.get("output_schema", {})
    _check_schema(output_schema, "output_schema")

    # --- dependencies (optional, validated) ---
    deps_raw = raw.get("dependencies", [])
    if not isinstance(deps_raw, list):
        raise ManifestValidationError(
            f"Invalid dependencies for tool '{tool_id}': must be a list",
            reason="invalid_dependencies",
        )

    # --- permissions (optional, validated) ---
    perms_raw = raw.get("permissions", [])
    if not isinstance(perms_raw, list):
        raise ManifestValidationError(
            f"Invalid permissions for tool '{tool_id}': must be a list",
            reason="invalid_permissions",
        )

    # --- model_requirements (optional, validated) ---
    reqs_raw = raw.get("model_requirements", [])
    if not isinstance(reqs_raw, list):
        raise ManifestValidationError(
            f"Invalid model_requirements for tool '{tool_id}': must be a list",
            reason="invalid_model_requirements",
        )

    logger.debug("Manifest validated for tool '%s' v%s", tool_id, version)
    return ToolManifest(
        format_version=format_version,
        tool_id=tool_id,
        name=name,
        entry_point=entry_point,
        description=str(raw.get("description", "")),
        version=version,
        category=category,
        source=source,
        risk_level=risk_level,
        trust_level=trust_level,
        offline=bool(raw.get("offline", True)),
        requires_network=bool(raw.get("requires_network", False)),
        supported_platforms=[str(p) for p in platforms_raw],
        permissions=[str(p) for p in perms_raw],
        model_requirements=[str(r) for r in reqs_raw],
        dependencies=[str(d) for d in deps_raw],
        input_schema=dict(input_schema),
        output_schema=dict(output_schema),
        author=str(raw.get("author", "")),
        homepage=str(raw.get("homepage", "")),
        license=str(raw.get("license", "")),
        icon=str(raw.get("icon", "")),
        raw=dict(raw),
    )
