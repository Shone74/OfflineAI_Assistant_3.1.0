"""Memory Manager — coordinates short-term, long-term, and vector memory.

This is the single entry point the rest of the application uses to
interact with memory.  It owns a :class:`DatabaseManager` and lazily
initialises the embedding / vector backends.
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger
from database.database_manager import DatabaseManager
from database.models import MemoryEntry
from memory.embeddings import EmbeddingModel, StubEmbeddingModel, load_embedding_model
from memory.long_term import LongTermMemory
from memory.short_term import ShortTermMemory
from memory.vector_memory import VectorMemory

logger = get_logger("memory")


class MemoryManager:
    """Top-level facade over all memory subsystems."""

    def __init__(
        self,
        db_path: str | None = None,
        embedding_model: EmbeddingModel | None = None,
        embedding_backend: str = "stub",
        short_term_window: int = 10,
        default_workspace_id: str | None = None,
        default_project_id: str | None = None,
    ) -> None:
        self._db = DatabaseManager()
        self._long_term = LongTermMemory(self._db)
        self._short_term = ShortTermMemory(max_window=short_term_window)
        self._embedding_model = embedding_model or load_embedding_model(
            embedding_backend
        )
        self._vector = VectorMemory(self._embedding_model)

        # Lazy semantic index over long-term memory records (kept separate from
        # the arbitrary-text self._vector documents index; embeddings are NOT
        # persisted — no schema change).
        self._memory_index: VectorMemory | None = None
        self._memory_records: dict[str, MemoryEntry] = {}
        self._memory_index_count: int = -1

        self._conversation_id: int | None = None
        self._default_workspace_id = default_workspace_id
        self._default_project_id = default_project_id
        logger.info("MemoryManager initialised")

    # ------------------------------------------------------------------ #
    # Conversation lifecycle
    # ------------------------------------------------------------------ #
    def start_conversation(
        self,
        title: str = "",
        workspace_id: str | None = None,
        project_id: str | None = None,
        profile_snapshot: dict[str, Any] | None = None,
    ) -> int:
        """Create and activate a new conversation with context."""
        ws = workspace_id or self._default_workspace_id
        proj = project_id or self._default_project_id
        conv = self._long_term.save_conversation(
            title=title,
            workspace_id=ws,
            project_id=proj,
            profile_snapshot=profile_snapshot,
        )
        conv_id = conv.id or 0
        self._conversation_id = conv_id if conv_id else None
        self._short_term.clear()
        logger.info("Started conversation id=%s", conv_id)
        return conv_id or 0

    def end_conversation(self) -> None:
        if self._conversation_id is not None:
            logger.info("Ended conversation id=%d", self._conversation_id)
        self._conversation_id = None
        self._short_term.clear()

    def ensure_conversation(
        self,
        workspace_id: str | None = None,
        project_id: str | None = None,
        profile_snapshot: dict[str, Any] | None = None,
    ) -> int:
        """Create a conversation lazily if none exists (does NOT clear STM)."""
        if self._conversation_id is None:
            ws = workspace_id or self._default_workspace_id
            proj = project_id or self._default_project_id
            conv = self._long_term.save_conversation(
                workspace_id=ws,
                project_id=proj,
                profile_snapshot=profile_snapshot,
            )
            conv_id = conv.id or 0
            self._conversation_id = conv_id if conv_id else None
            logger.info("Lazily created conversation id=%s", conv_id)
        assert self._conversation_id is not None
        return self._conversation_id

    def select_conversation(self, conversation_id: int) -> bool:
        """Activate an existing conversation for subsequent message persistence.

        Unlike :meth:`start_conversation`, this does NOT create a new
        conversation record and does NOT clear short-term memory.
        The selected conversation becomes the active persistence target
        until a new conversation is started or ``end_conversation`` is called.

        Returns ``True`` if the conversation exists, ``False`` otherwise.
        """
        conv = self._long_term.get_conversation(conversation_id)
        if conv is None:
            return False
        self._conversation_id = conversation_id
        logger.info("Selected conversation id=%s", conversation_id)
        return True

    def load_conversation_into_stm(self, conversation_id: int) -> int:
        """Clear STM and populate it with messages from a persisted conversation.

        Clears the short-term memory buffer first (so no stale messages
        from a previous conversation leak into the new context), then loads
        all messages from the persisted conversation in chronological order.

        Returns the number of messages loaded.
        """
        self._short_term.clear()
        messages = self._long_term.get_messages(conversation_id)
        for msg in messages:
            self._short_term.add(msg.role, msg.content)
        return len(messages)

    def get_conversation_context(self, conversation_id: int) -> tuple[str | None, str | None, dict[str, Any] | None]:
        """Load the stored context for a conversation.

        Returns (workspace_id, project_id, profile_snapshot).
        """
        conv = self._long_term.get_conversation(conversation_id)
        if conv is None:
            return None, None, None
        return conv.workspace_id, conv.project_id, conv.profile_snapshot

    # ------------------------------------------------------------------ #
    # Conversation list / management (for UI sidebar)
    # ------------------------------------------------------------------ #
    def list_conversations(self) -> list[dict[str, Any]]:
        """Return all conversations as dicts for the ConversationSidebar UI."""
        convs = self._long_term.list_conversations()
        result = []
        for c in convs:
            result.append({
                "id": c.id,
                "title": c.title or f"Conversation {c.id}",
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "pinned": c.pinned,
            })
        return result

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        """Get conversation by ID as a dict."""
        conv = self._long_term.get_conversation(conversation_id)
        if conv is None:
            return None
        return {
            "id": conv.id,
            "title": conv.title or f"Conversation {conv.id}",
            "workspace_id": conv.workspace_id,
            "project_id": conv.project_id,
            "profile_snapshot": conv.profile_snapshot,
        }

    def delete_conversation(self, conversation_id: int) -> None:
        """Delete a conversation by ID."""
        self._long_term.delete_conversation(conversation_id)

    def rename_conversation(self, conversation_id: int, new_title: str) -> None:
        """Rename a conversation."""
        self._db.execute(
            "UPDATE conversations SET title = ?, updated_at = datetime('now') WHERE id = ?",
            (new_title, conversation_id),
        )
        logger.info("Conversation %d renamed to '%s'", conversation_id, new_title)

    def pin_conversation(self, conversation_id: int, pinned: bool) -> None:
        """Pin or unpin a conversation."""
        self._long_term.pin_conversation(conversation_id, pinned)

    def set_defaults(self, workspace_id: str | None = None, project_id: str | None = None) -> None:
        """Set default workspace/project for new conversations."""
        self._default_workspace_id = workspace_id
        self._default_project_id = project_id

    def get_messages(self, conversation_id: int) -> list[Any]:
        """Get all messages in a conversation."""
        return self._long_term.get_messages(conversation_id)

    # ------------------------------------------------------------------ #
    # Message handling (short-term + long-term)
    # ------------------------------------------------------------------ #
    def add_user_message(self, text: str) -> None:
        self._short_term.add_user(text)
        cid = self.ensure_conversation()
        self._long_term.save_message(cid, "user", text)
        logger.debug("User message stored (conv=%d)", cid)

    def add_assistant_message(self, text: str) -> None:
        self._short_term.add_assistant(text)
        cid = self.ensure_conversation()
        self._long_term.save_message(cid, "assistant", text)
        logger.debug("Assistant message stored (conv=%d)", cid)

    def get_history(self) -> list[dict[str, str]]:
        return self._short_term.get_history()

    # ------------------------------------------------------------------ #
    # Durable memorizable facts / preferences
    # ------------------------------------------------------------------ #
    def save_memory(
        self, content: str, mem_type: str = "fact", importance: float = 0.5,
        agent_id: int | None = None,
    ) -> int:
        entry = MemoryEntry(type=mem_type, content=content, importance=importance, agent_id=agent_id)
        return self._long_term.save_memory(entry)

    def search_memories(self, query: str, limit: int = 10) -> list[Any]:
        return self._long_term.search_relevant_memories(query, limit=limit)

    def search_memories_by_agent(self, agent_id: int, query: str, limit: int = 10) -> list[MemoryEntry]:
        """Return memories associated with *agent_id* matching *query*."""
        return self._long_term.search_memories_by_agent(agent_id, query, limit=limit)

    def get_all_memories(self, limit: int = 100) -> list[Any]:
        return self._long_term.get_all_memories(limit=limit)

    def get_agent_memories(self, agent_id: int, limit: int = 100) -> list[MemoryEntry]:
        """Return all memories associated with *agent_id*."""
        rows = self._long_term._db.query(
            "SELECT * FROM memories WHERE agent_id = ? "
            "ORDER BY importance DESC, last_used DESC, created_at DESC LIMIT ?",
            (agent_id, limit),
        )
        return self._long_term._rows_to_entries(rows)

    def find_preference_memory(self, key: str) -> MemoryEntry | None:
        """Return the single memory row stored for a preference *key*, if any."""
        return self._long_term.find_preference_memory(key)

    def update_memory(self, entry: MemoryEntry) -> bool:
        self.clear_semantic_index()
        return self._long_term.update_memory(entry)

    def delete_memory(self, mem_id: int) -> None:
        self.clear_semantic_index()
        self._long_term.delete_memory(mem_id)

    def delete_message(self, message_id: int) -> bool:
        return self._long_term.delete_message(message_id)

    def delete_all_memories(self) -> int:
        self.clear_semantic_index()
        return self._long_term.delete_all_memories()


    def get_preference(self, key: str, default: str | None = None) -> str | None:
        return self._long_term.get_setting(key, default)

    def set_preference(self, key: str, value: str, category: str = "user") -> None:
        """Persist a user preference, upserting a single memory row per key.

        The setting is always upserted into ``settings`` (unchanged behaviour).
        For the memory row, instead of appending a new row on every call we:
          - create one the first time a key is seen,
          - do nothing when the serialized value is identical to the existing
            memory (prevents duplicate ``assistant_profile`` rows on shutdown),
          - update the existing row when the value actually changes.
        This keeps long-term memory from growing unbounded on repeated saves of
        an unchanged profile.
        """
        self.clear_semantic_index()
        self._long_term.set_setting(key, value, category)
        mem_content = f"User prefers: {key} = {value}"
        existing = self._long_term.find_preference_memory(key)
        if existing is None:
            self.save_memory(content=mem_content, mem_type="user_preference")
        elif existing.content == mem_content:
            return
        else:
            self._long_term.update_memory(
                MemoryEntry(
                    id=existing.id,
                    type=existing.type,
                    content=mem_content,
                    importance=existing.importance,
                    created_at=existing.created_at,
                    last_used=existing.last_used,
                )
            )
            logger.info("Preference memory updated for key=%s", key)

    # ------------------------------------------------------------------ #
    # Vector / semantic memory
    # ------------------------------------------------------------------ #
    def index_documents(self, texts: list[str]) -> list[str]:
        return self._vector.add_texts(texts)

    def search_documents(self, query: str, k: int = 5) -> list[tuple[Any, float]]:
        return self._vector.search(query, k=k)

    # ------------------------------------------------------------------ #
    # Semantic retrieval over long-term memory records
    # ------------------------------------------------------------------ #
    def semantic_search(
        self, query: str, k: int = 5
    ) -> list[tuple[MemoryEntry, float]]:
        """Rank stored memories by semantic similarity to *query*.

        Encodes *query* and the (cached) long-term memory records with the
        configured embedding model via :class:`VectorMemory`, then returns the
        top-*k* ``(MemoryEntry, similarity)`` pairs sorted by descending
        similarity.  This is an *additional* capability alongside keyword
        ``search_memories`` — it does not replace it, is not persisted, and is
        not wired into chat or ``build_context`` (that belongs to a later
        milestone).
        """
        self._ensure_memory_index()
        if self._memory_index is None or not self._memory_records:
            return []
        results = self._memory_index.search(query, k=k)
        ranked: list[tuple[MemoryEntry, float]] = []
        for entry, score in results:
            mem = self._memory_records.get(entry.id)
            if mem is not None:
                ranked.append((mem, score))
        return ranked

    def clear_semantic_index(self) -> None:
        """Drop the cached semantic index (forces a rebuild on next search)."""
        self._memory_index = None
        self._memory_records = {}
        self._memory_index_count = -1

    def _ensure_memory_index(self) -> None:
        """Lazily (re)build the in-memory embedding index over memory records.

        Rebuilds only when the live memory count differs from the cached count,
        so repeated searches are cheap.  Embeddings are generated on demand and
        never written back to the database.
        """
        if self._memory_index is None:
            self._memory_index = VectorMemory(self._embedding_model)
            self._memory_index_count = -1
        live = self._long_term.count_memories()
        if live == self._memory_index_count:
            return
        self._memory_index.clear()
        self._memory_records = {}
        for mem in self._long_term.get_all_memories(limit=10000):
            if mem.content:
                entry_id = self._memory_index.add(mem.content)
                self._memory_records[entry_id] = mem
        self._memory_index_count = live

    # ------------------------------------------------------------------ #
    # Context assembly for the LLM prompt
    # ------------------------------------------------------------------ #
    def build_context(self, user_input: str, max_memories: int = 5) -> dict[str, Any]:
        """Build the full context dict to prepend to the LLM prompt.

        Hybrid retrieval: existing keyword results are always consulted; when a
        real (non-stub) embedding model is configured, semantic results are
        merged in as well. Candidates are de-duplicated, ranked (semantic hits
        first by descending similarity, then keyword candidates in their existing
        order) and capped at ``max_memories``. The existing output structure
        (``history`` + ``relevant_memories`` of ``{type, content}``) is preserved
        so ``Assistant._memories_for_prompt`` is unchanged.

        Semantic retrieval is gated on Memory being ON (this method is only
        reached when ``Assistant._memory_enabled()`` is True) and on a real
        embedding backend being configured. On any semantic failure it degrades
        to keyword-only results so Chat never breaks.
        """
        history = self.get_history()
        keyword = self.search_memories(user_input, limit=max_memories)

        semantic: list[tuple[MemoryEntry, float]] = []
        if max_memories > 0 and self._has_real_embedding_model():
            try:
                semantic = self.semantic_search(user_input, k=max_memories)
            except Exception:
                logger.warning("Semantic retrieval failed — using keyword-only results")
                semantic = []

        relevant_memories = self._merge_semantic_keyword(semantic, keyword, max_memories)
        return {
            "history": history,
            "relevant_memories": [
                {"type": m.type, "content": m.content} for m in relevant_memories
            ],
        }

    def _has_real_embedding_model(self) -> bool:
        """True when a real semantic backend is configured (not the stub)."""
        return not isinstance(self._embedding_model, StubEmbeddingModel)

    def get_embedding_model_info(self) -> dict[str, Any]:
        """Return information about the embedding backend.

        Returns a dict with:
        - ``name``: The actual model name (e.g., "sentence-transformers", "mxbai-gguf", "stub")
        - ``is_stub``: True when semantic retrieval is inactive (using stub fallback)
        - ``intended_name``: The backend name requested by config (if fallback occurred)
        - ``dimension``: The vector embedding dimension

        This allows UI to inform users when semantic retrieval is NOT active
        even though they selected a "real" backend.
        """
        model = self._embedding_model
        return {
            "name": model.name if hasattr(model, "name") else "stub",
            "is_stub": model.is_stub_fallback if hasattr(model, "is_stub_fallback") else True,
            "intended_name": model.intended_name if hasattr(model, "intended_name") else None,
            "dimension": model.dimension,
        }

    def _memory_key(self, m: MemoryEntry) -> str:
        """Stable identity for de-duplication (id when available, else content)."""
        if m.id is not None:
            return f"id:{m.id}"
        return f"content:{m.content}"

    def _merge_semantic_keyword(
        self,
        semantic: list[tuple[MemoryEntry, float]],
        keyword: list[MemoryEntry],
        max_memories: int,
    ) -> list[MemoryEntry]:
        """Merge, de-dup, rank, and cap memory candidates for the prompt.

        Semantic hits (with scores) rank first by descending similarity;
        keyword-only candidates follow in their existing keyword order. The same
        memory appears at most once. The result never exceeds ``max_memories``.
        """
        seen: set[str] = set()
        merged: list[MemoryEntry] = []

        for mem, _score in sorted(semantic, key=lambda pair: pair[1], reverse=True):
            key = self._memory_key(mem)
            if key in seen:
                continue
            seen.add(key)
            merged.append(mem)
            if len(merged) >= max_memories:
                return merged

        for mem in keyword:
            key = self._memory_key(mem)
            if key in seen:
                continue
            seen.add(key)
            merged.append(mem)
            if len(merged) >= max_memories:
                break

        return merged

    # ------------------------------------------------------------------ #
    # Agent-scoped context assembly
    # ------------------------------------------------------------------ #
    def build_agent_context(self, agent_id: int, query: str, max_memories: int = 5) -> list[dict[str, str]]:
        """Retrieve memories scoped to *agent_id* relevant to *query*.

        Reuses the existing keyword search infrastructure — no new vector
        store or embedding model is introduced. Returns an empty list when
        Memory is disabled or no manager is available.
        """
        memories = self.search_memories_by_agent(agent_id, query, limit=max_memories)
        return [{"type": m.type, "content": m.content} for m in memories]

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self._db.close()
        logger.info("MemoryManager closed")

    @property
    def db(self) -> DatabaseManager:
        return self._db

    @property
    def conversation_id(self) -> int | None:
        return self._conversation_id
