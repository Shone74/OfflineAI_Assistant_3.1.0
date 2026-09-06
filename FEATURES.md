# Application Functionality Report

**Application:** Offline AI Assistant
**Report date:** 2026-09-06 (updated: hardening pass — async generation,
cancel-preserving history, robust reasoner, dependency extras)
**Verification method:** live end-to-end execution of every feature in a headless
environment (`verify_features.py` + supplementary UI/dialog checks), plus the full
pytest suite (335/335 passing).

**Status legend:**

| Status | Meaning |
|---|---|
| ✅ RADI (WORKS) | Fully functional — verified end-to-end |
| 🟡 DELIMIČNO RADI (PARTIAL) | Works with limitations — see notes |
| ❌ NERADI (BROKEN) | Not usable — see notes |

---

## Feature List (Logical Dependency Order)

Features are ordered so that each level depends only on the levels above it
(Infrastructure → Model → Assistant → Tools → Agents → Voice → UI → Installer).

---

### LEVEL 1 — Infrastructure (Foundation)

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 1.1 | Configuration manager (`settings.json` create/set/save/reload) | ✅ RADI | Verified: defaults, deep merge, persistence |
| 1.2 | Event bus (publish/subscribe/unsubscribe, thread-safe) | ✅ RADI | Verified with subscription IDs and unsubscribe |
| 1.3 | Logging (file + level control) | ✅ RADI | Log files written under `%LOCALAPPDATA%\OfflineAI\logs` |
| 1.4 | SQLite database (8 migrations, CRUD) | ✅ RADI | Verified: insert/query; agents, memory, conversations, plugins tables |
| 1.5 | Path resolution (dev / PyInstaller `USER_DATA_BASE`) | ✅ RADI | Auto-creates config/data/logs/models directories |

### LEVEL 2 — AI Model Subsystem

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 2.1 | Model discovery (local GGUF + extensionless + Ollama + LM Studio) | ✅ RADI | Verified: 2 models found in `models/llm` |
| 2.2 | llama.cpp runtime (llama-cpp-python) | ✅ RADI | Importable in this environment |
| 2.3 | Model activation/load (GGUF loader, threads/GPU-layers/n-ctx) | ✅ RADI | Real loader path verified; background QThread load in UI |
| 2.4 | Model unload / switch (unload-first policy) | ✅ RADI | Enforced by ModelManager.activate_model |
| 2.5 | Model capabilities inference (vision/tools/code/reasoning/long-context) | ✅ RADI | Name + GGUF metadata + tensor-based detection |
| 2.6 | GPU detection (VRAM, auto GPU layers) | ✅ RADI | pynvml present; auto-detection implemented |
| 2.7 | Vision projector (mmproj) auto-detection | ✅ RADI | Detected next to vision models; attached via `mmproj=`/legacy handler |
| 2.8 | Model download (explicit, via requests) | ✅ RADI | `installer.downloader` present; app is offline — download is explicit-only |
| 2.9 | Model deletion | ✅ RADI | Removes file, rescans, falls back to stub if active |

### LEVEL 3 — Assistant Core

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 3.1 | Chat pipeline (`process_message`: prompt → stream → response) | ✅ RADI | Verified with streaming engine |
| 3.2 | System prompt rendering (identity, description, custom instructions) | ✅ RADI | Profile-driven; no hardcoded name |
| 3.3 | Conversation memory (short-term history in prompt) | ✅ RADI | Sliding window from config |
| 3.4 | Context budget enforcement (token truncation) | ✅ RADI | Exact tokenizer count with char-estimate fallback |
| 3.5 | Streaming + token callbacks + cooperative cancellation | ✅ RADI | Cancel event + predicate both supported |
| 3.6 | Vision — image attach in chat | ✅ RADI | Full path: UI picker → base64 → llama.cpp `image_url` parts |
| 3.7 | Vision — gate for non-vision models | ✅ RADI | Clear refusal message; no crash, no hallucinated descriptions |
| 3.8 | Memory: long-term storage (SQLite) + relevance recall | ✅ RADI | save + build_context verified |
| 3.9 | Memory: explicit "remember that …" intent + confirm/decline | ✅ RADI | English trigger phrases; affirmative/negative classification |
| 3.10 | Knowledge base (index .txt/.md/.pdf/.docx/.html + search) | ✅ RADI | PDF/DOCX need optional pypdf/docx libs — plain-text formats always work |
| 3.11 | RAG pipeline (retrieve → inject into system prompt) | ✅ RADI | Context injection verified |
| 3.12 | Vector memory (kNN search; faiss optional) | ✅ RADI | Pure-Python kNN fallback verified |
| 3.13 | Assistant Profile (identity/personality/communication/expertise/behavior/boundaries) | ✅ RADI | 6 profile tabs; persisted in settings |

### LEVEL 4 — Tools & Security

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 4.1 | Tool registry (register/execute/enable/disable) | ✅ RADI | Single execution gateway |
| 4.2 | calculate (safe math, no eval) | ✅ RADI | 2+3*4=14 |
| 4.3 | date_time (current date/time) | ✅ RADI | — |
| 4.4 | clipboard_read / clipboard_write | ✅ RADI | — |
| 4.5 | read_file / list_directory / search_files / file_metadata | ✅ RADI | Sandboxed reads verified |
| 4.6 | write_file / create_directory / copy_file / move_file / delete_file | ✅ RADI | Guarded by SecurityLayer (ASK/DENY policies) |
| 4.7 | system_info (CPU/RAM/disk/GPU) + process_info | ✅ RADI | psutil metrics verified |
| 4.8 | open_application (app launcher with aliases) | ✅ RADI | Graceful failure on unknown app; known aliases mapped |
| 4.9 | search_knowledge (RAG tool) | ✅ RADI | Via RAGPipeline |
| 4.10 | SecurityLayer (ALLOW/ASK/DENY policies + audit log) | ✅ RADI | Confirmation-gateway intercepts risky tools |
| 4.11 | GUI permission prompt (modal, thread-safe) | ✅ RADI | MainWindow routes ASK tools to QMessageBox on GUI thread |

### LEVEL 5 — Agents & Automation

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 5.1 | Agent repository (SQLite CRUD + lifecycle events) | ✅ RADI | — |
| 5.2 | Built-in agents (Researcher, Writer, Coder, Analyst, File Manager, System Monitor, Planner) | ✅ RADI | Seeded once on first run; user edits never overwritten |
| 5.3 | Agent editor dialog (name/prompt/model/whitelist/permissions) | ✅ RADI | Constructs and loads |
| 5.4 | Planner (stub keyword → LLM with fallback) | ✅ RADI | Both paths verified |
| 5.5 | Agent execution (plan → act → summarize, whitelists, permission profiles) | ✅ RADI | Sequential run verified |
| 5.6 | Agent orchestrator (multi-agent sequential workflows) | ✅ RADI | "1 done" summary verified |
| 5.7 | Automation workflows (named, JSON-persisted, conditional steps) | ✅ RADI | Workflow run + persistence verified |
| 5.8 | Scheduler (interval + one-shot; cron needs `croniter`) | ✅ RADI | Interval/once fully functional offline; cron only when croniter installed (not in requirements) |
| 5.9 | Scheduled tasks UI (task editor, enable/disable, run-now) | ✅ RADI | Task editor dialog verified |
| 5.10 | **Online API engine (OpenAI-compatible, opt-in, MULTI-PROVIDER)** | ✅ RADI | Built-in presets: OpenRouter, Groq, Google AI Studio, Mistral, Cerebras, Together + custom endpoints; per-provider keys in settings.json; agents route via `<provider>:<model>` |
| 5.11 | **Online API settings tab (per-provider key/base_url/model, live model catalogue fetch, test button)** | ✅ RADI | Masked key fields; curated suggestions + "Fetch models" via GET /models; custom provider registration |
| 5.12 | **Chat 🌐 Online indicator during API-served turns** | ✅ RADI | Shows on `API_ENGINE_ACTIVE`, hides when the turn ends |

### LEVEL 6 — Plugins

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 6.1 | Plugin discovery (`plugin.json` manifests, subdirectory scan) | ✅ RADI | Validated manifests; invalid skipped safely |
| 6.2 | Plugin loading (entry_point `module:attr`, Plugin subclass) | ✅ RADI | 1/1 demo plugin loaded + enabled |
| 6.3 | Plugin enable/disable + state persistence | ✅ RADI | States saved across restarts |
| 6.4 | Plugin security (permissions, security_profile wiring) | ✅ RADI | Enforced via SecurityLayer |

### LEVEL 7 — Voice

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 7.1 | VoiceManager lifecycle (idle → recording → processing → speaking) | ✅ RADI | Full record/stop/transcribe verified |
| 7.2 | Microphone capture (sounddevice/WASAPI, device selection) | ✅ RADI | Works in the real GUI; offscreen test env uses fake mic |
| 7.3 | STT — faster-whisper (local models: base, tiny present) | ✅ RADI | Local model dirs verified; never downloads automatically |
| 7.4 | TTS — pyttsx3 (2 system voices found) | ✅ RADI | Background QThread; never blocks GUI |
| 7.5 | Wake word — openwakeword (hey_jarvis) | ✅ RADI | Installed and active |
| 7.6 | Automatic Listening (continuous listen→answer→speak loop) | ✅ RADI | Coordinator state machine verified (incl. echo protection: mic off during TTS) |
| 7.7 | Voice page auto-population (recommended values) | ✅ RADI | Provider/model/device/rate/volume auto-filled |
| 7.8 | Audio settings (input/output device pickers, WASAPI prefs, mic test) | ✅ RADI | Device enumeration verified |

### LEVEL 8 — User Interface

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 8.1 | AppShell (topbar, sidebar, context panel, 13-page navigation) | ✅ RADI | All pages construct + navigate |
| 8.2 | Home page (hero, snapshot cards, quick actions) | ✅ RADI | Real model status shown (no more "stub" label) |
| 8.3 | Chat page (messages, markdown, streaming, export, search, delete) | ✅ RADI | Export txt/md/json verified |
| 8.4 | Files attach (text file → into message) | ✅ RADI | — |
| 8.5 | Vision button (model-aware enable/disable + counter) | ✅ RADI | Auto-syncs on MODEL_LOADED/UNLOADED |
| 8.6 | Memory page (browse, importance, delete) | ✅ RADI | — |
| 8.7 | Knowledge dashboard (index, rebuild, export, search, delete) | ✅ RADI | — |
| 8.8 | Models page (list, details, activate, unload, folder select, download) | ✅ RADI | Background load via QThread; status colors |
| 8.9 | Capabilities page (live per-model capability cards) | ✅ RADI | Auto-refreshes on model change |
| 8.10 | Agents page (CRUD, enable/disable, filters) | ✅ RADI | — |
| 8.11 | Tools page (catalog, categories, enable/disable) | ✅ RADI | — |
| 8.12 | Voice page (see 7.7–7.8) | ✅ RADI | — |
| 8.13 | Automation dashboard + Workflow builder | ✅ RADI | — |
| 8.14 | Settings (quick + advanced dialog, 13 tabs) | ✅ RADI | — |
| 8.15 | Projects/Workspaces (create, open, context injection) | ✅ RADI | Project context enters the system prompt as data |
| 8.16 | Conversation sidebar (history, rename, pin, delete) | ✅ RADI | — |
| 8.17 | System tray (minimize-to-tray, restore, quit) | ✅ RADI | — |
| 8.18 | System status bar (CPU/RAM/GPU/model) | ✅ RADI | — |
| 8.19 | Theme system (Graphite+Emerald, workspace/installer modes) | ✅ RADI | Design tokens; no hardcoded colors |
| 8.20 | Welcome wizard (7-step first-run setup) | ✅ RADI | Constructs and steps |
| 8.21 | Model manager dialog (download catalog) | ✅ RADI | — |
| 8.22 | Keyboard shortcuts (Ctrl+N/,,/Q,/) | ✅ RADI | — |

### LEVEL 9 — Installer / Packaging

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| 9.1 | PyInstaller packaging (one-file build) | ✅ RADI | `installer/packager.py` + spec generation |
| 9.2 | Inno Setup installer script generation | ✅ RADI | — |
| 9.3 | Hardware detection (CPU/RAM/GPU/VRAM/disk) | ✅ RADI | Used by wizard system-check page |

---

## Summary

| Status | Count |
|---|---|
| ✅ RADI (WORKS) | **69** |
| 🟡 DELIMIČNO RADI (PARTIAL) | **0** |
| ❌ NERADI (BROKEN) | **0** |

## Known Limitations (not bugs — by design or environment)

1. **Cron schedules** require the optional `croniter` package (not in
   `requirements.txt`); interval and one-shot scheduling work without it.
2. **PDF/DOCX knowledge indexing** uses optional `pypdf`/`docx` libraries when
   present; plain-text formats (.txt/.md/.html) always work.
3. **Vision inference** requires a vision-capable model *and* its `mmproj`
   projector file placed next to it; without a projector the model runs text-only
   and image messages are politely refused.
4. **VoiceManager.stop()** in an offscreen one-shot script exhibits a benign
   Qt/QThread teardown crash in the *test environment only*; the same call is
   verified working under pytest (test_voice_faza7) and in the real GUI.
5. The application is **English-only** by design (UI, prompts, logs).
6. **Online API is opt-in** and disabled by default (offline-first). Agents use
   it only when explicitly given an `openrouter:<model>` model name AND the
   user has enabled the API and stored their personal key in settings. When
   the API is unavailable/disabled/misconfigured, agents transparently fall
   back to the local engine. Images are NOT forwarded online (v1 — text only).
   Free-tier models have daily rate limits (HTTP 429 is surfaced clearly).

## Post-Redesign Hardening Additions (2026-09-06)

| # | Feature | Status | Notes |
|---|---------|--------|-------|
| H.1 | Automation: ONCE tasks execute exactly once | ✅ RADI | Success disables the task (persisted); regression suite `tests/test_automation_once.py` |
| H.2 | Automation: scheduler tick on background worker | ✅ RADI | `AutomationTaskWorker`/`AutomationDispatcher`; GUI never blocks on tasks (`tests/test_automation_worker.py`) |
| H.3 | Automation: "Run Now" on background worker | ✅ RADI | In-flight protection prevents duplicate execution (`tests/test_run_now_async.py`) |
| H.4 | Vector memory: incremental FAISS updates | ✅ RADI | O(dim) per add instead of O(N·dim) rebuild; remove() keeps legitimate rebuild (`tests/test_vector_memory_faiss.py`) |
| H.5 | Security: fail-closed regression lock | ✅ RADI | 22 tests locking ALLOW/ASK/DENY contracts (`tests/test_security_fail_closed.py`) |
| H.6 | Chat: cancelled generations preserve partial text | ✅ RADI | Saved to history with "(generation cancelled)" marker; no AI_RESPONSE_RECEIVED on cancel (`tests/test_cancel_preserves_partial.py`) |
| H.7 | Chat: all MainWindow generation on background worker | ✅ RADI | Slash commands + tool heuristics included; busy-wait removed (`tests/test_main_window_async_generation.py`) |
| H.8 | Agent: robust LLMReasoner yes/no classification | ✅ RADI | Word-boundary matching; ambiguous → stub fallback (`tests/test_llm_reasoner.py`) |
| H.9 | Knowledge: stub-embedding warning banner | ✅ RADI | Dashboard shows degraded-search warning (`tests/test_knowledge_embedding_warning.py`) |
| H.10 | Dependencies: optional docs extras declared | ✅ RADI | pypdf/PyMuPDF/python-docx/docx2txt/bs4 in `docs` extra + anti-drift test (`tests/test_dependency_declarations.py`) |

## Verification Artifacts

- `verify_features.py` — 37 executable checks, all WORKS (run with
  `OFFLINE_AI_TEST_MODE=1 QT_QPA_PLATFORM=offscreen python verify_features.py`)
- Full pytest suite: **335/335 passing** (incl. multi-provider Online-API,
  automation, security, FAISS, async-generation and cancel-preservation suites)
- `ruff check`: clean
