-- Migration 005: Agent memory association
-- Adds an optional agent_id column to the memories table so that
-- memories created during Agent execution can be associated with a
-- specific persisted Agent definition.
--
-- This is an additive, backward-compatible schema change:
--   - The column defaults to NULL (no agent association).
--   - Existing memory rows are unaffected.
--   - Existing migrations are NOT modified.

ALTER TABLE memories ADD COLUMN agent_id INTEGER DEFAULT NULL;

CREATE INDEX IF NOT EXISTS idx_memories_agent_id ON memories(agent_id);
