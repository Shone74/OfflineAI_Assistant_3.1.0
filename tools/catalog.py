"""Persistent catalog for discovered and installed external tools.

The catalog persists tool state to a JSON file in the application's
configuration directory (``ConfigManager`` / settings.json).  It does **not**
write to the production SQLite database (``assistant.db``).

State values tracked per tool:
  * ``tool_state`` — installation lifecycle: discovered, validated,
    install_requested, installing, installed, enabled, disabled, failed
  * ``enabled`` — boolean, whether the tool is enabled in the registry
  * ``installed`` — boolean, whether the tool has been installed
  * ``catalog_status`` — runtime availability status for UI display:
    discovered, available, unavailable, unsupported_by_model, disabled,
    not_installed, invalid, failed

The catalog separates *installation state* (ToolState enum) from *runtime
status* (ToolStatus enum used by the compatibility evaluator).  This allows
a tool to be installed but disabled, or discovered but not installed,
without ambiguity.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config_manager import ConfigManager
from core.logger import get_logger
from tools.manifest import ToolManifest, ToolState

logger = get_logger("tools.catalog")

_CATALOG_FILENAME = "tool_catalog.json"


class ToolCatalog:
    """Persistent catalog for external tool installation state.

    Uses the ConfigManager's settings.json file as the backing store,
    stored under the ``external_tools`` top-level key.  This avoids
    touching the production ``assistant.db`` entirely.
    """

    def __init__(self, config: ConfigManager | None = None) -> None:
        self._config = config or ConfigManager()
        self._catalog_path = self._config.settings_path.parent / _CATALOG_FILENAME
        self._entries: dict[str, dict[str, Any]] = {}
        self._load()

    @property
    def catalog_path(self) -> Path:
        return self._catalog_path

    def _load(self) -> None:
        """Load the catalog from disk, handling malformed state safely."""
        try:
            if self._catalog_path.exists():
                raw = json.loads(self._catalog_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict) and isinstance(raw.get("tools"), dict):
                    self._entries = dict(raw["tools"])
                    logger.info("Loaded %d external tool(s) from catalog", len(self._entries))
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("Malformed tool catalog at %s: %s — reinitializing empty",
                           self._catalog_path, exc)
            self._entries = {}

    def _save(self) -> None:
        """Persist the catalog to disk."""
        try:
            self._catalog_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"format_version": "1.0", "tools": self._entries}
            self._catalog_path.write_text(
                json.dumps(data, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.error("Failed to save tool catalog to %s: %s", self._catalog_path, exc)

    def upsert_discovered(self, manifest: ToolManifest) -> None:
        """Record a discovered tool (before installation)."""
        entry = self._entries.get(manifest.tool_id, {})
        entry.update({
            "tool_id": manifest.tool_id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "entry_point": manifest.entry_point,
            "tool_state": ToolState.VALIDATED.value,
            "enabled": False,
            "installed": False,
            "trust_level": manifest.trust_level,
            "risk_level": manifest.risk_level,
            "source": manifest.source,
            "category": manifest.category,
            "permissions": list(manifest.permissions),
            "supported_platforms": list(manifest.supported_platforms),
            "model_requirements": list(manifest.model_requirements),
            "offline": manifest.offline,
            "requires_network": manifest.requires_network,
            "author": manifest.author,
            "homepage": manifest.homepage,
            "format_version": manifest.format_version,
        })
        self._entries[manifest.tool_id] = entry
        self._save()

    def upsert_installed(
        self,
        manifest: ToolManifest,
        enabled: bool = False,
    ) -> None:
        """Record that a tool has been installed (but not auto-enabled)."""
        entry = self._entries.get(manifest.tool_id, {})
        entry.update({
            "tool_id": manifest.tool_id,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "entry_point": manifest.entry_point,
            "tool_state": ToolState.INSTALLED.value,
            "enabled": enabled,
            "installed": True,
            "trust_level": manifest.trust_level,
            "risk_level": manifest.risk_level,
            "source": manifest.source,
            "category": manifest.category,
            "permissions": list(manifest.permissions),
            "supported_platforms": list(manifest.supported_platforms),
            "model_requirements": list(manifest.model_requirements),
            "offline": manifest.offline,
            "requires_network": manifest.requires_network,
            "author": manifest.author,
            "homepage": manifest.homepage,
            "format_version": manifest.format_version,
        })
        self._entries[manifest.tool_id] = entry
        self._save()

    def update_state(self, tool_id: str, state: ToolState, error: str | None = None) -> None:
        """Update the installation lifecycle state of a tool."""
        entry = self._entries.get(tool_id)
        if entry is None:
            return
        entry["tool_state"] = state.value
        if error is not None:
            entry["error"] = error
        self._save()

    def update_enabled(self, tool_id: str, enabled: bool) -> None:
        """Update the enabled/disabled state of a tool in the catalog."""
        entry = self._entries.get(tool_id)
        if entry is None:
            return
        entry["enabled"] = enabled
        entry["tool_state"] = ToolState.ENABLED.value if enabled else ToolState.DISABLED.value
        self._save()

    def update_failed(self, tool_id: str, error: str | None = None) -> None:
        """Mark a tool as FAILED in the catalog."""
        entry = self._entries.get(tool_id)
        if entry is None:
            return
        entry["tool_state"] = ToolState.FAILED.value
        if error is not None:
            entry["error"] = error
        self._save()

    def remove(self, tool_id: str) -> bool:
        """Remove a tool from the catalog."""
        if tool_id in self._entries:
            del self._entries[tool_id]
            self._save()
            return True
        return False

    def get(self, tool_id: str) -> dict[str, Any] | None:
        """Return the persisted catalog entry for *tool_id*."""
        return self._entries.get(tool_id)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all catalog entries."""
        return list(self._entries.values())

    def list_by_state(self, *states: ToolState) -> list[dict[str, Any]]:
        """Return catalog entries matching any of the given installation states."""
        state_values = {s.value for s in states}
        return [e for e in self._entries.values() if e.get("tool_state") in state_values]

    def list_installed(self) -> list[dict[str, Any]]:
        """Return entries that have been installed (regardless of enabled)."""
        return [e for e in self._entries.values() if e.get("installed", False)]

    def list_enabled(self) -> list[dict[str, Any]]:
        """Return entries that are both installed and enabled."""
        return [
            e for e in self._entries.values()
            if e.get("installed", False) and e.get("enabled", False)
        ]

    def list_discovered(self) -> list[dict[str, Any]]:
        """Return entries that have been discovered but not installed."""
        return [e for e in self._entries.values() if not e.get("installed", False)]

    def clear(self) -> None:
        """Clear all catalog entries (used in tests)."""
        self._entries = {}
        self._save()
