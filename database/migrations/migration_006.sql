-- Migration 006: Project workspace_path and settings columns
-- Adds a filesystem path column to projects for real workspace association,
-- and a settings column for project-specific configuration.
-- This is an additive, backward-compatible schema change.

ALTER TABLE projects ADD COLUMN workspace_path TEXT;
ALTER TABLE projects ADD COLUMN settings TEXT NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_projects_workspace_path ON projects(workspace_path);
