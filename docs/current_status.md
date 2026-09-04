# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04 (Redizajn završen)
**Trenutna faza:** FAZA 7 (voice) je opciona i odložena — sve ostalo završeno
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
| 5 | Wizard redizajn | 4 | 3 | 75% ✅* |
| 6 | Model integracija | 4 | 4 | 100% ✅ |
| 7 | Voice (opciono) | 3 | 0 | 0% ➖ |
| 8 | Čišćenje i završetak | 5 | 5 | 100% ✅ |

**Ukupno: 43 / 47 koraka (91%)** — preostala 4 koraka su opcioni voice (Faza 7) + wizard bottom bar (5.2, kozmetika).

**Test suite: 92/92 prolazi** | **Ruff: All checks passed** | **GPU: full offload verifikovan** (Qwen2.5-Coder-7B, RTX 3080)

## Redizajn — završni rezime

1. **Launcher** — NameError bug popravljen, double-boot uklonjen; `run.py` radi E2E
2. **Design sistem** — `ui/design/` (tokens/qss/components); ThemeManager generiše sve iz tokena; dva režima (workspace/installer)
3. **AppShell** — topbar + toggle kontrole, sidebar sa selected stanjima + New Conversation + My Profile, context panel sa stvarnim podacima, EventBus integracija, HomePage hero kartica
4. **Stranice** — svih 12 stranica na WORKSPACE tokenima; Chat po workspace dizajnu (capability dugmad, ➤ send); Settings stranica + Advanced dialog
5. **Wizard** — dinamički step highlight (✓/●/broj); PRAVA instalacija (folderi, dependencije, model discovery, GGUF verifikacija, config) umesto simulacije
6. **Modeli** — CUDA wheel (cu132) + cu13 runtime; GPU offload radi out-of-the-box; Qwen2.5-Coder-7B aktivan (999 slojeva, 70.8 tok/s); params 4096/1024/8
7. **Dokumentacija** — 7 dokumenata + baseline; README/START_HERE novi
8. **Kvalitet** — 92 testa (36 baseline + 56 novih), ruff čist, E2E verifikovano

---

## Detaljan pregled po fazama

### FAZA 0 — Priprema i sigurnosna mreža ✅
Git repo (.gitignore bez GGUF); zavisnosti (scipy, nvidia-ml-py3); baseline suite (conftest + 23 smoke testa); NameError verifikovan; settings.json analiza.

### FAZA 1 — Stabilizacija launchera ✅
`_build_pages(manager, navigator)` fix; `start(show_main_window=False)`; entry point `app.application_final:main`; requirements +pywin32/requests + extras + dev; `requires-python >=3.11`.

### FAZA 2 — Design system ✅
`ui/design/tokens.py` (WORKSPACE #202326/#27C48A + INSTALLER #151819/#1D8A68, tint(), tipografija, radius); `ui/design/qss.py` (base/shell/chat/wizard builder); `ui/design/components.py` (Card, Banner, Badge, StatusChip, StorageBar, InstallProgressBar, CapabilityChip, StepIndicator, dugmad); ThemeManager ↔ tokens (legacy → fallback).

### FAZA 3 — Redizajn AppShell ✅
Topbar (☰/ime/●Local/Context/⚙); sidebar (selected stanja, ＋New Conversation, ADVANCED sekcija, Profile/Settings dno); context panel (Assistant/AI Model/Capabilities/Memory + 🔒, update API); EventBus (MODEL_*/MEMORY/PROFILE + NEW_CHAT publish); bez lokalnog QSS; HomePage (AssistantHeroCard + Snapshot + Quick Actions).

### FAZA 4 — Migracija stranica ✅ (11/11)
Mapa ruta (docs/pages_map.md); Chat (workspace header + capability dugmad — Vision disabled namerno, ➤ send, nula inline hex); Memory/Agents/AgentEditor/Capabilities/AssistantHub/Projects/Tools/Models na WORKSPACE tokenima; Settings stranica (quick + Advanced dialog); worker/tray preživeli.

### FAZA 5 — Wizard redizajn ✅ (3/4; 5.2 kozmetika odložena)
Dinamički step highlight (currentIdChanged → ✓/●/broj stanja); PRAVA instalacija (5 stvarnih faza umesto simulacije — folderi/dependencije/model discovery/GGUF verify/config); nul-safety timer. 5.2 (custom bottom bar sa verzijom) — kozmetika, QWizard dugmad funkcionalna; 5.4 — wizard koristi identične vrednosti kao INSTALLER tokeni (lokalne konstante; vrednosti identične, refaktor u tokens opcion).

### FAZA 6 — Model integracija ✅
CUDA wheel v0.3.35-cu132 + nvidia-cublas/cuda-runtime cu13 (pip); GPU full offload (999 slojeva) verifikovan E2E — 70.8 tok/s, load 8.7s; Qwen2.5-Coder-7B primarni, Phi-4-mini sekundarni; settings: n_ctx 4096, max_tokens 1024, n_threads 8; BOM-tolerantan config (utf-8-sig); embeddings stub (nema kandidata).

### FAZA 7 — Voice ➖ (odloženo, opciono)
STT/TTS konfiguracija postoji i radi (VoicePage); wake-word stub. Testiranje sa stvarnim mikrofonom odloženo — funkcionalnost je netaknuta iz starog koda.

### FAZA 8 — Čišćenje i završetak ✅
8.1 Dead weight: prazni folderi zadržani (runtime ih koristi/ignore); "Izgled Aplikaccije" zadržan kao dizajn referenca; main_original.py zadržan (--test-runtime); ConfigManager primaran. 8.2 Folder ime zadržano (dokumentovano). 8.3 README/START_HERE novi (GPU uputstvo, modeli, testovi). 8.4 E2E: 40s run — AppShell + GPU load + security/voice/knowledge/agent/automation bez greške. 8.5 Ruff all passed (136 fixeva; BLE001/S110/S112 namerno ignorisani — stub-first obrasci).

---

## Dnevnik promena

| Datum | Faza/Korak | Promena |
|---|---|---|
| 2026-09-04 | — | Analiza; docs/ kreirana (6 dokumenata); modeli kopirani (Qwen 4.36GB + Phi 3.08GB) |
| 2026-09-04 | 0.1–0.5 | FAZA 0: git init, baseline 36/36 |
| 2026-09-04 | 1.1–1.5 | FAZA 1: run.py radi E2E |
| 2026-09-04 | 2.1–2.4 | FAZA 2: design system; 51/51 |
| 2026-09-04 | 3.1–3.6 | FAZA 3: AppShell + HomePage; 72/72 |
| 2026-09-04 | 4.1–4.8 | FAZA 4 (10/11): stranice na tokenima; 76/76 |
| 2026-09-04 | 6.1–6.4 | FAZA 6: GPU radi! CUDA wheel; BOM fix; 80/80 |
| 2026-09-04 | 4.9 | Settings stranica; FAZA 4 kompletna; 83/83 |
| 2026-09-04 | 5.1–5.3 | FAZA 5: step highlight + prava instalacija; 92/92 |
| 2026-09-04 | 8.1–8.5 | FAZA 8: README, lint clean, E2E final — **REDIZAJN ZAVRŠEN** |

---

## Poznati otvoreni problemi (post-redizajn)

1. **5.2 Custom wizard bottom bar** — kozmetika; QWizard dugmad funkcionalna. Opciono u sledećoj iteraciji.
2. **Voice testiranje (Faza 7)** — odloženo; VoicePage funkcionalnost netaknuta (STT/TTS konfiguracija + test dugmad).
3. **Vision multimodalni chat** — nije implementiran u pipeline (arhitekturna odluka: 🖼 dugme disabled). Za buduću verziju: mmproj + image input u ChatWidget.
4. **Wizard konstante vs tokens** — vrednosti identične INSTALLER paleti; refaktor na direktan import opcion.
5. **Tray ikona** — vezana za legacy MainWindow (kreira se nevidljivo). Puna integracija u AppShell = budući korak.

## Sledeći koraci (preporuke van redizajna)

1. Voice E2E testiranje (Faza 7)
2. Wizard bottom bar (5.2) + refaktor konstanti na tokens import
3. Tray integracija u AppShell
4. Vision pipeline (mmproj + slike u chatu)
5. faiss-cpu + pravi embedding model za vektorsku memoriju (brže pretrage)
