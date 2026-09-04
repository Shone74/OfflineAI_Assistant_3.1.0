"""Plugin discovery — reads & validates ``plugin.json`` manifests.

Discovery is **side-effect free**: it parses JSON manifests and validates them
but never imports or executes plugin code.  Invalid manifests are skipped with
a warning and a published ``PLUGIN_LOAD_FAILED`` event so a single broken
plugin cannot affect startup.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from plugins.models import (
    PLUGIN_API_VERSION,
    PluginMetadata,
    is_valid_api_version,
    is_valid_plugin_id,
    is_valid_semver,
    parse_entry_point,
)

logger = get_logger("plugins.discovery")

_MANIFEST_NAME = "plugin.json"


def _publish(event_type: str, data: dict[str, Any]) -> None:
    EventBus.get_instance().publish(event_type, data=data)


def validate_manifest(raw: Any) -> PluginMetadata | None:
    """Validate a parsed manifest dict.

    Returns a :class:`PluginMetadata` when valid, or ``None`` (with a
    descriptive reason logged + event published) when invalid.  Never raises.
    """
    if not isinstance(raw, dict):
        logger.warning("Plugin manifest is not a JSON object; skipping")
        _publish("PLUGIN_LOAD_FAILED", {"reason": "manifest_not_object"})
        return None

    plugin_id = str(raw.get("id", "")).strip()
    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    entry_point = str(raw.get("entry_point", "")).strip()
    api_version = str(raw.get("api_version", "")).strip()

    if not plugin_id:
        logger.warning("Plugin manifest missing 'id'; skipping")
        _publish("PLUGIN_LOAD_FAILED", {"reason": "missing_id"})
        return None
    if not is_valid_plugin_id(plugin_id):
        logger.warning("Invalid plugin id '%s' (must be lowercase identifier); skipping", plugin_id)
        _publish("PLUGIN_LOAD_FAILED", {"plugin_id": plugin_id, "reason": "invalid_id"})
        return None
    if not name:
        logger.warning("Plugin '%s' missing 'name'; skipping", plugin_id)
        _publish("PLUGIN_LOAD_FAILED", {"plugin_id": plugin_id, "reason": "missing_name"})
        return None
    if not version or not is_valid_semver(version):
        logger.warning("Plugin '%s' has invalid version '%s'; skipping", plugin_id, version)
        _publish("PLUGIN_LOAD_FAILED", {"plugin_id": plugin_id, "reason": "invalid_version"})
        return None
    if not entry_point or parse_entry_point(entry_point) is None:
        logger.warning(
            "Plugin '%s' has invalid entry_point '%s'; skipping", plugin_id, entry_point
        )
        _publish("PLUGIN_LOAD_FAILED", {"plugin_id": plugin_id, "reason": "invalid_entry_point"})
        return None
    if api_version and not is_valid_api_version(api_version):
        logger.warning(
            "Plugin '%s' api_version '%s' not compatible with %s; skipping",
            plugin_id,
            api_version,
            PLUGIN_API_VERSION,
        )
        _publish(
            "PLUGIN_LOAD_FAILED",
            {"plugin_id": plugin_id, "reason": "incompatible_api_version"},
        )
        return None

    api_version = api_version or PLUGIN_API_VERSION
    logger.debug("Discovery accepted manifest for plugin '%s' (%s)", plugin_id, name)
    return PluginMetadata.from_dict(raw)


def discover_plugins(directory: str | Path) -> list[PluginMetadata]:
    """Scan *directory* for ``<plugin_id>/plugin.json`` manifests.

    Walks immediate sub-directories only (one manifest per folder).  Each
    folder is a candidate plugin; the folder name is informational only — the
    plugin ``id`` comes from the manifest.  Returns valid metadata in
    discovery order.  Invalid or duplicate manifests are skipped safely.
    """
    base = Path(directory)
    discovered: list[PluginMetadata] = []
    seen: set[str] = set()

    if not base.exists() or not base.is_dir():
        logger.info("Plugin directory '%s' not found — 0 plugins discovered", base)
        return discovered

    for candidate in sorted(base.iterdir()):
        if not candidate.is_dir():
            continue
        manifest_path = candidate / _MANIFEST_NAME
        if not manifest_path.exists():
            logger.debug("No plugin.json in '%s' — skipping", candidate.name)
            continue

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read manifest %s: %s; skipping", manifest_path, exc)
            _publish(
                "PLUGIN_LOAD_FAILED",
                {"path": str(manifest_path), "reason": "unreadable_manifest"},
            )
            continue

        metadata = validate_manifest(raw)
        if metadata is None:
            continue
        if metadata.id in seen:
            logger.warning("Duplicate plugin id '%s' — skipping later definition", metadata.id)
            _publish(
                "PLUGIN_LOAD_FAILED",
                {"plugin_id": metadata.id, "reason": "duplicate_id"},
            )
            continue

        seen.add(metadata.id)
        discovered.append(metadata)
        _publish(
            "PLUGIN_DISCOVERED",
            {"plugin_id": metadata.id, "name": metadata.name, "version": metadata.version},
        )
        logger.info("Discovered plugin '%s' v%s", metadata.id, metadata.version)

    logger.info("Plugin discovery complete — %d valid manifest(s)", len(discovered))
    return discovered
