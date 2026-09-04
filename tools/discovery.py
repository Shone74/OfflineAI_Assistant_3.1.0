"""External tool discovery service.

Discovers and validates external tool manifests from explicitly configured
local sources.  Discovery is **side-effect free**: it parses JSON manifest
files and validates them but never imports or executes tool code.  Discovered
tools are distinguishable from installed tools — discovery never implies
installation.

Discovery sources:
  * A directory configured in ``settings.json`` under ``external_tools.directories``
  * Any additional paths passed explicitly to ``discover()``

Each source directory should contain subdirectories, each with a
``tool.json`` manifest.  The subdirectory name is informational; the
``tool_id`` comes from the manifest.  Duplicate tool IDs are detected and
skipped.  Malformed manifests are reported via the event bus and logger
without crashing the scan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logger import get_logger
from tools.manifest import (
    ManifestValidationError,
    ToolManifest,
    ToolState,
    validate_manifest,
)

logger = get_logger("tools.discovery")

_MANIFEST_NAME = "tool.json"


@dataclass
class DiscoveryResult:
    """Outcome of discovering a single manifest during a scan."""

    tool_id: str
    state: ToolState
    manifest: ToolManifest | None = None
    error: str | None = None
    path: str | None = None
    reason: str | None = None

    @property
    def success(self) -> bool:
        return self.manifest is not None


@dataclass
class DiscoveryReport:
    """Aggregate result of a full discovery scan."""

    discovered: list[DiscoveryResult] = field(default_factory=list)
    total: int = 0

    def valid_manifests(self) -> list[ToolManifest]:
        return [r.manifest for r in self.discovered if r.manifest is not None]

    def invalid_results(self) -> list[DiscoveryResult]:
        return [r for r in self.discovered if r.manifest is None]


class ToolDiscoveryService:
    """Discovers external tool manifests from local, explicitly-configured sources.

    The service is intentionally side-effect free during discovery:
    manifests are parsed and validated only.  No tool code is imported or
    executed.  Installation is an explicit separate step handled by
    :class:`~tools.installer.ToolInstaller`.

    Discovery sources come from two places:
      1. ``ConfigManager`` settings under ``external_tools.directories``
      2. Paths explicitly passed to :meth:`discover`
    """

    def __init__(
        self,
        config: ConfigManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._config = config or ConfigManager()
        self._event_bus = event_bus or EventBus.get_instance()

    @property
    def config(self) -> ConfigManager:
        return self._config

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    def get_discovery_directories(self) -> list[str]:
        """Return the list of explicitly-configured discovery directories."""
        dirs = self._config.get("external_tools.directories", [])
        if isinstance(dirs, list):
            return [str(d) for d in dirs if str(d).strip()]
        return []

    def discover(self, paths: list[str] | str | None = None) -> DiscoveryReport:
        """Scan all configured + *paths* directories for tool manifests.

        Returns a :class:`DiscoveryReport` listing every discovered manifest
        (valid or invalid).  Invalid manifests are included as
        :class:`DiscoveryResult` with ``state=FAILED`` and ``reason`` set.
        """
        all_paths: list[str] = []
        if paths is not None:
            if isinstance(paths, str):
                all_paths.append(paths)
            else:
                all_paths.extend(str(p) for p in paths)
        all_paths.extend(self.get_discovery_directories())

        report = DiscoveryReport()
        seen: set[str] = set()

        for source_dir in all_paths:
            self._scan_directory(source_dir, report, seen)

        report.total = len(report.discovered)
        logger.info(
            "Discovery complete — %d valid, %d invalid out of %d total",
            len(report.valid_manifests()),
            len(report.invalid_results()),
            report.total,
        )
        return report

    def _scan_directory(
        self,
        directory: str,
        report: DiscoveryReport,
        seen: set[str],
    ) -> None:
        """Scan *directory* for subdirectories containing ``tool.json``."""
        base = Path(directory)

        if not base.exists() or not base.is_dir():
            logger.info("Discovery directory '%s' not found — skipping", base)
            return

        for candidate in sorted(base.iterdir()):
            if not candidate.is_dir():
                continue
            manifest_path = candidate / _MANIFEST_NAME
            if not manifest_path.exists():
                continue

            result = self._parse_and_validate(manifest_path, candidate.name)
            if result is None:
                continue

            if result.tool_id and result.tool_id in seen:
                logger.warning(
                    "Duplicate tool_id '%s' — skipping later definition",
                    result.tool_id,
                )
                self._event_bus.publish(
                    "TOOL_DISCOVERY_FAILED",
                    {"path": str(manifest_path), "tool_id": result.tool_id, "reason": "duplicate_id"},
                )
                continue

            if result.tool_id:
                seen.add(result.tool_id)

            self._event_bus.publish(
                "TOOL_DISCOVERED",
                {
                    "tool_id": result.tool_id,
                    "name": result.manifest.name if result.manifest else "",
                    "version": result.manifest.version if result.manifest else "",
                    "path": str(manifest_path),
                    "state": result.state.value,
                },
            )
            report.discovered.append(result)

    def _parse_and_validate(
        self,
        manifest_path: Path,
        folder_name: str,
    ) -> DiscoveryResult | None:
        """Read and validate a single manifest file.

        Returns a :class:`DiscoveryResult` (success or failure) or ``None``
        if the manifest should be silently skipped (e.g. no readable JSON).
        """
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("Cannot read manifest %s: %s; skipping", manifest_path, exc)
            self._event_bus.publish(
                "TOOL_DISCOVERY_FAILED",
                {"path": str(manifest_path), "reason": "unreadable"},
            )
            return DiscoveryResult(
                tool_id="",
                state=ToolState.FAILED,
                error=str(exc),
                path=str(manifest_path),
                reason="unreadable",
            )
        except json.JSONDecodeError as exc:
            logger.warning("Malformed JSON in manifest %s: %s; skipping", manifest_path, exc)
            self._event_bus.publish(
                "TOOL_DISCOVERY_FAILED",
                {"path": str(manifest_path), "reason": "malformed_json"},
            )
            return DiscoveryResult(
                tool_id="",
                state=ToolState.FAILED,
                error=str(exc),
                path=str(manifest_path),
                reason="malformed_json",
            )

        try:
            manifest = validate_manifest(raw)
        except ManifestValidationError as exc:
            logger.warning("Invalid manifest %s: %s (reason=%s)", manifest_path, exc, exc.reason)
            self._event_bus.publish(
                "TOOL_DISCOVERY_FAILED",
                {
                    "path": str(manifest_path),
                    "reason": exc.reason,
                    "error": str(exc),
                    "format_version": str(raw.get("format_version", "")),
                },
            )
            tool_id = str(raw.get("tool_id", "")) if isinstance(raw, dict) else ""
            return DiscoveryResult(
                tool_id=tool_id,
                state=ToolState.FAILED,
                error=str(exc),
                path=str(manifest_path),
                reason=exc.reason,
            )

        logger.info(
            "Discovered tool manifest '%s' v%s (entry_point=%s)",
            manifest.tool_id,
            manifest.version,
            manifest.entry_point,
        )

        return DiscoveryResult(
            tool_id=manifest.tool_id,
            state=ToolState.VALIDATED,
            manifest=manifest,
            path=str(manifest_path),
        )

    def refresh(self) -> DiscoveryReport:
        """Convenience alias for :meth:`discover` using configured directories only."""
        return self.discover()
