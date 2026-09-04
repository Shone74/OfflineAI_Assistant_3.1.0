"""Agent memory integration — associates memories with specific Agents.

This is an **integration layer** over the existing :class:`MemoryManager`.
It does NOT create a new memory subsystem, vector database, or embedding
model.  It reuses the existing SQLite ``memories`` table (extended with an
optional ``agent_id`` column via migration_005.sql) and the existing
keyword/semantic retrieval infrastructure.

Conceptual flow:

    Agent goal/task
          ↓
        AgentMemory.recall(goal)        — retrieve agent-scoped memories
          ↓                                 (existing MemoryManager.search_memories_by_agent)
    relevant memory context
          ↓
    Planner prompt                     — memories are injected, not auto-saved

    ... Agent runs ...
          ↓
    AgentMemory.remember(content)      — controlled, intentional memory creation
          ↓                                 (only called by explicit decision, NOT automatically)
    MemoryManager.save_memory(...)     — stores via existing LongTermMemory
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.logger import get_logger

if TYPE_CHECKING:
    from memory.memory_manager import MemoryManager

logger = get_logger("agent_memory")


class AgentMemory:
    """Scopes existing MemoryManager operations to a specific Agent.

    All persistence goes through the single ``MemoryManager`` /
    ``DatabaseManager`` — no second storage, no second vector DB.
    """

    def __init__(
        self,
        memory_manager: MemoryManager | None,
        agent_id: int | None,
        agent_name: str = "",
        memory_enabled: bool = True,
    ) -> None:
        self._memory = memory_manager
        self._agent_id = agent_id
        self._agent_name = agent_name
        self._memory_enabled = memory_enabled

    @property
    def agent_id(self) -> int | None:
        return self._agent_id

    @property
    def is_enabled(self) -> bool:
        """True when a MemoryManager is available AND global Memory is ON."""
        return self._memory is not None and self._memory_enabled

    def recall(self, query: str, max_memories: int = 5) -> list[Any]:
        """Retrieve memories associated with this Agent relevant to *query*.

        Returns an empty list when Memory is disabled or no manager is
        available.  Retrieval uses the existing keyword search infrastructure.
        """
        if not self.is_enabled:
            return []
        if self._agent_id is None:
            return []
        memories = self._memory.search_memories_by_agent(  # type: ignore[union-attr]
            self._agent_id, query, limit=max_memories,
        )
        logger.debug(
            "Agent '%s' recalled %d memory(s) for query: %s",
            self._agent_name, len(memories), query,
        )
        return memories

    def remember(self, content: str, mem_type: str = "fact", importance: float = 0.5) -> int | None:
        """Create a memory entry associated with this Agent.

        This is a **controlled** operation — callers must decide what is
        worth persisting.  It is NOT called automatically for every message
        or tool result.

        Returns the memory id, or ``None`` when Memory is disabled.
        """
        if not self.is_enabled:
            logger.info(
                "Agent '%s' memory creation skipped (Memory disabled)",
                self._agent_name,
            )
            return None
        if self._agent_id is None:
            return None
        mem_id = self._memory.save_memory(  # type: ignore[union-attr]
            content=content, mem_type=mem_type, importance=importance,
            agent_id=self._agent_id,
        )
        logger.info(
            "Agent '%s' created memory id=%d (type=%s)",
            self._agent_name, mem_id, mem_type,
        )
        return mem_id

    def get_memories(self, limit: int = 50) -> list[Any]:
        """Return all memories for this Agent (most important first)."""
        if not self.is_enabled or self._agent_id is None:
            return []
        return self._memory.get_agent_memories(self._agent_id, limit=limit)  # type: ignore[union-attr]
