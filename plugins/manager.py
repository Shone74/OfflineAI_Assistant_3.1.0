"""Plugin manager — lifecycle orchestration for the plugin system.

The manager is the single authority over plugin state.  It owns the
``DISCOVERED -> LOADED -> ENABLED/DISABLED/FAILED -> UNLOADED`` state machine,
publishes ``PLUGIN_*`` lifecycle events, registers plugin tools through the
shared :class:`ToolRegistry` (so they inherit the active :class:`SecurityLayer`)
and routes plugin-declared slash commands.

Dependency note: imports only ``core`` (logger, event_bus), ``tools.base``
interfaces, and sibling ``plugins.*`` modules.  It deliberately does **not**
import ``core.assistant`` — the assistant holds a reference to the manager
instead, keeping the dependency direction acyclic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from plugins.base import Plugin
from plugins.discovery import discover_plugins
from plugins.loader import initialize_plugin, load_plugin
from plugins.models import PluginLoadResult, PluginMetadata, PluginState
from plugins.registry import PluginCommand, PluginCommandRegistry
from tools.base import Tool, ToolRegistry

logger = get_logger("plugins.manager")


@dataclass
class _PluginEntry:
    metadata: PluginMetadata
    instance: Plugin | None = None
    state: PluginState = PluginState.DISCOVERED
    tools: list[Tool] = field(default_factory=list)
    event_subs: list[tuple[str, str]] = field(default_factory=list)


class PluginManager:
    """Coordinates discovery, loading, enabling and disabling of plugins."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        event_bus: Any = None,
        command_registry: PluginCommandRegistry | None = None,
        config: Any = None,
    ) -> None:
        self._registry = tool_registry
        self._event_bus = event_bus or EventBus.get_instance()
        self._commands = command_registry or PluginCommandRegistry()
        self._entries: dict[str, _PluginEntry] = {}
        self._config = config

    # ------------------------------------------------------------------ #
    # Public surface
    # ------------------------------------------------------------------ #
    @property
    def tool_registry(self) -> ToolRegistry:
        return self._registry

    @property
    def event_bus(self) -> Any:
        return self._event_bus

    @property
    def command_registry(self) -> PluginCommandRegistry:
        return self._commands

    @property
    def plugins(self) -> list[PluginMetadata]:
        return [entry.metadata for entry in self._entries.values()]

    def get(self, plugin_id: str) -> Plugin | None:
        entry = self._entries.get(plugin_id)
        return entry.instance if entry else None

    def get_state(self, plugin_id: str) -> PluginState | None:
        entry = self._entries.get(plugin_id)
        return entry.state if entry else None

    def get_metadata(self, plugin_id: str) -> PluginMetadata | None:
        entry = self._entries.get(plugin_id)
        return entry.metadata if entry else None

    def list_plugin_ids(self) -> list[str]:
        return list(self._entries.keys())

    def save_plugin_states(self) -> None:
        if self._config is None:
            return
        enabled = [pid for pid, entry in self._entries.items() if entry.state == PluginState.ENABLED]
        self._config.set("plugins.enabled", enabled)

    def load_plugin_states(self) -> None:
        if self._config is None:
            return
        enabled = self._config.get("plugins.enabled", [])
        enabled_set = set(enabled)
        for pid, entry in list(self._entries.items()):
            if entry.state == PluginState.ENABLED and pid not in enabled_set:
                self.disable(pid)
            elif entry.state == PluginState.LOADED and pid in enabled_set:
                self.enable(pid)

    def validate_dependencies(self, plugin_id: str) -> tuple[bool, list[str]]:
        entry = self._entries.get(plugin_id)
        if entry is None or entry.metadata is None:
            return False, []
        missing = []
        for dep in entry.metadata.dependencies:
            if dep not in self._entries or self._entries[dep].state not in (
                PluginState.LOADED,
                PluginState.ENABLED,
                PluginState.DISABLED,
            ):
                missing.append(dep)
        return len(missing) == 0, missing

    # ------------------------------------------------------------------ #
    # Bulk discovery + loading (used at bootstrap)
    # ------------------------------------------------------------------ #
    def discover_and_load(self, directory: str | Path) -> int:
        """Discover manifests in *directory*, load, and enable each plugin.

        Returns the number of plugins successfully enabled.  A broken plugin
        is recorded as ``FAILED`` and never blocks the rest.
        """
        discovered = discover_plugins(directory)
        enabled = 0
        for metadata in discovered:
            result = self.load(metadata)
            if result.success and self.enable(metadata.id):
                enabled += 1
        if discovered:
            logger.info(
                "Plugin manager ready — %d/%d plugin(s) enabled", enabled, len(discovered)
            )
        else:
            logger.info("Plugin manager ready — 0 plugin(s) discovered")
        return enabled

    # ------------------------------------------------------------------ #
    # Single-plugin lifecycle
    # ------------------------------------------------------------------ #
    def load(self, metadata: PluginMetadata) -> PluginLoadResult:
        plugin_id = metadata.id
        if plugin_id in self._entries:
            existing = self._entries[plugin_id]
            if existing.state == PluginState.FAILED:
                pass
            else:
                logger.info(
                    "Plugin '%s' already loaded (state=%s)", plugin_id, existing.state.value
                )
                return PluginLoadResult(plugin_id=plugin_id, state=PluginState.LOADED, metadata=existing.metadata)

        if metadata.dependencies:
            self._entries[plugin_id] = _PluginEntry(metadata=metadata, state=PluginState.LOADING)
            ok, missing = self.validate_dependencies(plugin_id)
            if not ok:
                logger.warning("Plugin '%s' missing dependencies: %s", plugin_id, missing)
                self._entries[plugin_id].state = PluginState.FAILED
                self._event_bus.publish(
                    "PLUGIN_LOAD_FAILED",
                    {"plugin_id": plugin_id, "reason": "missing_dependencies", "missing": missing},
                )
                return PluginLoadResult(plugin_id=plugin_id, state=PluginState.FAILED, metadata=metadata, error=f"Missing dependencies: {', '.join(missing)}")

        entry = _PluginEntry(metadata=metadata, state=PluginState.LOADING)
        self._entries[plugin_id] = entry
        self._event_bus.publish(
            "PLUGIN_LOAD_START", {"plugin_id": plugin_id, "name": metadata.name}
        )

        instance = load_plugin(
            metadata, registry=self._registry, event_bus=self._event_bus
        )
        if instance is None:
            entry.state = PluginState.FAILED
            self._event_bus.publish(
                "PLUGIN_LOAD_FAILED", {"plugin_id": plugin_id, "reason": "load_error"}
            )
            return PluginLoadResult(plugin_id=plugin_id, state=PluginState.FAILED)

        entry.instance = instance
        entry.state = PluginState.LOADED
        self._event_bus.publish(
            "PLUGIN_LOADED", {"plugin_id": plugin_id, "name": metadata.name}
        )
        return PluginLoadResult(plugin_id=plugin_id, state=PluginState.LOADED, metadata=metadata)

    def load_instance(self, metadata: PluginMetadata, instance: Plugin) -> bool:
        """Register a pre-built plugin instance, bypassing module import.

        Useful for programmatic/pluginised plugins and tests.  The instance is
        initialized (mirrors :func:`plugins.loader.load_plugin`) then left in the
        ``LOADED`` state — call :meth:`enable` to register its tools/commands.
        """
        plugin_id = metadata.id
        if plugin_id in self._entries and self._entries[plugin_id].state != PluginState.FAILED:
            logger.info("Plugin '%s' already loaded", plugin_id)
            return False

        entry = _PluginEntry(metadata=metadata, instance=instance, state=PluginState.LOADING)
        self._entries[plugin_id] = entry
        self._event_bus.publish("PLUGIN_LOAD_START", {"plugin_id": plugin_id, "name": metadata.name})

        try:
            initialize_plugin(metadata, instance, self._registry, self._event_bus)
        except Exception as exc:
            logger.exception("Plugin '%s' initialize failed", plugin_id)
            self._event_bus.publish(
                "PLUGIN_LOAD_FAILED",
                {"plugin_id": plugin_id, "reason": "init_error", "error": str(exc)},
            )
            entry.state = PluginState.FAILED
            return False

        entry.state = PluginState.LOADED
        self._event_bus.publish("PLUGIN_LOADED", {"plugin_id": plugin_id, "name": metadata.name})
        return True

    def enable(self, plugin_id: str) -> bool:
        entry = self._entries.get(plugin_id)
        if entry is None or entry.instance is None:
            logger.warning("Cannot enable unknown plugin '%s'", plugin_id)
            return False
        if entry.state == PluginState.ENABLED:
            logger.info("Plugin '%s' already enabled", plugin_id)
            return True
        if entry.state not in (PluginState.LOADED, PluginState.DISABLED):
            logger.warning(
                "Plugin '%s' cannot be enabled from state %s", plugin_id, entry.state.value
            )
            return False

        try:
            self._register_plugin_tools(entry)
            self._register_plugin_commands(entry)
            self._subscribe_events(entry)
            entry.instance.enable()
        except Exception as exc:
            logger.exception("Plugin '%s' enable failed", plugin_id)
            self._rollback_entry(entry)
            self._event_bus.publish(
                "PLUGIN_ERROR", {"plugin_id": plugin_id, "reason": "enable_failed", "error": str(exc)}
            )
            entry.state = PluginState.FAILED
            return False

        entry.state = PluginState.ENABLED
        self._event_bus.publish(
            "PLUGIN_ENABLED", {"plugin_id": plugin_id, "name": entry.metadata.name}
        )
        logger.info("Plugin '%s' enabled", plugin_id)
        return True

    def disable(self, plugin_id: str) -> bool:
        entry = self._entries.get(plugin_id)
        if entry is None:
            logger.warning("Cannot disable unknown plugin '%s'", plugin_id)
            return False
        if entry.state != PluginState.ENABLED:
            logger.info("Plugin '%s' not enabled (state=%s)", plugin_id, entry.state.value)
            return False

        try:
            self._unregister_plugin_tools(entry)
            self._commands.unregister_plugin(plugin_id)
            self._unsubscribe_events(entry)
        except Exception as exc:
            logger.exception("Plugin '%s' disable teardown failed", plugin_id)
            self._event_bus.publish(
                "PLUGIN_ERROR",
                {"plugin_id": plugin_id, "reason": "disable_teardown_failed", "error": str(exc)},
            )
        if entry.instance is not None:
            try:
                entry.instance.disable()
            except Exception as exc:
                logger.exception("Plugin '%s' disable hook failed", plugin_id)
                self._event_bus.publish(
                    "PLUGIN_ERROR",
                    {"plugin_id": plugin_id, "reason": "disable_hook_failed", "error": str(exc)},
                )

        entry.state = PluginState.DISABLED
        self._event_bus.publish(
            "PLUGIN_DISABLED", {"plugin_id": plugin_id, "name": entry.metadata.name}
        )
        logger.info("Plugin '%s' disabled", plugin_id)
        return True

    def unload(self, plugin_id: str) -> bool:
        entry = self._entries.get(plugin_id)
        if entry is None:
            logger.warning("Cannot unload unknown plugin '%s'", plugin_id)
            return False

        if entry.state == PluginState.ENABLED:
            self.disable(plugin_id)

        try:
            if entry.instance is not None:
                entry.instance.unload()
        except Exception:
            logger.exception("Plugin '%s' unload failed", plugin_id)

        entry.state = PluginState.UNLOADED
        entry.instance = None
        entry.tools.clear()
        self._commands.unregister_plugin(plugin_id)
        self._entries.pop(plugin_id, None)
        self._event_bus.publish("PLUGIN_UNLOADED", {"plugin_id": plugin_id})
        logger.info("Plugin '%s' unloaded", plugin_id)
        return True

    def reload(self, plugin_id: str) -> bool:
        entry = self._entries.get(plugin_id)
        if entry is None or entry.metadata is None:
            return False
        metadata = entry.metadata
        self.unload(plugin_id)
        result = self.load(metadata)
        return result.success and self.enable(plugin_id)

    # ------------------------------------------------------------------ #
    # Internal: tool/command/event wiring
    # ------------------------------------------------------------------ #
    def _rollback_entry(self, entry: _PluginEntry) -> None:
        """Best-effort removal of resources leaked by a partially-enabled entry.

        Used when ``enable()`` fails after some (but not all) plugin tools,
        commands, or event subscriptions were already registered, so a FAILED
        plugin never leaves executable tools behind in the shared registry.
        """
        self._unregister_plugin_tools(entry)
        self._commands.unregister_plugin(entry.metadata.id)
        self._unsubscribe_events(entry)

    def _register_plugin_tools(self, entry: _PluginEntry) -> None:
        instance = entry.instance
        if instance is None:
            return
        tools = instance.register_tools(self._registry) or []
        for tool in tools:
            if not isinstance(tool, Tool):
                raise TypeError(f"register_tools returned non-Tool: {type(tool).__name__}")
            self._registry.register(tool)
            entry.tools.append(tool)

    def _unregister_plugin_tools(self, entry: _PluginEntry) -> None:
        for tool in entry.tools:
            name = getattr(tool, "name", None)
            if name:
                self._registry.unregister(name)
        entry.tools.clear()

    def _register_plugin_commands(self, entry: _PluginEntry) -> None:
        instance = entry.instance
        if instance is None:
            return
        for cmd in instance.register_commands() or []:
            if not isinstance(cmd, PluginCommand):
                raise TypeError(f"register_commands returned non-PluginCommand: {type(cmd).__name__}")
            cmd.plugin_id = entry.metadata.id
            self._commands.register(cmd)

    def _subscribe_events(self, entry: _PluginEntry) -> None:
        instance = entry.instance
        if instance is None:
            return
        for evt in getattr(instance, "events", []) or []:
            sub_id = self._event_bus.subscribe(evt, instance.on_event)
            entry.event_subs.append((evt, sub_id))

    def _unsubscribe_events(self, entry: _PluginEntry) -> None:
        for evt, sub_id in entry.event_subs:
            self._event_bus.unsubscribe(evt, sub_id)
        entry.event_subs.clear()

    # ------------------------------------------------------------------ #
    # Built-in /plugin command routing (used by Assistant._handle_slash_command)
    # ------------------------------------------------------------------ #
    def list_summary(self) -> str:
        if not self._entries:
            return "Nema plugina"
        lines = []
        for pid in sorted(self._entries):
            entry = self._entries[pid]
            lines.append(f"  {pid} — {entry.state.value} ({entry.metadata.name})")
        return "Plugini:\n" + "\n".join(lines)

    def handle_plugin_command(self, plugin_id: str, action: str, args: str) -> str:
        """Route a ``/plugin <id> <action> [args]`` invocation.

        Returns the response string, or ``None`` when *action* does not match
        any known command (so the caller can fall through to normal chat).
        """
        if not plugin_id:
            return "Upotreba: /plugin <id> <enable|disable|info|komanda> [args]"

        entry = self._entries.get(plugin_id)
        if entry is None:
            return f"Plugin '{plugin_id}' nije pronađen"

        if action == "enable":
            if self.enable(plugin_id):
                return f"Plugin '{plugin_id}' omogućen"
            return f"Plugin '{plugin_id}' ne može biti omogućen (stanje: {entry.state.value})"
        if action == "disable":
            if self.disable(plugin_id):
                return f"Plugin '{plugin_id}' onemogućen"
            return f"Plugin '{plugin_id}' ne može biti onemogućen (stanje: {entry.state.value})"

        if action == "info":
            md = entry.metadata
            return (
                f"Plugin: {md.name} ({plugin_id})\n"
                f"  Verzija: {md.version}\n"
                f"  Opis: {md.description or '—'}\n"
                f"  Autor: {md.author or '—'}\n"
                f"  Stanje: {entry.state.value}\n"
                f"  Kategorije: {', '.join(md.categories) or '—'}\n"
                f"  Dozvole: {', '.join(md.permissions) or '—'}"
            )

        if action and entry.state == PluginState.ENABLED:
            result = self._commands.handle(plugin_id, action, args)
            if result is not None:
                return result
        return f"Nepoznata komanda '{action}' za plugin '{plugin_id}'"
