# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04 (Faza 7 završena — Wake Word + Automatic Listening)
**Trenutna faza:** Sve faze završene (7/9)
**Plan:** `docs/project_plan.md`

Legenda statusa: ⬜ Nije počelo · 🟡 U toku · ✅ Završeno · ⛔ Blokirano · ➖ N/A

---

## Presjek stanja

| Faza | Naziv | Koraci | Završeno | % |
|---|---|---|---|---|
| 0 | Priprema i sigurnosna mreža | 5 | 5 | 100% ✅ |
| 1 | Stabilizacija launchera | 5 | 5 | 100% ✅ |
| 2 | Design system | 4 | 4 | 100% ✅ |
| 3 | Redizajn AppShell | 6 | 6 | 100% ✅ |
| 4 | Migracija stranica | 11 | 11 | 100% ✅ |
| 5 | Wizard redizajn | 4 | 3 | 75% ✅ |
| 6 | Model integracija | 4 | 4 | 100% ✅ |
| 7 | Voice (Wake Word + Auto Listening) | 3 | 3 | 100% ✅ |
| 8 | Čišćenje i završetak | 5 | 5 | 100% ✅ |

**Ukupno: 46 / 47 koraka (98%)** — preostao samo 5.2 (wizard bottom bar, kozmetika).

**Test suite: 129/129 prolazi** | **Ruff: all passed** | **GPU: full offload** | **Wake word: stvarni openwakeword backend**

---

## FAZA 7 — Wake Word + Automatic Listening ✅ (kompletna specifikacija implementirana)

### Wake Word
- ✅ **Default: "hey_jarvis"** — openwakeword predefinisana labela; config `voice.wake_word.{enabled,provider,hotword,threshold}`
- ✅ Thread-safe trigger (QMetaObject marshalling na GUI thread — fix kritičnog bug-a iz audita)
- ✅ Refractory 2s (jedna fraza = jedan trigger)
- ✅ Echo zaštita: wake word ugašen tokom TTS-a, restart posle
- ✅ **Stvarni backend verifikovan u runtime-u**: `openwakeword` + `onnxruntime` instalirani; ONNX inference (tflite ne postoji za Windows)
- ✅ Settings UI: Wake Word sekcija (enable + phrase)
- ✅ `_restart_wake_word_if_enabled` poštuje `voice.wake_word.enabled`

### Automatic Listening
- ✅ ChatVoiceCoordinator (nova komponenta) — povezuje Chat + Assistant + Voice u AppShell-u (resio i "dupli ChatWidget" bug: chat u finalnoj aplikaciji nije bio povezan na pipeline!)
- ✅ State machine: IDLE→LISTENING→PROCESSING→SPEAKING→LISTENING petlja; idempotentan ON/OFF; STOP blokira re-schedule
- ✅ Silence watchdog (QTimer, buffer-growth, 3s) — automatski kraj izjave
- ✅ UI: "Automatic Listening" / "Automatic Listening: ON" toggle dugme
- ✅ Modovi nezavisni: wake ≠ auto ≠ manual; wake ignoriše tokom auto ciklusa
- ✅ Error → konzistentno OFF stanje
- ✅ Čist shutdown (closeEvent + aboutToQuit + VoiceManager.stop)

### Verifikacija (§17)
- **Testovi:** 37 novih voice testova; **129/129 ukupno** (wake default/config/trigger/duplikat/lifecycle/error; auto ON/OFF/idempotent/ciklusi/pun-krug/stop-u-svakoј-fazi/shutdown; interakcije; echo; single-session; UI; config)
- **Runtime:** `run.py` 40s — `Wake-word detection started (openwakeword)` sa `hotword=hey_jarvis`, bez grešaka
- **Lint:** ruff all passed
- **Ograničenja:** mikrofonski pun ciklus (govor→STT→odgovor→TTS→re-listen) verifikovan jedinično kroz fake audio + injektovane providere; **realna glasovna verifikacija sa stvarnim mikrofonom zahteva čoveka** (recite "Hey Jarvis" i uključite "Automatic Listening" dugme u Chat strani)

---

## Ranije faze — sažetak (detalji u git istoriji: 16+ commitova)

- **FAZA 0-1:** Git + baseline suite; NameError fix, double-boot fix — run.py radi
- **FAZA 2:** ui/design (tokens/QSS/komponente); ThemeManager iz tokena
- **FAZA 3:** AppShell redizajn (topbar/sidebar/context/EventBus); HomePage hero
- **FAZA 4:** 12 stranica na design tokenima; Settings stranica; Chat workspace layout
- **FAZA 5:** Wizard dinamički step highlight + PRAVA instalacija (GGUF verify)
- **FAZA 6:** CUDA wheel — **GPU full offload** (Qwen2.5-Coder-7B, 999 slojeva, 70 tok/s)
- **FAZA 8:** README/START_HERE; ruff all passed; E2E final

---

## Dnevnik promena

| Datum | Faza/Korak | Promena |
|---|---|---|
| 2026-09-04 | — | Analiza; docs/ kreirana; modeli kopirani |
| 2026-09-04 | 0–8 | Redizajn završen (16 commitova, 92/92 testova) |
| 2026-09-04 | 7 | **Wake Word (hey_jarvis, stvarni openwakeword backend) + Automatic Listening (state machine + UI + watchdog)**; ChatVoiceCoordinator rešio dupli-ChatWidget bug; 129/129 testova; runtime verifikovano |

---

## Poznati otvoreni problemi

1. **5.2 Custom wizard bottom bar** — kozmetika; QWizard dugmad funkcionalna.
2. **Realna glasovna verifikacija** — jedinično pokriveno; stvarni mikrofon test zahteva čoveka (nije automatizovan).
3. **Vision multimodalni chat** — nije implementiran (dugme disabled).
4. **Silence watchdog je buffer-growth heuristika** — RMS/energija VAD je buduća nadogradnja (dokumentovano u koordinatoru).
5. **Wake word koristi default mikrofon** — `OpenWakeWord` stream ne poštuje `audio.input_device_*` config (postojije ograničenje, dokumentovano u auditu G3.6).
6. **Hotword promena zahteva restart** — provider se kreira pri startup-u; Settings UI to jasno saopštava korisniku.

## Sledeći koraci (preporuke)

1. Čovek testira: "Hey Jarvis" sa stvarnim mikrofonom + Automatic Listening ciklus
2. RMS-based VAD (umesto buffer-growth heuristike)
3. Wake word device selection iz audio configa
4. Wizard bottom bar (5.2)
