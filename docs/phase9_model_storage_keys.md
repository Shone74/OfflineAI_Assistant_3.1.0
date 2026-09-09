# Phase 9 — Model-Storage Settings: Roles of the Three Keys

Status: **documented contract** (Phase 9 Task 3). No migration is
performed; all three keys are intentionally retained.

## `models.storage_root` — CANONICAL

The single canonical model-storage root. New code and UI treat this as
the primary root; the Welcome wizard and the Settings model-storage tab
persist it through `core.paths.set_models_root()`.

- Resolution precedence: `OFFLINE_AI_MODELS_ROOT` env (tests) → this
  key → legacy `ai.models_dir` → `<user_data>/models` default
  suggestion.
- Category directories derive from it:
  `<root>/llm`, `<root>/embedding`, `<root>/stt`
  (the `stt` resolver honors the legacy `<root>/voice/stt` sublayout).
- Absolute values only; relative values are rejected — never resolved
  against the process CWD.
- Nothing supersedes it. It is the setting the installer (Phase 6) and
  downloader (Phase 7) rely on.

## `ai.models_dir` — LEGACY COMPATIBILITY (retained)

The pre-Phase-3 key. It is **intentionally alive** and must NOT be
removed as part of Phase 9:

- Older settings.json files carry only this key; the runtime still
  resolves their model root through it
  (`core.paths.get_models_root` precedence 2). When the value names the
  `llm` category dir (the historical meaning), the root is its PARENT,
  keeping existing trees (`<root>/llm/...`) working.
- `set_models_root()` **mirrors** every canonical change into this key
  as `<root>/llm` so readers from any era stay consistent
  (`core/paths.py`, `set_models_root`).
- Startup reads it as the primary scan dir only when absolute
  (`app/application.py`); runtime re-pointing listens for it via the
  legacy `CONFIG_CHANGED` branch in `MainWindow`.

## `ai.model_search_paths` — LEGACY/ADVISORY extra search roots (retained)

A list of additional absolute directories that participate in model
**discovery**. It is a search hint, never a storage location and never
a replacement for `models.storage_root`.

- Read **once at application startup**:
  `app.application` passes it to `ModelManager(search_paths=...)`,
  which scans it *in addition to* the canonical root's llm category dir
  (deduplicated; results deduplicated by resolved path in
  `ai.models.discovery.discover_all_models`).
- Hand-edited absolute entries keep working — that is its purpose.
- `set_models_root()` rewrites the list to `[<root>/llm]` so it stays
  coherent with the canonical root.
- **Startup-only:** runtime root changes re-point the manager via
  `set_models_dir()` (which replaces the search-path list in-session)
  without rewriting this key; a value edited in settings.json applies
  on the next launch.

## Contract tests

- Canonical resolution + mirror writes + legacy migration:
  `tests/test_phase3_models_root.py`
- Runtime propagation (canonical and legacy keys):
  `tests/test_phase8_integration.py`
- Legacy-parent resolution: `tests/test_phase7_downloader.py`
- Multi-root discovery (canonical + advisory roots):
  `tests/test_phase9_multi_root_search.py`
