"""Plugin data models — metadata, lifecycle state, and security profile.

These are pure data classes with **no** dependency on the application
bootstrap, so they can be imported from `plugins.*` modules and from tests
without pulling in Qt or the `core.assistant` coordinator (keeps the dependency
direction clean: plugins -> core/tools only).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from core.logger import get_logger

logger = get_logger("plugins")

PLUGIN_API_VERSION = "1.0"
_SUPPORTED_API_VERSIONS: frozenset[str] = frozenset({PLUGIN_API_VERSION})

_API_VERSION_RE = re.compile(r"^\d+\.\d+$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+].*)?$")


class PluginState(Enum):
    """Lifecycle states a plugin transitions through."""

    DISCOVERED = "discovered"
    LOADING = "loading"
    LOADED = "loaded"
    ENABLED = "enabled"
    DISABLED = "disabled"
    FAILED = "failed"
    UNLOADED = "unloaded"


@dataclass
class PluginSecurityProfile:
    """Declares which capability categories a plugin requests.

    This is documentation/hint metadata **only** — the
    :class:`PermissionManager` / :class:`SecurityLayer` retains final
    authority over whether a tool may actually execute.  Plugin tools still
    carry their own ``category``/``risk_level`` and pass through the same
    registry callback as built-in tools.
    """

    permissions: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> PluginSecurityProfile:
        if not isinstance(data, dict):
            return cls()
        perms = data.get("permissions", [])
        cats = data.get("categories", [])
        if not isinstance(perms, list):
            perms = []
        if not isinstance(cats, list):
            cats = []
        return cls(
            permissions=[str(p) for p in perms],
            categories=[str(c) for c in cats],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "permissions": list(self.permissions),
            "categories": list(self.categories),
        }


@dataclass
class PluginMetadata:
    """Static description of a plugin, parsed from its ``plugin.json``."""

    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    api_version: str = PLUGIN_API_VERSION
    entry_point: str = ""
    permissions: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    homepage: str = ""
    repo: str = ""
    license: str = ""
    icon: str = ""
    dependencies: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def security_profile(self) -> PluginSecurityProfile:
        return PluginSecurityProfile(
            permissions=list(self.permissions),
            categories=list(self.categories),
        )

    @classmethod
    def from_dict(cls, data: Any) -> PluginMetadata:
        if not isinstance(data, dict):
            raise TypeError("plugin manifest must be a JSON object")
        raw = dict(data)
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            version=str(data.get("version", "0.0.0")),
            description=str(data.get("description", "")),
            author=str(data.get("author", "")),
            api_version=str(data.get("api_version", PLUGIN_API_VERSION)),
            entry_point=str(data.get("entry_point", "")),
            permissions=list(data.get("permissions") or []),
            categories=list(data.get("categories") or []),
            homepage=str(data.get("homepage", "")),
            repo=str(data.get("repo", "")),
            license=str(data.get("license", "")),
            icon=str(data.get("icon", "")),
            dependencies=list(data.get("dependencies") or []),
            raw=raw,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "api_version": self.api_version,
            "entry_point": self.entry_point,
            "permissions": list(self.permissions),
            "categories": list(self.categories),
            "homepage": self.homepage,
            "repo": self.repo,
            "license": self.license,
            "icon": self.icon,
            "dependencies": list(self.dependencies),
        }


@dataclass
class PluginLoadResult:
    """Outcome of loading a single plugin during discovery."""

    plugin_id: str
    state: PluginState
    error: str | None = None
    metadata: PluginMetadata | None = None

    @property
    def success(self) -> bool:
        return self.state == PluginState.LOADED


def is_valid_api_version(version: str) -> bool:
    """True when *version* is a known-compatible plugin API version."""
    if not isinstance(version, str):
        return False
    if version in _SUPPORTED_API_VERSIONS:
        return True
    # Accept a matching major version, e.g. "1.0" is compatible with "1.2".
    if _API_VERSION_RE.match(version) and "." in PLUGIN_API_VERSION:
        return version.split(".", 1)[0] == PLUGIN_API_VERSION.split(".", 1)[0]
    return False


def is_valid_semver(version: str) -> bool:
    """Loose semver check used during manifest validation."""
    return bool(_SEMVER_RE.match(version))


def is_valid_plugin_id(plugin_id: str) -> bool:
    """Plugin IDs are lowercase identifiers used in file paths and commands."""
    if not isinstance(plugin_id, str):
        return False
    return bool(re.match(r"^[a-z][a-z0-9._-]*$", plugin_id))


def parse_entry_point(entry_point: str) -> tuple[str, str] | None:
    """Split ``module:attr`` into ``(module, attr)`` or return ``None``."""
    if not isinstance(entry_point, str) or ":" not in entry_point:
        return None
    module, _, attr = entry_point.partition(":")
    module = module.strip()
    attr = attr.strip()
    if not module or not attr:
        return None
    return module, attr
