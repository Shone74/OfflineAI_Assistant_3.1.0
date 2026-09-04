"""Plugin loader — imports a plugin module and instantiates its class.

The loader uses ``importlib`` to resolve ``module:attr`` entry points and
isolate failures: any exception during import or instantiation is caught,
logged, and surfaced as a ``PLUGIN_LOAD_FAILED`` event — the broken plugin
never crashes startup or sibling plugins.

Security note: only ``importlib.import_module`` is used — never
``importlib.reload``.  Re-running an arbitrary already-imported module's
top-level code (as ``reload`` would) can corrupt live singletons such as the
``EventBus``/``SecurityLayer`` and is intentionally avoided.  The manifest's
``entry_point`` is treated as trusted operator input (the plugin directory is
local, operator-controlled); future hardening may load each plugin from an
explicit file path under its own directory.
"""

from __future__ import annotations

import importlib
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from plugins.base import Plugin, PluginError
from plugins.models import PluginMetadata, parse_entry_point
from tools.base import ToolRegistry

logger = get_logger("plugins.loader")


def _publish(event_type: str, data: dict[str, Any], event_bus: Any = None) -> None:
    """Publish *event_type* to *event_bus* when given, else the singleton bus."""
    bus = event_bus or EventBus.get_instance()
    bus.publish(event_type, data=data)


def initialize_plugin(
    metadata: PluginMetadata,
    instance: Plugin,
    registry: ToolRegistry | None,
    event_bus: Any,
) -> None:
    """Attach metadata and run the plugin's ``initialize`` hook.

    Shared by :func:`load_plugin` and :meth:`PluginManager.load_instance` so the
    init sequence (metadata assignment + hook + security profile wiring) and the
    event-bus target never diverge.
    """
    instance.metadata = metadata
    instance.initialize(
        registry=registry,
        event_bus=event_bus,
        security_profile=metadata.security_profile,
    )


def _instantiate(metadata: PluginMetadata) -> Plugin:
    """Import the module and return a constructed (not yet initialized) plugin."""
    entry = parse_entry_point(metadata.entry_point)
    if entry is None:
        raise PluginError(f"Invalid entry_point '{metadata.entry_point}'")
    module_name, attr_name = entry

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise PluginError(f"Cannot import plugin module '{module_name}'") from exc

    try:
        factory = getattr(module, attr_name)
    except AttributeError as exc:
        raise PluginError(f"Entry point '{attr_name}' not found in '{module_name}'") from exc

    instance = factory() if callable(factory) else factory
    if not isinstance(instance, Plugin):
        raise PluginError(
            f"Entry point '{module_name}:{attr_name}' is not a Plugin subclass "
            f"(got {type(instance).__name__})"
        )
    return instance


def load_plugin(
    metadata: PluginMetadata,
    registry: ToolRegistry | None = None,
    event_bus: Any = None,
) -> Plugin | None:
    """Load and initialize a single plugin.

    Returns the live :class:`Plugin` instance, or ``None`` if loading failed
    (the failure is logged + published so the manager can mark it FAILED).
    Lifecycle events are published to *event_bus* when supplied, otherwise to
    the :class:`EventBus` singleton — matching the manager's injected bus.
    """
    plugin_id = metadata.id
    bus = event_bus or EventBus.get_instance()
    logger.info("Loading plugin '%s' (entry_point=%s)", plugin_id, metadata.entry_point)
    _publish("PLUGIN_LOAD_START", {"plugin_id": plugin_id}, bus)

    try:
        instance = _instantiate(metadata)
        initialize_plugin(metadata, instance, registry, event_bus)
    except Exception as exc:
        logger.exception("Plugin '%s' failed to load (entry_point=%s)", plugin_id, metadata.entry_point)
        _publish(
            "PLUGIN_LOAD_FAILED",
            {"plugin_id": plugin_id, "reason": "load_error", "error": str(exc)},
            bus,
        )
        return None

    _publish(
        "PLUGIN_LOADED",
        {"plugin_id": plugin_id, "entry_point": metadata.entry_point},
        bus,
    )
    logger.info("Plugin '%s' loaded successfully", plugin_id)
    return instance
