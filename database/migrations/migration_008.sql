-- Migration 008: Database Schema Cleanup (Phase 2.4C)
-- Removes six dead tables that are no longer referenced by any active
-- application code, indexes, triggers, or views.
--
-- Tables removed:
--   users       — legacy user tracking (no active references)
--   tasks       — legacy task scheduling (no active references)
--   plugins     — legacy plugin registry (PluginManager uses directory-based discovery)
--   permissions — legacy plugin permissions (depends on plugins table)
--   models      — legacy model registry (ModelManager uses file-based discovery)
--   logs        — legacy log storage (uses file-based logging via core.logger)
--
-- Drop order matters: permissions has a FOREIGN KEY (plugin_id) referencing plugins.
-- permissions is dropped first to avoid FK constraint violations.

DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS plugins;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS tasks;
DROP TABLE IF EXISTS models;
DROP TABLE IF EXISTS logs;
