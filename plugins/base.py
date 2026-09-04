"""Plugin base class — lifecycle hooks every plugin implements.

A plugin is a plain Python class subclassing :class:`Plugin`.  Implementations
declare their identity via :attr:`metadata` (typically a class-level
:class:`PluginMetadata`) and extend tool/command registration through the
lifecycle methods.

Dependency note: this module depends only on ``core.logger`` and
``tools.base`` interfaces — never on ``core.assistant``.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, ClassVar

from core.logger import get_logger
from tools.base import Tool, ToolRegistry

if TYPE_CHECKING:
    from plugins.models import PluginMetadata

logger = get_logger("plugins")


class PluginError(Exception):
    """Raised for plugin lifecycle failures (load/initialize errors)."""


class Plugin(ABC):
    """Abstract base class for all plugins."""

    metadata: PluginMetadata
    events: ClassVar[list[str]] = []

    def initialize(
        self,
        registry: ToolRegistry | None = None,
        event_bus: Any | None = None,
        security_profile: Any | None = None,
    ) -> None:
        """Called once, right after the plugin module is loaded.

        Subclasses override to capture ``registry``/``event_bus`` references
        or perform setup that does not (yet) register tools.
        """

    def enable(self) -> None:
        """Called when the plugin is enabled (after tools/commands registered)."""

    def disable(self) -> None:
        """Called when the plugin is disabled (tools/commands unregistered)."""

    def unload(self) -> None:
        """Called when the plugin is unloaded from memory."""

    def register_tools(self, registry: ToolRegistry) -> list[Tool]:
        """Return the tools this plugin contributes.

        Each returned tool is registered via ``registry.register(tool)`` by the
        :class:`PluginManager` — plugins must **never** call
        ``tool.execute()`` directly.
        """
        return []

    def register_commands(self) -> list[Any]:
        """Return :class:`PluginCommand` objects this plugin contributes"""
        return []

    def on_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Receive events the plugin subscribed to (see :attr:`events`)."""

    def on_startup(self) -> None:
        """Hook fired once the full application is started."""

    def on_shutdown(self) -> None:
        """Hook fired once during application shutdown."""
