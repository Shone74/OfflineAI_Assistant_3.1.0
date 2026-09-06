# Current Status — Offline AI Assistant Redesign

**Last updated:** 2026-09-04 (Phase 7 completed — Wake Word + Automatic Listening)
**Current phase:** All phases completed (7/9)
**Plan:** `docs/project_plan.md`

Status legend: ⬜ Not started · 🟡 In progress · ✅ Completed · ⛔ Blocked · ➖ N/A

---

## State overview

| Phase | Name | Steps | Completed | % |
|---|---|---|---|---|
| 0 | Preparation and safety net | 5 | 5 | 100% ✅ |
| 1 | Launcher stabilization | 5 | 5 | 100% ✅ |
| 2 | Design system | 4 | 4 | 100% ✅ |
| 3 | AppShell redesign | 6 | 6 | 100% ✅ |
| 4 | Page migration | 11 | 11 | 100% ✅ |
| 5 | Wizard redesign | 4 | 3 | 75% ✅ |
| 6 | Model integration | 4 | 4 | 100% ✅ |
| 7 | Voice (Wake Word + Auto Listening) | 3 | 3 | 100% ✅ |
| 8 | Cleanup and completion | 5 | 5 | 100% ✅ |

**Total: 46 / 47 steps (98%)** — only 5.2 remains (wizard bottom bar, cosmetic).

**Test suite: 129/129 passing** | **Ruff: all passed** | **GPU: full offload** | **Wake word: real openwakeword backend**

---

## PHASE 7 — Wake Word + Automatic Listening ✅ (complete specification implemented)

### Wake Word
- ✅ **Default: "hey_jarvis"** — openwakeword predefined label; config `voice.wake_word.{enabled,provider,hotword,threshold}`
- ✅ Thread-safe trigger (QMetaObject marshalling to the GUI thread — fix of a critical bug from the audit)
- ✅ 2s refractory period (one phrase = one trigger)
- ✅ Echo protection: wake word disabled during TTS, restarted after
- ✅ **Real backend verified at runtime**: `openwakeword` + `onnxruntime` installed; ONNX inference (tflite does not exist for Windows)
- ✅ Settings UI: Wake Word section (enable + phrase)
- ✅ `_restart_wake_word_if_enabled` respects `voice.wake_word.enabled`

### Automatic Listening
- ✅ ChatVoiceCoordinator (new component) — connects Chat + Assistant + Voice in AppShell (also fixed the "duplicate ChatWidget" bug: the chat in the final application was not connected to the pipeline!)
- ✅ State machine: IDLE→LISTENING→PROCESSING→SPEAKING→LISTENING loop; idempotent ON/OFF; STOP blocks re-scheduling
- ✅ Silence watchdog (QTimer, buffer-growth, 3s) — automatic end of utterance
- ✅ UI: "Automatic Listening" / "Automatic Listening: ON" toggle button
- ✅ Independent modes: wake ≠ auto ≠ manual; wake ignored during the auto cycle
- ✅ Error → consistent OFF state
- ✅ Clean shutdown (closeEvent + aboutToQuit + VoiceManager.stop)

### Verification (§17)
- **Tests:** 37 new voice tests; **129/129 total** (wake default/config/trigger/duplicate/lifecycle/error; auto ON/OFF/idempotent/cycles/full loop/stop-in-every-phase/shutdown; interactions; echo; single-session; UI; config)
- **Runtime:** `run.py` 40s — `Wake-word detection started (openwakeword)` with `hotword=hey_jarvis`, no errors
- **Lint:** ruff all passed
- **Limitations:** the full microphone cycle (speech→STT→response→TTS→re-listen) was verified only through unit tests with fake audio + injected providers; **real voice verification with an actual microphone requires a human** (say "Hey Jarvis" and enable the "Automatic Listening" button on the Chat page)

---

## Earlier phases — summary (details in git history: 16+ commits)

- **PHASE 0-1:** Git + baseline suite; NameError fix, double-boot fix — run.py works
- **PHASE 2:** ui/design (tokens/QSS/components); ThemeManager from tokens
- **PHASE 3:** AppShell redesign (topbar/sidebar/context/EventBus); HomePage hero
- **PHASE 4:** 12 pages on design tokens; Settings page; Chat workspace layout
- **PHASE 5:** Wizard dynamic step highlight + REAL installation (GGUF verify)
- **PHASE 6:** CUDA wheel — **GPU full offload** (Qwen2.5-Coder-7B, 999 layers, 70 tok/s)
- **PHASE 8:** README/START_HERE; ruff all passed; E2E final

---

## Change log

| Date | Phase/Step | Change |
|---|---|---|
| 2026-09-04 | — | Analysis; docs/ created; models copied |
| 2026-09-04 | 0–8 | Redesign completed (16 commits, 92/92 tests) |
| 2026-09-04 | 7 | **Wake Word (hey_jarvis, real openwakeword backend) + Automatic Listening (state machine + UI + watchdog)**; ChatVoiceCoordinator fixed the duplicate-ChatWidget bug; 129/129 tests; verified at runtime |

---

## Known open issues

1. **5.2 Custom wizard bottom bar** — cosmetic; QWizard buttons are functional.
2. **Real voice verification** — covered by unit tests; a real microphone test requires a human (not automated).
3. **Vision multimodal chat** — not implemented (button disabled).
4. **Silence watchdog is a buffer-growth heuristic** — RMS/energy VAD is a future upgrade (documented in the coordinator).
5. **Wake word uses the default microphone** — the `OpenWakeWord` stream does not respect the `audio.input_device_*` config (existing limitation, documented in audit G3.6).
6. **Hotword change requires a restart** — the provider is created at startup; the Settings UI clearly communicates this to the user.

## Next steps (recommendations)

1. Human test: "Hey Jarvis" with a real microphone + the Automatic Listening cycle
2. RMS-based VAD (instead of the buffer-growth heuristic)
3. Wake word device selection from the audio config
4. Wizard bottom bar (5.2)
