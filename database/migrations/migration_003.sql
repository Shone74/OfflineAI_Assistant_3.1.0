-- Migration 003: Conversation context fields for FAZA 13.5
-- Adds workspace_id, project_id, and profile_snapshot to conversations table.

ALTER TABLE conversations ADD COLUMN workspace_id TEXT;
ALTER TABLE conversations ADD COLUMN project_id TEXT;
ALTER TABLE conversations ADD COLUMN profile_snapshot TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_workspace_id ON conversations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conversations_project_id ON conversations(project_id);