"""Short-term memory — keeps the active conversation in RAM.

A bounded list of messages that rotates once it exceeds the configured
window size.  This is the context fed to the LLM on every turn.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from core.logger import get_logger

logger = get_logger("short_term")

DEFAULT_WINDOW = 10


@dataclass
class ShortTermMessage:
    role: str
    content: str


class ShortTermMemory:
    """In-memory conversation buffer with a configurable max length."""

    def __init__(self, max_window: int = DEFAULT_WINDOW) -> None:
        self._messages: deque[ShortTermMessage] = deque(maxlen=max_window)
        logger.info("ShortTermMemory ready (window=%d)", max_window)

    def add(self, role: str, content: str) -> None:
        self._messages.append(ShortTermMessage(role=role, content=content))
        logger.debug("STM add (%s): %d chars", role, len(content))

    def add_user(self, text: str) -> None:
        self.add("user", text)

    def add_assistant(self, text: str) -> None:
        self.add("assistant", text)

    def get_history(self) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in self._messages]

    def clear(self) -> None:
        self._messages.clear()
        logger.info("Short-term memory cleared")

    def __len__(self) -> int:
        return len(self._messages)

    def __getitem__(self, index: int) -> dict[str, str]:
        msg = self._messages[index]
        return {"role": msg.role, "content": msg.content}

    @property
    def max_window(self) -> int:
        return self._messages.maxlen  # type: ignore[return-value]

    def set_max_window(self, new_max: int) -> None:
        """Resize the deque capacity without losing existing recent entries.

        - Validates ``new_max`` is a positive integer.
        - Preserves as many of the most-recent messages as possible.
        - Never mutates the persistent SQLite database.
        - Never creates an invalid deque state.
        """
        if not isinstance(new_max, int) or new_max < 1:
            raise ValueError(f"new_max must be a positive integer, got {new_max!r}")
        if self._messages.maxlen == new_max:
            return
        old_messages = list(self._messages)
        logger.info(
            "ShortTermMemory resize: %d -> %d",
            self._messages.maxlen,
            new_max,
        )
        self._messages = deque(old_messages[-new_max:], maxlen=new_max)
