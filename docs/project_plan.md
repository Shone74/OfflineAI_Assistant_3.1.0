# Project Plan — Offline AI Assistant Redesign

**Plan version:** 1.0
**Date created:** 2026-09-04
**Goal:** Redesign the application according to the reference design from `Izgled Aplikaccije/` with **zero functional regression** — everything that works today must continue to work across the entire application.

---

## 0. References

| What | Where |
|---|---|
| Design previews (HTML/Python) | `Izgled Aplikaccije/` — 9 files |
| Main workspace design (PySide6) | `Izgled Aplikaccije/assistant_workspace_preview.py` |
| Official theme spec | `Izgled Aplikaccije/official_theme_preview.py` |
| Design system report | `docs/design_system.md` |
| Models report | `docs/models_report.md` |
| Current status | `docs/current_status.md` |

---

## 1. Plan phases (step map)

Each phase consists of steps. A step is complete only when it is verified (see §3). Status is updated in `docs/current_status.md` after every successfully completed step.

---

### PHASE 0 — Preparation and safety net (makes regression impossible)

| # | Step | Details | Verification |
|---|---|---|---|
| 0.1 | Set up git repository | `git init`, initial commit of the whole project (without `__pycache__`, `.pytest_cache`, `models/llm/*.gguf` — add `.gitignore`). Each phase = branching/sub-branching with commits per step. | `git log` shows the initial state |
| 0.2 | Install dependencies in the Python 3.11 env | `scipy`, `nvidia-ml-py3` (missing from the 3.11 pip list); pytest+pytest-qt exist. `llama-cpp-python 0.3.35` already installed. | `pip check` clean; `python -c "import llama_cpp, PySide6, scipy"` |
| 0.3 | Baseline test suite — capture the "golden state" | Write a regression smoke suite: headless run (`QT_QPA_PLATFORM=offscreen`, `OFFLINE_AI_TEST_MODE=1`) + the existing 9 tests + new smoke tests for Assistant, ModelManager, memory, RAG, tools (stub engine). Save the baseline output to `docs/baseline/`. | All baseline tests pass; baseline file exists |
| 0.4 | Verify the `NameError` bug in the launcher | Document the exact behavior of `run.py` → `application_final.main()` (`navigator` is not in scope). The fix is in 1.1. | Error reproduction recorded in the status |
| 0.5 | Review `settings.json` settings | `models_dir` currently `E:/models`, `model_search_paths` only AppData. Align with the new layout (see models_report §3). | Settings valid, models are discovered |

---

### PHASE 1 — Launcher stabilization and removal of critical bugs

| # | Step | Details | Verification |
|---|---|---|---|
| 1.1 | Fix `application_final.py` | `navigator` was defined locally in `main()` but used in `_build_pages()` (lines 43, 50, 51) → NameError. Refactor: `_build_pages(manager, navigator)`. | `run.py` launches the application without exceptions |
| 1.2 | Remove the double-boot pattern | `manager.start()` creates and shows the MainWindow, which the final bootstrap then immediately closes. Rework the bootstrap so the MainWindow is NOT shown when AppShell is active (parameter show_window=False or a new bootstrap path without the old window). | Only one window is visible at startup; no flickering |
| 1.3 | Unify the entry point | pyproject script → `app.application_final:main`, run.py → the same. Remove the conflict. | `python run.py` and `offline-ai-final` work identically |
| 1.4 | Align requirements.txt | Add: `requests`, `pywin32` (Windows marker), optionally `openwakeword`, `faiss-cpu`, `sentence-transformers`, `croniter` as optional extensions (separate requirements-dev.txt: pytest, pytest-qt, ruff, mypy). | `pip install -r requirements.txt` is enough for full operation |
| 1.5 | Explicit Python version | The code was tested on 3.11.9 (all dependencies work), pyproject requires >=3.13 (llama-cpp is missing on 3.14). Decision: requires-python `>=3.11` with documentation that 3.11 is verified. | pyproject/README aligned |

---

### PHASE 2 — Design system (foundation of the redesign)

| # | Step | Details | Verification |
|---|---|---|---|
| 2.1 | Create `ui/design/tokens.py` | All hex values from design_system.md as Python constants: `GRAPHITE`, `GRAPHITE_LIGHT`, `GRAPHITE_DARK`, `EMERALD`, `EMERALD_DARK`, `TEXT_PRIMARY`, `TEXT_SECONDARY`, `BORDER`, `RED`, `YELLOW`, + wizard shades (#151819, #1D8A68, #62C7A3...) and rgba tint formulas. ONE source of truth for all colors. | Module import works; no hardcoded hex values outside tokens.py (grep check) |
| 2.2 | Create QSS builder library `ui/design/qss.py` | Functions that generate QSS for: topbar, sidebar, context panel, nav_button, primary/secondary/disabled buttons, cards, inputs, badges, chips, banners, progress bar, spinner. | Unit test: generated QSS contains all selectors |
| 2.3 | Components `ui/design/components.py` | Reusable Qt widgets: `Card`, `Badge`, `StatusChip`, `Banner`, `StorageBar`, `InstallStepChips`, `Spinner`, `CapabilityChip`, `StepIndicator` (for the wizard sidebar). | Widget tests (creation, API, style) |
| 2.4 | Integrate ThemeManager ↔ design tokens | ThemeManager becomes the sole QSS applier; `grey_emerald` (workspace) and `dark` (installer) palettes from tokens.py; remove hardcoded palettes from app_shell.py and welcome_wizard.py. | Changing the theme changes the look of the whole app |
| 2.4b | Decision on two palettes | The official design contains a darker wizard mode (#151819/#1D8A68) and a lighter workspace mode (#202326/#27C48A). Decision: keep both — installer/wizard uses the darker one, the main app the lighter one — both from tokens.py. | Both palettes defined in tokens.py |

---

### PHASE 3 — AppShell redesign (main window)

| # | Step | Details | Verification |
|---|---|---|---|
| 3.1 | Topbar | ☰ (toggle sidebar), assistant name, stretch, "● Local" status, "Context" (toggle context panel), ⚙ Settings — per the workspace design. The `_sidebar_visible`/`_context_visible` flags finally get buttons. | Clicking ☰/Context toggles; ● Local status visible |
| 3.2 | Sidebar with selected state | Hover + selected indicator (emerald text/accent) on the current page; "+ New Conversation" and "👤 My Profile" at the bottom; navigation per the design (emoji icons). | Visual check + navigation to all pages works |
| 3.3 | Context panel | Sections: Assistant (name + "Balanced · Serbian"), AI Model (name + ● Ready · GPU), Capabilities (✓ list), Memory (relevant count), privacy footer 🔒. Connect to real Assistant data. | Panel shows real model/memory data |
| 3.4 | Status integration (EventBus) | Model load/unload, memory changes, generation events → context panel and status labels via the EventBus (no direct references). | Event simulation changes the panel |
| 3.5 | AppShell ↔ ThemeManager | AppShell stops using hardcoded QSS; everything from the qss.py builder; reaction to theme changes. | Theme change from Settings works across the whole shell |
| 3.6 | Home/AssistantHub page | "Your Assistant" hero card with ✦, status, "Start Conversation" (primary) → navigation to Chat; "Assistant Snapshot" 2×2 grid; "Quick Actions" 2×2 grid — per the design. | Clicking the actions navigates correctly |

---

### PHASE 4 — Page migration to AppShell

Goal: all functional pages work within the new shell. Not a single page is lost — they are only redirected into AppShell.

| # | Step | Details | Verification |
|---|---|---|---|
| 4.1 | Page inventory and route map | List all pages from MainWindow (13 pages) and map them to AppShell routes: Home, Assistant Hub, Chat, Memory, Knowledge, Models, Capabilities, Projects, Agents, Tools, Voice, Automation, Workflow + Settings. Identify pages the design does not have (Agents, Tools, Voice, Automation, Workflow, Models) — decision: keep them as "advanced" (visible in the sidebar) because the functionality is mandatory. | Route map in the status document; no functionality lost |
| 4.2 | Chat in the shell | Carry the ChatWidget functionality (streaming, conversation history, tool calls) into the AppShell Chat page with the workspace layout (header, messages, capability buttons 📎 Files / 🖼 Vision / 🧠 Memory, input + send ➤). | Chat does streaming with the real model (Qwen2.5-Coder) |
| 4.3 | Memory page | Memory list + "Add Memory" / "Forget Selected" per the design; connected to MemoryManager. | Adding/deleting memories works and persists |
| 4.4 | Knowledge page | Source list + "+ Add Knowledge Source"; RAG indexing works; search from chat (KnowledgeSearchTool) works. | Indexing + search tested |
| 4.5 | Models page | Discovery, activation, GPU info; display of the selected models (Qwen2.5-Coder-7B primary, Phi-4-mini secondary). | Model activation works; VRAM info accurate |
| 4.5b | Vision decision | Qwen2.5-VL is a VISION_LLM but multimodal inference is NOT implemented in the pipeline. Decision: do not use the VL model for now; shorten the 🖼 Vision button in chat or mark it as "coming soon" (do NOT implement a half-solution). | Button disabled/marked |
| 4.6 | Capabilities page | Checkbox rows (Text, Programming, Vision, Documents, Voice, Automation) connected to the model's real capability flags. | Labels match the real flags |
| 4.7 | Projects page | Project list + "+ New Project"; ProfileStack override works. | Creating/opening a project works |
| 4.8 | Agents / Tools / Automation / Workflow | Move them as-functional into AppShell (the pages exist, redirect to new components only in Phase 5). Determine their place in the sidebar ("Advanced" section). | All 4 pages available and functional |
| 4.8b | Voice page | VoicePage functionality (STT/TTS configuration, test buttons) in the new design. | Configuration persists; playback test works |
| 4.9 | Settings | QComboBox tabs (General, Assistant, AI/Model, Privacy & Data) per the design; merge the existing SettingsDialog functionality. | All existing settings available |
| 4.10 | QThread/SysTray carry-over | System tray, shortcuts, and QThread workers from MainWindow must survive the migration (tray icon, model load worker, generation worker). | Tray works; background model load works |

---

### PHASE 5 — Wizard redesign (installation flow)

| # | Step | Details | Verification |
|---|---|---|---|
| 5.1 | Dynamic step indicator | WelcomeWizard sidebar: steps get completed/current states when the page changes (currently all look the same). STEP_COMPLETED_STYLE/STEP_CURRENT_STYLE already exist — just wire them up. | Step transition changes the sidebar |
| 5.2 | Custom bottom bar | Instead of standard QWizard buttons: a bottom bar with the version on the left (v1.2.0 → app version) and Back/Next/Cancel/Install buttons per the design. | Visual check |
| 5.3 | Real installation instead of simulation | Replace the InstallationPage QTimer simulation with real steps: folder check (app/models), model copy/verification (checksum) where applicable, creation of config structures. Model download remains optional (models are local). | Wizard ends with a genuinely ready installation |
| 5.4 | Wizard + design system | The wizard switches to tokens.py + qss.py + components.py (remove the internal WIZARD_STYLE palette — duplication). | Wizard uses shared components |

---

### PHASE 6 — Model integration and improvements

| # | Step | Details | Verification |
|---|---|---|---|
| 6.1 | Activate Qwen2.5-Coder-7B as the primary model | Model copied to `models/llm/` (4.36 GB, Q4_K_M, arch qwen2, tool_calling ✓). Settings: `models_dir` → `models/llm` (project-relative dev mode) or keep E:/models + search_paths. GPU: auto layers (all layers on the RTX 3080, model 4.36GB < 10GB VRAM). | Chat with the real model works; GPU offload confirmed (nvidia-smi during generation) |
| 6.2 | Phi-4-mini as the lightweight backup | Second copied model (3.08 GB, Q6_K_L) — available for fast responses / low-VRAM scenario. | Activating both models works (mutual exclusion, a known limitation) |
| 6.3 | Tune inference parameters | `n_ctx` 512 → 4096 (Qwen2.5 supports 32k; 4k balance for VRAM), `max_tokens` 204 → 1024, n_threads 4 → 8 (physical cores) or 16. | Responses are not cut off; context holds the entire conversation |
| 6.3b | Reset bad settings | `model_name: "qwen-7b"` does not match any discovered model — clear it to use default discovery (pick_default_model) or explicitly "Qwen2.5-Coder-7B". | Settings consistent with discovered models |
| 6.4 | Embeddings for memory/RAG (optional) | `memory.embedding_model: "stub"` — consider adding an embedding model from E:\models; there is no valid candidate (mmproj is PROJECTOR, not EMBEDDING) → keep the stub or add bge-micro GGUF later. | Decision recorded in the status |

---

### PHASE 7 — Voice functionality (optional, designed as secondary in the design)

| # | Step | Details | Verification |
|---|---|---|---|
| 7.1 | STT with faster-whisper | Model "base" in `models/voice/stt/`; language sr (the setting exists). Test: recorded WAV → text. | Transcription works |
| 7.2 | TTS pyttsx3 | The Voice setting Hazel EN-GB exists; for Serbian, download available SAPI voices. | Playback works |
| 7.3 | Wake word (optional) | openwakeword is not in requirements; a stub fallback exists. Keep the stub. | Recorded |

---

### PHASE 8 — Cleanup and completion

| # | Step | Details | Verification |
|---|---|---|---|
| 8.1 | Remove dead weight | Decide the fate of: empty folders (assets/, data/, config/ etc. — keep with .gitignore), `Izgled Aplikaccije/` (keep as the design reference), `main_original.py` (keep for --test-runtime), the duplicated settings mechanism (ConfigManager as primary). | Clean structure, documented |
| 8.2 | Typo fix "Izgled Aplikaccije" | Rename the folder to "Izgled Aplikacije" or keep it (paths in docs must reflect the actual name). Decision: keep the name, document it. | Documented |
|  Izgled | — | — | — |
| 8.3 | Update README/START_HERE | New instructions, hardware requirements, model setup (models/llm), design documentation. | README accurate |
| 8.4 | Final E2E testing | Full cycle: wizard → chat with the real model → memory → knowledge → voice → settings → restart persistence. | E2E checklist green |
| 8.5 | Lint + typecheck | ruff (line-length 100, py313→py311 target), mypy (3.11). | ruff/mypy clean (tolerance for legacy) |

---

## 2. Execution order (dependencies)

```
PHASE 0 (safety net)
  └─→ PHASE 1 (launcher stabilization)  ← blocks EVERYTHING
        └─→ PHASE 2 (design system)       ← blocks 3, 4, 5
              ├─→ PHASE 3 (AppShell redesign)
              │     └─→ PHASE 4 (page migration) ← longer phase
              │           └─→ PHASE 6 (models) — can also be earlier, independent of UI phases
              └─→ PHASE 5 (wizard)
  PHASE 7 (voice) — independent, can run in parallel from phase 4
PHASE 8 (cleanup) — at the very end
```

Key rule: **models (6.1–6.3) can be activated immediately after phase 1** for testing chat during development of the UI phases.

---

## 3. Verification rules (definition of done)

Every step must:
1. Pass the full test suite (baseline + new tests) — **zero regression**.
2. Be tested headless: `QT_QPA_PLATFORM=offscreen`, `OFFLINE_AI_TEST_MODE=1`.
3. Be tested with the real model where applicable (chat, streaming, GPU).
4. Update `docs/current_status.md` (status, date, evidence).
5. Commit per step with a phase/step description.

Test commands:
```powershell
# Headless test suite
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -m pytest tests/ -v

# Real model smoke test
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" main_original.py --test-runtime
```

---

## 4. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| llama-cpp-python does not exist for 3.14 | High (confirmed) | Use Python 3.11.9 (verified env) for development and tests |
| Regression of Assistant functionality during UI migration | Medium | Phase 0 baseline suite + "as-functional" migration then styling (4.8) |
| Vision (Qwen2.5-VL) does not work multimodally | Confirmed (report) | Do not use the VL model; mark the Vision button "coming soon" |
| Both models cannot fit in VRAM simultaneously | Certain (4.36+3.08>10 but individually OK) | Activate one at a time (existing limitation) |
| Wizard installation writes to external drives | Low | Wizard uses project/AppData folders |
| Two palettes create inconsistency | Medium | Phase 2 tokens.py — one source of truth |
