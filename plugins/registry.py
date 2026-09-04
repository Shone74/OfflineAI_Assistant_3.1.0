"""Plugin command registry — controlled extension point for ``/plugin`` commands.

Plugins may register named commands (e.g. ``/plugin mytool do_thing``).  The
registry performs deterministic routing by ``(plugin_id, name)`` and never
intercepts arbitrary chat messages — it is only invoked once
:class:`core.assistant.Assistant` has matched the ``/plugin`` prefix.

Dependency note: depends only on ``core.logger`` — deliberately decoupled from
:class:`plugins.manager.PluginManager` to avoid import cycles.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger

logger = get_logger("plugins.registry")

CommandHandler = Callable[[str], str]


@dataclass
class PluginCommand:
    """A single slash-command declared by a plugin."""

    name: str
    description: str
    handler: CommandHandler
    plugin_id: str = ""

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("PluginCommand requires a name")


class PluginCommandRegistry:
    """Routes plugin-declared slash commands by ``(plugin_id, name)``."""

    def __init__(self) -> None:
        self._commands: dict[str, list[PluginCommand]] = defaultdict(list)

    def register(self, command: PluginCommand) -> None:
        bucket = self._commands[command.plugin_id]
        # Replace any existing command with the same name for this plugin.
        for i, existing in enumerate(bucket):
            if existing.name == command.name:
                bucket[i] = command
                logger.debug("Plugin command updated: %s.%s", command.plugin_id, command.name)
                return
        bucket.append(command)
        logger.debug("Plugin command registered: %s.%s", command.plugin_id, command.name)

    def unregister_plugin(self, plugin_id: str) -> None:
        removed = self._commands.pop(plugin_id, None)
        if removed:
            logger.debug("Unregistered %d command(s) for plugin '%s'", len(removed), plugin_id)

    def get(self, plugin_id: str, name: str) -> PluginCommand | None:
        for cmd in self._commands.get(plugin_id, []):
            if cmd.name == name:
                return cmd
        return None

    def commands_for(self, plugin_id: str) -> list[PluginCommand]:
        return list(self._commands.get(plugin_id, []))

    def list_commands(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for plugin_id, cmds in self._commands.items():
            for cmd in cmds:
                out.append(
                    {
                        "plugin_id": plugin_id,
                        "name": cmd.name,
                        "description": cmd.description,
                    }
                )
        return out

    def handle(self, plugin_id: str, name: str, args: str) -> str | None:
        cmd = self.get(plugin_id, name)
        if cmd is None:
            return None
        try:
            logger.debug("Dispatching plugin command %s.%s(%r)", plugin_id, name, args)
            return cmd.handler(args)
        except Exception as exc:
            logger.exception("Plugin command %s.%s raised", plugin_id, name)
            return f"Greška u komandi '{name}': {exc}"
