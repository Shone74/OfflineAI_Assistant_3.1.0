-- Migration 004: Agent definitions table for Agent System persistence
-- Creates the agents table for storing persistent agent definitions.
-- This is an additive schema change — existing tables are not modified.

CREATE TABLE IF NOT EXISTS agents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    description     TEXT NOT NULL DEFAULT '',
    system_prompt   TEXT NOT NULL DEFAULT '',
    model_name      TEXT NOT NULL DEFAULT '',
    enabled         INTEGER NOT NULL DEFAULT 1,
    tool_whitelist  TEXT NOT NULL DEFAULT '[]',
    permission_profile TEXT NOT NULL DEFAULT 'default',
    profile_snapshot TEXT,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agents_name ON agents(name);
CREATE INDEX IF NOT EXISTS idx_agents_enabled ON agents(enabled);
