"""Plugin system package — modular, secure extensions for the assistant.

Public API:
    Plugin, PluginError          — base class + exception (plugins.base)
    PluginMetadata, PluginState, PluginSecurityProfile, PluginLoadResult
                                  — data models (plugins.models)
    PluginManager                — lifecycle orchestration (plugins.manager)
    PluginCommand, PluginCommandRegistry
                                  — slash-command extension point (plugins.registry)
    discover_plugins, load_plugin
                                  — discovery + import helpers
    PLUGIN_API_VERSION           — supported plugin API version constant
"""

from __future__ import annotations

from plugins.base import Plugin, PluginError
from plugins.discovery import discover_plugins
from plugins.loader import load_plugin
from plugins.manager import PluginManager
from plugins.models import (
    PLUGIN_API_VERSION,
    PluginLoadResult,
    PluginMetadata,
    PluginSecurityProfile,
    PluginState,
)
from plugins.registry import PluginCommand, PluginCommandRegistry

__all__ = [
    "PLUGIN_API_VERSION",
    "Plugin",
    "PluginCommand",
    "PluginCommandRegistry",
    "PluginError",
    "PluginLoadResult",
    "PluginManager",
    "PluginMetadata",
    "PluginSecurityProfile",
    "PluginState",
    "discover_plugins",
    "load_plugin",
]
