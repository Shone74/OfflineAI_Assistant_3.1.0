# MASTER PLAN — posle checkpointa 3f5c532

> Radni dokument za praćenje napretka. Ažurira se posle svakog završenog taska.
> NE komituje se bez odobrenja (tracking artefakt, nije projektna dokumentacija).

## Baseline (poslednja verifikacija)

| Stavka | Vrednost |
|---|---|
| HEAD | `be0f9c9` — C3: Legacy cleanup — Pokreni.bat portable Python, docs updated |
| Tests | 439 passed, 3 skipped |
| Working tree | clean (MASTER_PLAN.md je namerno nekomitovan tracking artefakt) |

## Istorija završenih taskova (pre ovog plana)

| Commit | Task | Testovi |
|---|---|---|
| `0913a6c` | Baseline checkpoint (Online API + Vision + EN lokalizacija) | 199 |
| `9ddd423` | Fix ONCE automation task re-execution | 211 |
| `3c0336d` | Move automation task execution off GUI thread | 223 |
| `180badf` | Make FAISS index updates incremental on add | 233 |
| `8371959` | Add security fail-closed regression tests | 255 |
| `3f5c532` | Move Run Now execution off GUI thread via dispatcher | 267 |

---

## STATUS TABELA

| # | Task | Prioritet | Status | Commit | Testovi |
|---|---|---|---|---|---|
| 1 | A1 — MainWindow sync generation → async worker | 🔴 | ✅ DONE | `d5df07a` | 276 |
| 2 | A2 — Cancel preserves partial response | 🟠 | ✅ DONE | `c6a3631` | 281 |
| 3 | B1 — LLMReasoner string matching | 🟡 | ✅ DONE | `c0782af` | 323 |
| 4 | B2 — Stub embedding UI warning | 🟡 | ✅ DONE | `ed48f0a` | 327 |
| 5 | C1 — Documentation refresh | 🔵 | ✅ DONE | `66b9a05` | 335 |
| 6 | C2 — Dependency reconciliation | 🔵 | ✅ DONE | `90fec66` | 335 |
| 7 | C3 — Legacy/duplicate cleanup | 🔵 | ✅ DONE | `392f189` + `be0f9c9` | 332 |
| 8 | D1 — plugins/project/installer tests | 🔵 | ✅ DONE | `new commits` | 439 |
| 9 | D2 — baseline smoke/CI independence | 🔵 | ✅ DONE | `new commit` | 439 |
| 10 | E1 — God-class decomposition | 🔵 | 🔧 IN PROGRESS | — | 439 |

Status legenda: ⬜ PENDING · 🔧 IN PROGRESS · ✅ DONE (commit + zeleni testovi) · ⏸ BLOCKED

---

## FAZA A — Preostali funkcionalni problemi

### A1 — MainWindow sync generation / GUI blocking 🔴 (SLEDEĆI TASK)

Problem: `ui/main_window.py::_start_generation_sync` — LLM generacija na GUI thread-u;
busy-wait petlja oko line 614-615; legacy/skrivena MainWindow putanja za slash-komande
i tool heuristiku. Primarna AppShell+ChatVoiceCoordinator putanja već koristi worker.

Cilj:
- ukloniti stvarni GUI blocking
- iskoristiti postojeći GenerationWorker/QThread obrazac
- ukloniti busy-wait
- očuvati ponašanje slash-komandi/tool heuristike
- BEZ trećeg paralelnog execution sistema

Tehnički detalj (iz security audita): `_request_permission` već koristi
`QMetaObject.invokeMethod(BlockingQueuedConnection)` — dizajniran za worker thread,
dakle permission dijalog uz async worker je arhitektonski omogućen.

Test zahtevi: worker-thread identitet, non-blocking probe, slash-komande i dalje rade,
native tool path sa permission radi, ONCE/automation netaknuti, 267 postojećih zeleno.

### A2 — Cancel mora sačuvati partial response 🟠

Problem: `ChatVoiceCoordinator._on_generation_cancelled` +
`MainWindow._on_worker_cancelled` — partial response nestaje nakon cancel-a.

Cilj:
- ako je generacija proizvela tekst, tekst ostaje u conversation/history
- cancellation ostaje cancellation (ne predstavlja se kao normalan završen odgovor)
- ne sme se duplirati response
- OBE putanje (Coordinator + MainWindow) moraju biti pokrivene testom

---

## FAZA B — Mali correctness/quality problemi

### B1 — LLMReasoner string-match 🟡

`agent/reasoning.py:66` — `if "no" in answer.strip().lower()[:12]` hvata "know",
"nothing" itd. Robusnija detekcija + testovi pozitivnih/negativnih slučajeva, bez
menjanja fallback semantike. (B1 i B2 su međusobno nezavisni → mogu paralelno.)

### B2 — Stub embedding UI warning 🟡

Backend ima `get_embedding_model_info()` + `is_stub`. Knowledge UI treba jasno
upozorenje da semantic search nije aktivan kad je stub aktivan. Ne menjati backend,
ne uvoditi auto-download modela.

---

## FAZA C — Documentation / dependency / hygiene 🔵

### C1 — Documentation refresh
README kaže "92 tests" (stvarno 267+), FEATURES.md 172, current_status.md zastareo.
Jedan source of truth za test count; ukloniti netačne reference; bez marketinških tvrdnji.
(Sub-agent friendly: čist tekst posao, nezavistan od koda.)

### C2 — Dependencies
`document_loader.py` koristi pypdf/docx — nedeklarisani u pyproject. Potvrditi stvarne
importe, uskladiti pyproject, dodati test protiv dependency drift-a.

### C3 — Legacy/duplicate cleanup
**COMPLETED:**
- `main_original.py` — KEPT for `--test-runtime` (documented in README, START_HERE, docs)
- `welcome_dialog.py` vs `welcome_wizard.py` — BOTH ACTIVE, different use cases:
  - `welcome_dialog.py`: simple welcome when model IS available
  - `welcome_wizard.py`: full 7-step onboarding when NO model available
- `Pokreni.bat` — fixed: portable Python 3.11 resolution (.venv → py -3.11 → hardcoded fallback)
- Folder `Izgled Aplikaccije` → `design_previews` (typo fix + ASCII-safe)
- README/docs: all references updated to `design_previews/`
- Added `.gitkeep` to empty folders: `assets/`, `config/`, `data/`, `knowledge_docs/`

---

## FAZA D — Test coverage 🔵

### D1 — plugins / project / installer
**COMPLETED:**
- Added `tests/test_plugins.py` (36 tests): discovery, loader, manager lifecycle, wiring, config persistence, command registry, builtin commands, edge cases
- Added `tests/test_project.py` (47 tests): WorkspaceManager/ProjectManager CRUD, profile overrides, workspace path validation, file listing, cache behavior, event publishing
- Added `tests/test_installer.py` (24 tests): PackageSpec/InnoSetupScript generation, hardware detection & model recommendation, downloader, InstallConfig
- All tests pass in OFFLINE_AI_TEST_MODE (headless)
- Total test count: 439 (was 332) — +107 new regression tests

### D2 — baseline smoke/CI independence
**COMPLETED:**
- Added `@requires_models` pytest marker to model-dependent tests in `test_baseline_smoke.py`
- Tests now SKIP (not FAIL) when GGUF models are unavailable
- CI can run full test suite without local model files
- Local development (with models present) still runs all model tests
- Modified tests: `test_discovery_finds_project_models`, `test_discovered_model_capabilities`, `test_model_manager_rescan_lists_models`, `test_gguf_metadata_reader_on_project_model`
- Adjusted `test_discovery_all_sources_no_crash` to not assert model count when models unavailable

---

## FAZA E — Architecture / maintainability 🔵

### E1 — God classes (POSLEDNJE)
`ui/settings.py` ~2664, `core/assistant.py` ~2246, `ui/welcome_wizard.py` ~1704,
`ui/main_window.py` ~1490. Mapirati odgovornosti → prirodne granice → mali extraction
plan → jedan extraction po tasku → testovi pre/posle → bez promene ponašanja.
MainWindow se NE dira dok A1 nije završen.

**E1a — ui/settings: Profile tabs extraction** ✅ DONE
- Extracted 6 profile tab classes (ProfileTab, CommunicationTab, PersonalityTab, ExpertiseTab, BehaviorTab, BoundariesTab) → `ui/settings/profile_tabs.py`
- Created `ui/settings/` package with `__init__.py` for backwards compatibility
- SettingsDialog line count reduced from ~3113 to ~2913
- All 439 tests pass

**E1b — ui/settings: Model & Storage tabs extraction** ✅ DONE
- Extracted ModelStatusTab (~100 lines) and StorageTab (~20 lines) → `ui/settings/model_storage_tabs.py`
- SettingsDialog line count reduced from ~2913 to ~2793
- All 439 tests pass

**E1c — ui/settings: Logging & Language tabs extraction** ✅ DONE
- Extracted LoggingTab (~50 lines) and LanguageTab (~20 lines) → `ui/settings/logging_language_tabs.py`
- SettingsDialog line count reduced from ~2793 to ~2720
- All 439 tests pass

**E1d — ui/settings: Plugin tab extraction** ✅ DONE
- Extracted PluginTab (~120 lines) → `ui/settings/plugin_tab.py`
- SettingsDialog line count reduced from ~2720 to ~2600
- All 439 tests pass

**E1e — ui/settings: Generation & Memory tabs extraction** ✅ DONE
- Extracted GenerationSettingsTab (~180 lines) and MemorySettingsTab (~190 lines) → `ui/settings/generation_memory_tabs.py`
- SettingsDialog line count reduced from ~2600 to ~2276 (27% total reduction)
- All 439 tests pass

**E1f — ui/settings: Filesystem security tab extraction** ✅ DONE
- Extracted FilesystemSecurityTab (~300 lines) → `ui/settings/filesystem_tab.py`
- SettingsDialog line count reduced from ~2276 to ~2004 (36% total reduction)
- All 439 tests pass

**E1g — ui/settings: Audio settings tab extraction** ✅ DONE
- Extracted _AudioTestWorker (~40 lines) and AudioSettingsTab (~450 lines) → `ui/settings/audio_tab.py`
- SettingsDialog line count reduced from ~2004 to ~1574 (49% total reduction)
- All 439 tests pass

---

## KONTRAINT I TOKA RADA (za svaki task)

1. Verifikuj baseline (git status + test suite) pre početka
2. Jedan task = jedan commit, poruke u stilu prethodnih
3. Fokusni testovi pa kompletna suite pre commit-a
4. Ažuriraj ovu tabelu posle svakog taska (status + commit + test count)
5. Ne menjaj ništa van scope-a taska
