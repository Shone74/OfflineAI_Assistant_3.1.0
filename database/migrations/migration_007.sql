-- Migration 007: Conversation pin support for FAZA 13.5
-- Allows users to mark important conversations for easy access

ALTER TABLE conversations ADD COLUMN is_pinned INTEGER DEFAULT 0;