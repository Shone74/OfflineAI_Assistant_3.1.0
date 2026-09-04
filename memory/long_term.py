"""Long-term memory — persists conversations, messages, and facts in SQLite.

All database access goes through :class:`DatabaseManager`.  Never open a
raw ``sqlite3`` connection outside this module.
"""

from __future__ import annotations

import json
from typing import Any

from core.logger import get_logger
from database.database_manager import DatabaseManager, row_to_conversation
from database.models import Conversation, MemoryEntry, Message

logger = get_logger("long_term")


class LongTermMemory:
    """SQLite-backed persistence for conversations and durable memories."""

    def __init__(self, db: DatabaseManager) -> None:
        self._db = db
        logger.info("LongTermMemory ready (SQLite)")

    # ------------------------------------------------------------------ #
    # Conversations & messages
    # ------------------------------------------------------------------ #
    def save_conversation(
        self,
        title: str = "",
        workspace_id: str | None = None,
        project_id: str | None = None,
        profile_snapshot: dict[str, Any] | None = None,
        pinned: bool = False,
    ) -> Conversation:
        profile_json = json.dumps(profile_snapshot) if profile_snapshot else None
        cur = self._db.execute(
            "INSERT INTO conversations (title, summary, workspace_id, project_id, profile_snapshot, is_pinned, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (title or "Nova razgovor", "", workspace_id, project_id, profile_json, 1 if pinned else 0),
        )
        return Conversation(
            id=cur.lastrowid,
            title=title or "Nova razgovor",
            summary="",
            workspace_id=workspace_id,
            project_id=project_id,
            profile_snapshot=profile_snapshot,
            pinned=pinned,
        )

    def get_conversation(self, conv_id: int) -> Conversation | None:
        row = self._db.query_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        if row is None:
            return None
        return row_to_conversation(row)

    def list_conversations(self) -> list[Conversation]:
        rows = self._db.query(
            "SELECT * FROM conversations ORDER BY is_pinned DESC, updated_at DESC"
        )
        return [row_to_conversation(r) for r in rows]

    def save_message(self, conversation_id: int, role: str, content: str) -> Message:
        cur = self._db.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) "
            "VALUES (?, ?, ?, datetime('now'))",
            (conversation_id, role, content),
        )
        return Message(
            id=cur.lastrowid,
            conversation_id=conversation_id,
            role=role,
            content=content,
        )

    def get_messages(self, conversation_id: int) -> list[Message]:
        rows = self._db.query(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        )
        return [
            Message(
                id=r["id"],
                conversation_id=r["conversation_id"],
                role=r["role"],
                content=r["content"],
                timestamp=r["timestamp"],
            )
            for r in rows
        ]

    def delete_conversation(self, conv_id: int) -> None:
        self._db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        logger.info("Conversation %d deleted", conv_id)

    def delete_message(self, message_id: int) -> bool:
        cur = self._db.execute(
            "DELETE FROM messages WHERE id = ?", (message_id,)
        )
        deleted = cur.rowcount > 0
        if deleted:
            logger.info("Message %d deleted", message_id)
        return deleted

    def pin_conversation(self, conversation_id: int, pinned: bool) -> None:
        self._db.execute(
            "UPDATE conversations SET is_pinned = ?, updated_at = datetime('now') WHERE id = ?",
            (1 if pinned else 0, conversation_id),
        )
        logger.info("Conversation %d pinned=%s", conversation_id, pinned)

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #
    def set_setting(self, key: str, value: str, category: str = "general") -> None:
        self._db.execute(
            "INSERT INTO settings (key, value, category) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, category=excluded.category",
            (key, value, category),
        )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self._db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    # ------------------------------------------------------------------ #
    # Durable memorizable facts / preferences / agent memories
    # ------------------------------------------------------------------ #
    def save_memory(self, mem: MemoryEntry) -> int:
        cur = self._db.execute(
            "INSERT INTO memories (type, content, importance, agent_id, created_at, last_used) "
            "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (mem.type, mem.content, mem.importance, mem.agent_id),
        )
        result: int = cur.lastrowid if cur.lastrowid is not None else 0
        return result

    def search_memories(self, mem_type: str | None = None, limit: int = 50) -> list[MemoryEntry]:
        if mem_type:
            rows = self._db.query(
                "SELECT * FROM memories WHERE type = ? ORDER BY importance DESC, last_used DESC LIMIT ?",
                (mem_type, limit),
            )
        else:
            rows = self._db.query(
                "SELECT * FROM memories ORDER BY importance DESC, last_used DESC LIMIT ?",
                (limit,),
            )
        return self._rows_to_entries(rows)

    def search_memories_by_agent(self, agent_id: int, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Return memories associated with *agent_id* matching *query* keywords.

        Falls back to returning agent memories (unfiltered by query keywords)
        when no keyword match is found, so the Agent still receives context.
        """
        keywords = [w for w in query.lower().split() if len(w) > 2]
        if keywords:
            where_clause = "agent_id = ? AND (" + " OR ".join(
                "lower(content) LIKE ?" for _ in keywords
            ) + ")"
            params: list[Any] = [agent_id]
            for kw in keywords:
                params.append(f"%{kw}%")
            params.append(limit)
            rows = self._db.query(
                f"SELECT * FROM memories WHERE {where_clause} "
                "ORDER BY importance DESC, last_used DESC LIMIT ?",
                tuple(params),
            )
            results = self._rows_to_entries(rows)
            if results:
                return results

        # No keyword match — return all agent memories
        rows = self._db.query(
            "SELECT * FROM memories WHERE agent_id = ? "
            "ORDER BY importance DESC, last_used DESC LIMIT ?",
            (agent_id, limit),
        )
        return self._rows_to_entries(rows)

    def search_relevant_memories(self, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Return memories whose *content* contains a keyword from *query*."""
        keywords = [w for w in query.lower().split() if len(w) > 2]
        results: list[MemoryEntry] = []
        for mem in self.search_memories(limit=200):
            if any(kw in mem.content.lower() for kw in keywords):
                results.append(mem)
                if len(results) >= limit:
                    break
        return results

    def _rows_to_entries(self, rows: list[Any]) -> list[MemoryEntry]:
        """Convert raw SQLite rows to MemoryEntry objects."""
        return [
            MemoryEntry(
                id=r["id"], type=r["type"], content=r["content"],
                importance=r["importance"], agent_id=r["agent_id"] if "agent_id" in r.keys() else None,  # noqa: SIM118
                created_at=r["created_at"], last_used=r["last_used"],
            )
            for r in rows
        ]

    def get_all_memories(self, limit: int = 100) -> list[MemoryEntry]:
        """Return all memories ordered by importance then recency."""
        rows = self._db.query(
            "SELECT * FROM memories ORDER BY importance DESC, last_used DESC, created_at DESC LIMIT ?",
            (limit,),
        )
        return self._rows_to_entries(rows)

    def count_memories(self) -> int:
        """Total number of stored memory rows (used for index cache invalidation)."""
        row = self._db.query_one("SELECT COUNT(*) AS n FROM memories")
        return int(row["n"]) if row else 0

    def find_preference_memory(self, key: str) -> MemoryEntry | None:
        """Return the existing memory row for a preference *key*, if any.

        Preferences are persisted as ``Korisnik preferira: {key} = {value}``
        memory rows.  There should be at most one row per key; this lookup
        enables upsert semantics for ``set_preference`` without appending
        duplicates.
        """
        prefix = f"Korisnik preferira: {key} = "
        rows = self._db.query(
            "SELECT * FROM memories WHERE type = ?",
            ("user_preference",),
        )
        for r in rows:
            content = r["content"]
            if content.startswith(prefix):
                return MemoryEntry(
                    id=r["id"], type=r["type"], content=content,
                    importance=r["importance"], created_at=r["created_at"],
                    last_used=r["last_used"],
                )
        return None

    def update_memory(self, entry: MemoryEntry) -> bool:
        """Update an existing memory in place. Returns False if id is missing."""
        if entry.id is None:
            return False
        self._db.execute(
            "UPDATE memories SET type = ?, content = ?, importance = ?, last_used = datetime('now') "
            "WHERE id = ?",
            (entry.type, entry.content, entry.importance, entry.id),
        )
        logger.info("Memory %d updated", entry.id)
        return True

    def delete_memory(self, mem_id: int) -> None:
        """Delete a single memory by id (leaves conversations/messages untouched)."""
        self._db.execute("DELETE FROM memories WHERE id = ?", (mem_id,))
        logger.info("Memory %d deleted", mem_id)

    def delete_all_memories(self) -> int:
        """Delete every row in the memories table. Returns rows deleted."""
        cur = self._db.execute("DELETE FROM memories")
        count = cur.rowcount if cur.rowcount is not None else 0
        logger.info("All memories deleted (%d rows)", count)
        return count
