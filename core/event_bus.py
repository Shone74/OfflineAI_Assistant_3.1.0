"""Centralised Event Bus for inter-module communication.

All modules publish and subscribe through this bus — they never reference
each other directly.  This keeps the architecture loosely coupled.

Usage::

    bus = EventBus.get_instance()
    bus.subscribe("USER_MESSAGE_RECEIVED", my_handler)
    bus.publish("MODEL_LOADED", data={"model": "qwen-8b"})
"""

from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Callable
from typing import Any

EventCallback = Callable[[str, dict[str, Any]], None]


class EventBus:
    """Thread-safe publish/subscribe event bus (singleton)."""

    _instance: EventBus | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._subscribers: dict[str, dict[str, EventCallback]] = defaultdict(dict)
        self._lock: threading.RLock = threading.RLock()

    # ------------------------------------------------------------------ #
    @classmethod
    def get_instance(cls) -> EventBus:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------ #
    def subscribe(self, event_type: str, callback: EventCallback) -> str:
        """Register *callback* for *event_type*.

        Returns a subscription ID that can be passed to :meth:`unsubscribe`.
        """
        sub_id = str(uuid.uuid4())
        with self._lock:
            self._subscribers[event_type][sub_id] = callback
        return sub_id

    def unsubscribe(self, event_type: str, sub_id: str) -> None:
        with self._lock:
            self._subscribers[event_type].pop(sub_id, None)

    def publish(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Dispatch *event_type* to all subscribers with a copy of *data*."""
        event_data = data or {}
        with self._lock:
            callbacks = list(self._subscribers.get(event_type, {}).values())
        for callback in callbacks:
            try:
                callback(event_type, event_data)
            except Exception:
                import logging

                logging.getLogger("offlineai.event_bus").exception(
                    "Error in subscriber for event %s", event_type
                )

    def clear(self, event_type: str | None = None) -> None:
        """Remove all subscribers for *event_type*, or everything if ``None``."""
        with self._lock:
            if event_type is None:
                self._subscribers.clear()
            else:
                self._subscribers.pop(event_type, None)


EVENT_TYPES = frozenset(
    {
        "USER_MESSAGE_RECEIVED",
        "VOICE_COMMAND_RECEIVED",
        "AI_RESPONSE_RECEIVED",
        "MODEL_LOADED",
        "MODEL_UNLOADED",
        "MODEL_LOAD_FAILED",
        "GENERATION_STARTED",
        "GENERATION_TOKEN",
        "GENERATION_COMPLETED",
        "GENERATION_FAILED",
        "GENERATION_CANCELLED",
        "PLUGIN_STARTED",
        "PLUGIN_STOPPED",
        "TOOL_EXECUTED",
        "TASK_COMPLETED",
        "TASK_FAILED",
        "ERROR_OCCURRED",
        "CONFIG_CHANGED",
        "MEMORY_UPDATED",
        "AGENT_CREATED",
        "AGENT_UPDATED",
        "AGENT_DELETED",
        "AGENT_ENABLED",
        "AGENT_DISABLED",
        "AGENT_STARTED",
        "AGENT_STEP",
        "AGENT_TASK_STARTED",
        "AGENT_TASK_COMPLETED",
        "AGENT_ERROR",
        "AGENT_FINISHED",
        "AGENT_VERIFICATION",
        "PROFILE_UPDATED",
        "SHUTDOWN_REQUESTED",
        "APP_STARTED",
        "APP_STOPPED",
        "VOICE_INPUT_START",
        "VOICE_INPUT_END",
        "VOICE_TRANSCRIPT",
        "VOICE_PLAY_START",
        "VOICE_PLAY_DONE",
        "VOICE_ERROR",
        "VOICE_ENABLED_CHANGED",
        "VOICE_INPUT_ENABLED_CHANGED",
        "WAKE_WORD_DETECTED",
    }
)
