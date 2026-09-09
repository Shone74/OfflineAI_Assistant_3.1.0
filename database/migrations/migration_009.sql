-- Migration 009: messages(conversation_id) index (Phase 10 Task 4, M8)
-- get_messages(conversation_id) is executed on every conversation load
-- (memory page / chat history sidebar). Without an index it performs a
-- full-table scan over ALL messages in the database — the cost grows
-- linearly with total conversation history, directly degrading UI
-- response as the database accumulates history.
--
-- The conversations table (is_pinned, updated_at) already benefits from
-- its primary key; messages only has the autoincrement PK, so every
-- conversation_id filter had to walk the whole table.

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages (conversation_id);
