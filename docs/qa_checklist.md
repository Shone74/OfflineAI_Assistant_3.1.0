# QA Checklist — Verification without regression

**Purpose:** Defines what "functionality remains intact across the entire application" means. Every step from the plan must pass the relevant items before being marked ✅ in current_status.md.

---

## 1. Regression smoke suite (mandatory after EVERY step)

```powershell
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -m pytest tests/ -v
```
- Zero failing tests (the phase 0.3 baseline + new tests)
- No new warnings in the log vs the baseline

## 2. Launch check (after UI steps)

```powershell
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" run.py
```
- The app starts WITHOUT a traceback in the console and without a crash
- Only one main window (AppShell) is visible — no flickering of the old MainWindow
- Logs in `%LOCALAPPDATA%\OfflineAI\logs\` contain no newly occurring ERROR entries

## 3. Functional matrix (E2E — phase 8.4, but key items also during phases)

| # | Function | How it is verified | Phases that touch it |
|---|---|---|---|
| F1 | Chat streaming with the real model | Message → tokens appear; response complete | 1, 3, 4.2, 6.1 |
| F2 | GPU offload | `nvidia-smi` shows VRAM during generation | 6.1 |
| F3 | Model discovery (models/llm + E:/models if in paths) | Models page lists both copied models | 4.5, 6.1 |
| F4 | Activation/second model | Switching to Phi-4-mini and back works | 4.5, 6.2 |
| F5 | Memory: add/forget | Add Memory → restart → memory persists | 4.3 |
| F6 | "remember..." trigger in chat | Explicit memorization command is confirmed | 4.2, 4.3 |
| F7 | Knowledge indexing + search | Add a .md/.txt source → query via the KnowledgeSearchTool | 4.4 |
| F8 | Tool calls (tool_calling) | The agent executes a system tool with a permission prompt | 4.2, 4.8 |
| F9 | Permission layer (ASK) | A risky tool requires confirmation | 4.8 |
| F10 | Projects create/open | New project → settings override works | 4.7 |
| F11 | Automation workflow | Run the built-in system_check workflow | 4.8 |
| F12 | Voice STT/TTS test buttons | Playback + recording | 4.8b |
| F13 | Settings persistence | Theme/model change → restart → persists | 3.5, 4.9 |
| F14 | System tray | Minimize to tray + restore | 4.10 |
| F15 | Wizard first-run | (rename settings first_run.completed=false) → wizard flows through all 7 steps | 5.x |
| F16 | Wizard: real installation | Steps perform real actions (folders, checks) | 5.3 |
| F17 | Navigation to all pages | Every route from the sidebar opens the page without an error | 3.2, 4.x |
| F18 | Context panel data | Model/memory/capabilities reflect the actual state | 3.3, 3.4 |
| F19 | Topbar toggle | ☰ and Context buttons hide/show the panels | 3.1 |
| F20 | Restart persistence | Full cycle → restart → all settings/conversations present | 8.4 |

## 4. Visual checks (after design steps)

- Comparison with the `design_previews/` previews (side-by-side)
- Palettes: the wizard screen uses the installer palette, the app uses the workspace palette — no mixing
- No hardcoded hex values outside `ui/design/tokens.py` (grep check in 2.1)
- Segoe UI fonts, sizes per design_system.md §4

## 5. Prohibitions (anti-regression rules)

- DO NOT delete any page/functional route from MainWindow until it is redirected into AppShell
- DO NOT change signatures of public core/ai/ APIs until the smoke suite passes
- DO NOT touch `%LOCALAPPDATA%\OfflineAI\` manually during tests (except renames for the wizard test)
- Every step = commit (visible diff; easier rollback)
