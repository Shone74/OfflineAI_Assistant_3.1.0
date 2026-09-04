"""Request router — dispatches incoming requests to registered modules.

The router is the single dispatch point between the Core Engine and
domain modules (AI, Memory, Tools, Voice, ...).  Modules register a
handler by name; the assistant routes requests by name.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from core.logger import get_logger

logger = get_logger("router")


class Router:
    """Central request dispatcher."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}

    def register(self, module_name: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        """Register a *handler* callable for *module_name*."""
        self._handlers[module_name] = handler
        logger.debug("Registered handler for module '%s'", module_name)
