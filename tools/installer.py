"""External tool installer — explicit, opt-in installation lifecycle.

Installation follows a strict, explicitly-requested lifecycle:

    DISCOVERED → VALIDATED → INSTALL_REQUESTED → INSTALLING → INSTALLED → ENABLED

Key security guarantees (Phase 2D):
  * Installation is **never** automatic — ``install()`` must be called
    explicitly, returning :class:`InstallResult`.
  * ``INSTALL_REQUESTED`` is published as an event so the Agent Manager /
    ToolsPage can show a confirmation prompt before any real work happens.
  * Installation does **not** automatically enable a tool.  After installation
    the tool is ``INSTALLED`` (registered in the catalog and ToolRegistry)
    but ``DISABLED`` until the user explicitly calls :meth:`enable`.
  * Installation does **not** automatically grant permissions.  The
    manifest's declared permissions are stored as metadata only; the
    ``PermissionManager`` / ``SecurityLayer`` remains authoritative.
  * Installation resolves the ``entry_point`` via ``importlib`` only at install
    time — discovery never imports tool code.
  * No shell execution, no remote downloads, no arbitrary subprocess calls.
    The installer uses ``importlib.import_module`` + attribute lookup, the
    same mechanism as the plugin loader.

Installed tools enter the *same* ``ToolRegistry`` as built-in tools and
therefore pass through the existing ``SecurityLayer``.
"""

from __future__ import annotations

import dataclasses
import importlib
from dataclasses import dataclass

from core.event_bus import EventBus
from core.logger import get_logger
from tools.base import Tool, ToolRegistry
from tools.catalog import ToolCatalog
from tools.manifest import ToolManifest, ToolState

logger = get_logger("tools.installer")


@dataclass
class InstallResult:
    """Outcome of an explicit installation request."""

    tool_id: str
    state_before: ToolState
    state_after: ToolState
    success: bool
    error: str | None = None
    tool_instance: Tool | None = None
    reason: str | None = None


@dataclass
class _InstallEntry:
    """Internal tracking for an installing/validating tool."""

    manifest: ToolManifest
    state: ToolState = ToolState.VALIDATED
    tool_instance: Tool | None = None
    error: str | None = None
    install_error: str | None = None


class ToolInstaller:
    """Manages the explicit installation lifecycle of external tools.

    The installer is the only component that transitions a tool from
    ``VALIDATED`` → ``INSTALL_REQUESTED`` → ``INSTALLING`` → ``INSTALLED``
    (→ ``ENABLED``).  Each transition is a method call that must be invoked
    explicitly by the caller (e.g. the ToolsPage or AgentManager).

    Parameters
    ----------
    registry : ToolRegistry
        The shared ToolRegistry.  Installed tools are registered here so they
        pass through the existing SecurityLayer / PermissionManager.
    catalog : ToolCatalog
        Persistent catalog tracking installation/enabled state.
    event_bus : EventBus, optional
        Event bus for publishing lifecycle events.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        catalog: ToolCatalog,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._event_bus = event_bus or EventBus.get_instance()
        self._entries: dict[str, _InstallEntry] = {}

    # ------------------------------------------------------------------ #
    # Public properties
    # ------------------------------------------------------------------ #
    @property
    def registry(self) -> ToolRegistry:
        return self._registry

    @property
    def catalog(self) -> ToolCatalog:
        return self._catalog

    def get_install_entry(self, tool_id: str) -> _InstallEntry | None:
        return self._entries.get(tool_id)

    def list_installable(self) -> list[ToolManifest]:
        """Return manifests that have been discovered and validated."""
        return [e.manifest for e in self._entries.values() if e.state == ToolState.VALIDATED]

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def register_manifest(self, manifest: ToolManifest) -> None:
        """Accept a validated manifest from the discovery layer.

        This is the bridge between discovery and installation: the discovery
        service validates the manifest; the installer accepts it for potential
        installation.  Registration does **not** import or execute any code.
        """
        self._entries[manifest.tool_id] = _InstallEntry(
            manifest=manifest,
            state=ToolState.VALIDATED,
        )
        self._catalog.upsert_discovered(manifest)

    def install(self, tool_id: str) -> InstallResult:
        """Explicitly request installation of a discovered tool.

        Transitions the tool through:
        VALIDATED → INSTALL_REQUESTED → INSTALLING → INSTALLED

        The tool's entry_point is resolved via importlib at INSTALLING time.
        After successful installation the tool is registered in the ToolRegistry
        but **disabled** — the caller must call :meth:`enable` to activate it.

        Never auto-enables, never auto-grants permissions, never bypasses
        SecurityLayer.
        """
        entry = self._entries.get(tool_id)
        if entry is None:
            return InstallResult(
                tool_id=tool_id,
                state_before=ToolState.DISCOVERED,
                state_after=ToolState.FAILED,
                success=False,
                error="Tool not found in install queue",
                reason="not_found",
            )

        if entry.state == ToolState.INSTALLED:
            return InstallResult(
                tool_id=tool_id,
                state_before=entry.state,
                state_after=entry.state,
                success=True,
                error=None,
            )

        if entry.state in (ToolState.INSTALLING,):
            return InstallResult(
                tool_id=tool_id,
                state_before=entry.state,
                state_after=entry.state,
                success=False,
                error="Installation already in progress",
                reason="in_progress",
            )

        prev_state = entry.state
        entry.state = ToolState.INSTALL_REQUESTED
        self._event_bus.publish(
            "TOOL_INSTALL_REQUESTED",
            {"tool_id": tool_id, "entry_point": entry.manifest.entry_point},
        )
        logger.info("Install requested for tool '%s'", tool_id)

        entry.state = ToolState.INSTALLING
        self._event_bus.publish(
            "TOOL_INSTALLING",
            {"tool_id": tool_id, "entry_point": entry.manifest.entry_point},
        )
        logger.info("Installing tool '%s' (entry_point=%s)", tool_id, entry.manifest.entry_point)

        try:
            tool_instance = self._resolve_entry_point(entry.manifest)
        except Exception as exc:
            entry.state = ToolState.FAILED
            entry.install_error = str(exc)
            self._catalog.update_state(tool_id, ToolState.FAILED, error=str(exc))
            self._event_bus.publish(
                "TOOL_INSTALL_FAILED",
                {"tool_id": tool_id, "error": str(exc)},
            )
            logger.exception("Failed to install tool '%s'", tool_id)
            return InstallResult(
                tool_id=tool_id,
                state_before=prev_state,
                state_after=ToolState.FAILED,
                success=False,
                error=str(exc),
                reason="import_error",
            )

        entry.tool_instance = tool_instance
        entry.state = ToolState.INSTALLED

        # Register in the shared ToolRegistry so the tool passes through
        # the existing SecurityLayer.  The tool is registered but DISABLED.
        # Use the tool's own name (not manifest.tool_id) as the registry key.
        registry_name = tool_instance.name
        metadata = entry.manifest.to_metadata()
        metadata = dataclasses.replace(metadata, installed=True, enabled=False)
        self._registry.register(tool_instance, metadata=metadata)
        self._registry.disable(registry_name)

        self._catalog.upsert_installed(
            manifest=entry.manifest,
            enabled=False,
        )
        self._event_bus.publish(
            "TOOL_INSTALLED",
            {"tool_id": tool_id, "name": entry.manifest.name, "registry_name": registry_name},
        )
        logger.info("Tool '%s' installed and registered (disabled pending explicit enable)", tool_id)
        return InstallResult(
            tool_id=tool_id,
            state_before=prev_state,
            state_after=ToolState.INSTALLED,
            success=True,
            tool_instance=tool_instance,
        )

    def enable(self, tool_id: str) -> bool:
        """Explicitly enable an installed tool.

        The tool is already in the ToolRegistry; this flips its enabled bit.
        This is a separate step from installation so that installation never
        silently grants execution capability.
        """
        entry = self._entries.get(tool_id)
        if entry is None or entry.state != ToolState.INSTALLED:
            logger.warning("Cannot enable tool '%s': not installed", tool_id)
            return False

        entry.state = ToolState.ENABLED
        registry_name = entry.tool_instance.name if entry.tool_instance else tool_id
        success = self._registry.enable(registry_name)
        if success:
            self._catalog.update_enabled(tool_id, enabled=True)
            self._event_bus.publish("TOOL_ENABLED", {"tool_id": tool_id})
            logger.info("Tool '%s' enabled", tool_id)
        return success

    def disable(self, tool_id: str) -> bool:
        """Disable an enabled tool (remains installed and registered)."""
        entry = self._entries.get(tool_id)
        registry_name = entry.tool_instance.name if entry and entry.tool_instance else tool_id
        if entry is None:
            # Even if we don't have an in-memory entry, try the registry.
            success = self._registry.disable(tool_id)
            if success:
                self._catalog.update_enabled(tool_id, enabled=False)
                self._event_bus.publish("TOOL_DISABLED", {"tool_id": tool_id})
            return success

        if entry.state == ToolState.ENABLED:
            entry.state = ToolState.DISABLED
        success = self._registry.disable(registry_name)
        if success:
            self._catalog.update_enabled(tool_id, enabled=False)
            self._event_bus.publish("TOOL_DISABLED", {"tool_id": tool_id})
            logger.info("Tool '%s' disabled", tool_id)
        return success

    def uninstall(self, tool_id: str) -> bool:
        """Remove an installed external tool from the registry and catalog.

        This unregisters the tool from ToolRegistry (so it can no longer
        execute) and removes it from the catalog.  The manifest remains in
        the discovery layer and can be re-installed.
        """
        entry = self._entries.get(tool_id)
        if entry is None:
            return False

        registry_name = entry.tool_instance.name if entry.tool_instance else tool_id
        if entry.tool_instance is not None:
            self._registry.unregister(registry_name)

        entry.state = ToolState.DISCOVERED
        entry.tool_instance = None
        self._catalog.remove(tool_id)
        self._event_bus.publish("TOOL_UNINSTALLED", {"tool_id": tool_id})
        logger.info("Tool '%s' uninstalled", tool_id)
        return True

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_entry_point(manifest: ToolManifest) -> Tool:
        """Import the module and instantiate the tool class.

        Uses ``importlib.import_module`` — never ``subprocess``, never
        ``os.system``, never arbitrary shell execution.  This is the same
        safe import mechanism used by the plugin loader.

        Raises ``ImportError`` / ``AttributeError`` / ``TypeError`` on
        failure; the caller catches and records the error.
        """
        if ":" not in manifest.entry_point:
            raise ImportError(f"Invalid entry_point '{manifest.entry_point}': expected 'module:attr'")

        module_name, _, attr_name = manifest.entry_point.partition(":")
        module_name = module_name.strip()
        attr_name = attr_name.strip()

        if not module_name or not attr_name:
            raise ImportError(f"Invalid entry_point '{manifest.entry_point}': empty module or attr")

        module = importlib.import_module(module_name)

        obj = getattr(module, attr_name, None)
        if obj is None:
            raise AttributeError(f"Entry point '{attr_name}' not found in module '{module_name}'")

        instance = obj() if callable(obj) else obj
        if not isinstance(instance, Tool):
            raise TypeError(
                f"Entry point '{manifest.entry_point}' did not produce a Tool "
                f"instance (got {type(instance).__name__})"
            )

        return instance
