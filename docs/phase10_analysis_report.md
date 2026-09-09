# Phase 10 Analysis Report

> Generated: 2026-09-09  
> Scope: Assess post-Phase-9 repository state and identify the highest-value remaining work for Phase 10.

---

## 1. Executive Summary

Phase 9 is **complete and signed off**. The repository is in a strong, stable state:

- **773 tests pass**, 6 skipped, **0 failures** (779 collected).
- **Ruff is clean** on all Phase 7–9 source files.
- **Only 1 TODO** in the entire codebase (a design-time note in `docs/pages_map.md`, not a blocker).
- Phases 1–9 are complete (Faza 1–8 committed in git history; Phase 9 is HEAD `be0f9c9`).

The working tree contains **substantial pre-existing uncommitted changes** (30 modified files, 1 deleted `ui/settings.py`, ~24 untracked files) — these are NOT Phase 10 work and should not be assumed as such.

**Primary recommendation for Phase 10**: **Frozen-build end-to-end validation & application lifecycle coverage.** The PyInstaller frozen build (`offline_ai_frozen.spec`, `installer/OfflineAI.iss`) has no automated test, and the new `application_final.py` entry point (AppShell bootstrap) has no lifecycle test. These are the highest-risk, least-tested surfaces for the end user.

---

## 2. Repository State

### Git state
| Field | Value |
|-------|-------|
| HEAD | `be0f9c9` — "C3: Legacy cleanup — Pokreni.bat portable Python, docs updated" |
| Branch | Unnamed (detached HEAD or feature branch) |
| Working tree | **Dirty**: 30 modified, 1 deleted, ~24 untracked |

### Working tree summary (pre-existing, not Phase 10)

**Deleted file:**
- `ui/settings.py` — the ~2664-line monolithic settings dialog, replaced by the `ui/settings/` package (Extraction E1a–E1g, all DONE per `MASTER_PLAN.md`).

**Modified files (20 key):**
| File | Diff | Nature |
|------|------|--------|
| `core/paths.py` | 506± | Path architecture: deterministic, CWD-independent resolution |
| `installer/packager.py` | 614± | PyInstaller + Inno Setup packaging with frozen smoke-test support |
| `installer/downloader.py` | 680± | Model downloader with strict size/SHA-256 validation |
| `ai/models/model_manager.py` | — | Phase 3 default dir + GPU mode passthrough |
| `ui/main_window.py` | 62± | `models.storage_root` canonical key handling |
| `tools/file_security.py` | 220± | Symlink/junction blocking, CWD-independent validation |
| `app/application.py` | 75± | Background model-load worker, AppShell bootstrap prep |
| `app/application_final.py` | 176 (new) | Standalone final application bootstrap (AppShell entry point) |
| `ui/chat_voice_coordinator.py` | 4± | CWD-independent settings path via `SETTINGS_FILE` |
| `memory/embeddings.py` | 46± | Embedding model loading |
| `knowledge/knowledge_base.py` | 69± | RAG knowledge base |

**Untracked new files:**
- **Source:** `ai/hardware.py`, `ai/models/download_service.py`, `ai/models/gpu_runtime.py`, `ai/models/recommendation.py`, `installer/catalog.py`, `offline_ai_frozen.spec`, `installer/OfflineAI.iss`
- **Docs:** `docs/phase7_hardware_downloader.md`, `docs/phase8_integration.md`, `docs/phase9_model_storage_keys.md`
- **Tests:** `tests/test_phase1_paths.py` … `tests/test_phase9_multi_root_search.py` (9 phase test suites + `test_plugins.py`, `test_project.py`, `test_installer.py`)
- **Other:** `MASTER_PLAN.md` (tracking artifact), `ui/settings/` (package), `app_version_info.txt`

### Verification commands
- **Tests:** `python -m pytest tests/ -q` → 773 passed, 6 skipped, 0 failures (94s)
- **Lint:** `ruff check ai/ core/ tools/ installer/ ui/ app/ tests/ voice/ knowledge/ memory/ security/ project/ plugins/` → 0 issues
- **Test collection:** `python -m pytest tests/ --co -q` → 779 tests collected

---

## 3. Phase Completion Status

| Phase | Status | Git evidence |
|-------|--------|-------------|
| Faza 1 | ✅ Done | `01f75be` Faza 1: launcher stabilization |
| Faza 2 | ✅ Done | `d4e1d53` Faza 2: design system |
| Faza 3 | ✅ Done | `9c9bc5e`–`caf8600` Faza 3: AppShell redesign |
| Faza 4 | ✅ Done | `5096a0e` Faza 4: page migration to design system |
| Faza 5 | ✅ Done | `51788d2` / `244fd70` Faza 5: wizard redesign |
| Faza 6 | ✅ Done | `7b0cb63` Faza 6: model integration, GPU offload |
| Faza 7 | ✅ Done | `51788d2` Faza 7: wake word + automatic listening |
| Faza 8 | ✅ Done | `5e10c9b` Faza 8: README, lint, E2E final |
| **Phase 9** | ✅ Done & signed off | HEAD `be0f9c9`; working-tree files: `docs/phase9_model_storage_keys.md`, `tests/test_phase9_catalog_integrity.py`, `tests/test_phase9_multi_root_search.py`, `installer/catalog.py` |

**Phase 9 tasks (per task description):**
1. ✅ Catalog integrity curation — `installer/catalog.py` with verified SHA-256 for STT, approximate for LLM/embedding (auth-gated upstream)
2. ✅ Settings lint cleanup — extraction E1a–E1g complete, `ui/settings.py` → `ui/settings/` package
3. ✅ Legacy model-storage key documentation + multi-root regression — `tests/test_phase9_multi_root_search.py` (7 tests), `tests/test_phase9_catalog_integrity.py` (38 tests)

---

## 4. Architecture Overview

### Entry point
```
run.py (173 lines)
  → frozen bootstrap: CUDA DLL registration (optional)
  → OFFLINE_AI_SMOKE_TEST=1 → _frozen_smoke_test() (headless frozen validation)
  → else: app.application_final.main()
      → ApplicationManager.start()  (background model-load worker)
      → AppShell (primary window, replaces legacy MainWindow)
      → pages: Chat, Memory, Knowledge, Models, Capabilities, Projects,
               Agents, Tools, Voice, Automation, Workflow, Settings
      → aboutToQuit → coordinator.shutdown() → manager.stop() (idempotent)
```

### Key subsystems
| Layer | Module | Notes |
|-------|--------|-------|
| Paths | `core/paths.py` | Deterministic, CWD-independent. `user_data_root()`, `get_models_root()`, `get_model_category_dir()`, `resource_root()` |
| Config | `core/config_manager.py` | `ConfigManager` with `models.storage_root` (canonical) + `ai.models_dir` (legacy mirror) |
| Models | `ai/models/model_manager.py` | Multi-root search, GPU mode passthrough, `set_models_dir()` |
| Models | `ai/models/gpu_runtime.py` (new) | Centralized GPU detection. `decide_gpu_layers()`, `detect_gpu_capabilities()`, `apply_cuda_dll_discovery()` |
| Models | `ai/models/discovery.py` | Filesystem discovery (no manifest). Part files & link-safe. |
| Catalog | `installer/catalog.py` (new) | Curated download metadata. `is_fully_curated`, `is_installed()`, `find_model()`, `get_catalog()` |
| Download | `installer/downloader.py` | Strict size + SHA-256 validation. Scoped to install_dir. Part-file cleanup on mismatch. |
| Security | `tools/file_security.py` | Symlink/junction blocking, absolute-root enforcement, CWD-independent validation |
| Security | `security/auditor.py` | Fail-closed policy |
| UI | `ui/app_shell.py` | Reference AppShell, routes/pages navigator |
| UI | `ui/settings/` (new package) | Extracted from monolithic `ui/settings.py` (E1a–E1g) |
| Voice | `voice/` | STT/TTS/ASR, wake-word (Phase 7) |
| Knowledge | `knowledge/knowledge_base.py`, `rag_pipeline.py` | RAG pipeline, stub embedding fallback |
| Memory | `memory/embeddings.py`, `memory/memory_manager.py` | Embedding model loading |
| Installer | `installer/packager.py`, `installer/config.py`, `installer/OfflineAI.iss` | PyInstaller spec + Inno Setup script generation |
| Frozen | `offline_ai_frozen.spec` | PyInstaller spec (new) |

### Threading model
- `_StartupModelLoadWorker(QThread)` — background model loading at startup
- Background workers for: MainWindow generation, "Run Now" execution, automation task execution
- GUI updates via Qt signals (main thread only)

---

## 5. Test Coverage Analysis

### Test suites (779 tests, all passing)

| File | Tests | Phase | Coverage |
|------|-------|-------|----------|
| `test_phase1_paths.py` | ~? | Phase 1 | Path architecture, CWD-independence |
| `test_phase2_security.py` | ~? | Phase 2 | File security, fail-closed, link/junction blocking |
| `test_phase3_models_root.py` | ~? | Phase 3 | Models root, category dirs, storage root |
| `test_phase4_gpu_runtime.py` | ~? | Phase 4 | GPU detection, layer decisions, CUDA DLL discovery |
| `test_phase5_packaging.py` | ~? | Phase 5 | PyInstaller spec, Inno Setup script generation |
| `test_phase6_installer.py` | ~? | Phase 6 | Installer config, hardware detection, model recommendation |
| `test_phase7_downloader.py` | ~? | Phase 7 | Downloader, progress, strict validation, part-file cleanup |
| `test_phase8_integration.py` | 43 | Phase 8 | End-to-end integration: paths, discovery, security, GPU, lifecycle |
| `test_phase9_catalog_integrity.py` | 38 | Phase 9 | Catalog metadata, SHA-256 verification, install_dir, download e2e |
| `test_phase9_multi_root_search.py` | 7 | Phase 9 | Multi-root model discovery, search path semantics |
| `test_plugins.py` | 36 | Phase D1 | Plugin discovery, loader, manager lifecycle |
| `test_project.py` | 47 | Phase D1 | Project/workspace CRUD, profile overrides |
| `test_installer.py` | 24 | Phase D1 | PackageSpec, InstallConfig, hardware detection |
| `test_baseline_smoke.py` | ? | Phase D2 | `@requires_models` marker, event bus, engine stubs |
| `test_cancel_preserves.py` | ? | Threading | Cancelled response preserves partial text |
| `test_pages_migration.py` | 8 | Phase 4 | Page design elements, tokens, imports |
| `test_model_integration.py` | 4 | Phase 6 | Model discovery, capabilities, GPU offload |
| `test_api_engine.py` | ~60 | Faza 8 | Online API engine, provider routing, model presets |
| `test_wizard_redesign.py` | ~? | Phase 5 | Wizard steps, installation simulation |

### Test infrastructure
- `tests/conftest.py` — sets `OFFLINE_AI_TEST_MODE=1` and `QT_QPA_PLATFORM=offscreen` before any import
- `pytest.mark.requires_models` — skips model-dependent tests when GGUF files unavailable
- Tests run headless (no GPU/model files needed in CI)

### Coverage gaps identified

#### Gap 1: No frozen-build integration test
- `offline_ai_frozen.spec` is **new and untracked** — no test validates PyInstaller build output
- `run.py:_frozen_smoke_test()` exists (lines 69–153) but **no test exercises it**
- `installer/OfflineAI.iss` (Inno Setup script) is **new** — no test verifies installer package correctness
- `test_phase5_packaging.py` tests spec/script *generation* but not the *built* artifact
- **Risk**: A broken frozen build (missing DLL, wrong path resolution, missing resource) reaches end users with no CI detection

#### Gap 2: No application lifecycle test
- `app/application_final.py` (176 lines) is the **actual entry point** (`run.py:168` → `application_final.main`)
- It wires: `ApplicationManager.start()` → AppShell.show() → `aboutToQuit` → `coordinator.shutdown()` + `manager.stop()`
- The `_StartupModelLoadWorker(QThread)` thread lifecycle is **untested** — no test verifies thread shutdown on quit
- `test_phase8_integration.py` covers subsystem wiring but **not** the full `main()` → `app.exec()` → quit lifecycle
- **Risk**: Race condition on shutdown, leaked thread, incomplete cleanup of engine/memory/model_manager/database

#### Gap 3: No performance benchmarks
- No `test_phase*_performance.py` or any benchmarking tests exist anywhere
- GPU offload decisions (`gpu_runtime.py`) are unit-tested but not benchmarked for actual layer count optimization
- Model load time, first-response latency, and memory footprint are unmeasured
- **Risk**: No baseline to detect performance regressions

#### Gap 4: Download/installer error recovery (partial coverage)
- `test_phase9_catalog_integrity.py` covers: SHA mismatch, part-file cleanup, strict size validation
- **Missing**: network timeout/interruption mid-download, disk-full during write, resume capability, concurrent download attempts, partial companion file cleanup
- `test_phase7_downloader.py` exists but may not cover interruption scenarios
- **Risk**: Corrupted/partial downloads on flaky networks, no resume support

#### Gap 5: No end-to-end user journey test
- No test covers: first-run wizard → model download → model load → first chat message → voice activation → knowledge indexing → settings change → graceful shutdown
- Phase 8 integration tests cover subsystems in isolation; no test exercises the complete user flow through `application_final.py`
- **Risk**: Integration regressions between components go undetected

---

## 6. Phase 10 Candidate Priorities

### Priority 1: Frozen-build end-to-end validation (Highest)
**Why:** The frozen build is the primary distribution mechanism. `offline_ai_frozen.spec` + `installer/OfflineAI.iss` are untracked/new. The `_frozen_smoke_test()` in `run.py` validates path/config/resource resolution in frozen mode but is never invoked by tests. A broken frozen build is a silent, user-facing failure with no CI signal.

**Suggested work:**
- Add `tests/test_phase10_frozen_build.py` that invokes `run._frozen_smoke_test()` in a subprocess simulating `sys.frozen=True`
- Add a PyInstaller build integration test (or CI step) that builds the spec and runs the smoke test binary
- Add `installer/OfflineAI.iss` validation: verify all bundled paths referenced in the ISS exist

### Priority 2: Application lifecycle & shutdown safety
**Why:** `application_final.py` is the real entry point but has no lifecycle test. The `_StartupModelLoadWorker` thread and the `_on_about_to_quit` handler (which calls `manager.stop()`) are untested. Shutdown race conditions or thread leaks would corrupt user data on exit.

**Suggested work:**
- Add `tests/test_application_lifecycle.py`
- Test: `ApplicationManager.start()` → AppShell creation → `aboutToQuit` → `manager.stop()` → verify no leaked threads, all resources released
- Test: model-load worker failure → app starts without crashing, model status reflects failure
- Test: `manager.stop()` idempotency (second call is no-op)

### Priority 3: Download/installer error recovery
**Why:** The downloader has strict validation (SHA-256, size) but interruption/resume and disk-full scenarios are not tested. Users on flaky networks could get stuck with corrupted downloads.

**Suggested work:**
- Extend `test_phase7_downloader.py` with interruption/resume tests
- Add disk-full simulation (partial write + cleanup)
- Verify companion-file atomicity (all-or-nothing download)

### Priority 4: Performance baselines
**Why:** No performance benchmarks exist. GPU layer decisions, model load time, and inference latency are unmeasured. Without baselines, performance regressions go undetected.

**Suggested work:**
- Add `tests/test_phase10_performance.py` (non-blocking, CI-skippable)
- Record: model load time, first-token latency, memory usage
- GPU layer count optimization verification

---

## 7. Recommended Phase 10 Direction

**Primary focus: Frozen-build reliability & application lifecycle**

1. **Frozen build validation** (Priority 1) — the most user-impactful risk with zero test coverage
2. **Application lifecycle test** (Priority 2) — protects the new `application_final.py` AppShell entry point and its thread management
3. **Download error recovery** (Priority 3) — hardens the installer path for real-world network conditions

These three areas address the **last major untested surfaces** in the system. Together they would push the test count from 779 → ~810+ and provide CI coverage for the distribution and runtime reliability of the final application.

**Secondary/nice-to-have:** Performance baselines (Priority 4) can be added as a lighter follow-up if time permits.

---

*End of Phase 10 Analysis Report*
