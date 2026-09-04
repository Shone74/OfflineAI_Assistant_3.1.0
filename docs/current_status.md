# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04 (Faza 6 završena)
**Trenutna faza:** FAZA 5 — Wizard redizajn (sledeća)
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
| 4 | Migracija stranica | 11 | 10 | 91% 🟡 |
| 5 | Wizard redizajn | 4 | 0 | 0% |
| 6 | Model integracija | 4 | 4 | 100% ✅ |
| 7 | Voice (opciono) | 3 | 0 | 0% |
| 8 | Čišćenje i završetak | 5 | 0 | 0% |

**Ukupno: 34 / 47 koraka (72%)**

**Test suite: 80/80 prolazi** | **GPU: RTX 3080 full offload radi** (Qwen2.5-Coder-7B, 70.8 tok/s)

---

## FAZA 0 — Priprema i sigurnosna mreža ✅

- ✅ **0.1 Git** — init + .gitignore, 161 fajl.
- ✅ **0.2 Zavisnosti** — scipy + nvidia-ml-py3; pip check čist.
- ✅ **0.3 Baseline suite** — conftest.py (test mode + offscreen) + 23 smoke testa; 36/36.
- ✅ **0.4 NameError verifikovan** (popravljen u 1.1).
- ✅ **0.5 settings.json analiza** (korekcije izvršene u 6.3).

## FAZA 1 — Stabilizacija launchera ✅

- ✅ 1.1 NameError popravljen (`_build_pages(manager, navigator)`, `shell_holder`).
- ✅ 1.2 Double-boot uklonjen (`start(show_main_window=False)`).
- ✅ 1.3 Entry point: `offline-ai-final = "app.application_final:main"`.
- ✅ 1.4 requirements.txt: +requests, +pywin32, extras, requirements-dev.txt.
- ✅ 1.5 requires-python >=3.11; ruff/mypy py311.

**E2E:** run.py radi; 13 modela otkriveno; background model load.

## FAZA 2 — Design system ✅

- ✅ 2.1 `ui/design/tokens.py` — WORKSPACE + INSTALLER palete, tint(), tipografija, radius.
- ✅ 2.2 `ui/design/qss.py` — base/shell/chat/wizard builder iz tokena.
- ✅ 2.3 `ui/design/components.py` — Card, Banner, Badge, StatusChip, StorageBar, InstallProgressBar, CapabilityChip, StepIndicator, dugmad helperi.
- ✅ 2.4 ThemeManager generiše QSS iz tokena; legacy light/cyber → fallback; Settings combo = 2 teme. *(2.4b: obe palete u tokens — wizard installer, app workspace.)*

## FAZA 3 — Redizajn AppShell ✅

- ✅ 3.1 Topbar — ☰ toggle, ime, ● Local, Context toggle, ⚙.
- ✅ 3.2 Sidebar — selected stanje, ＋ New Conversation, ADVANCED sekcija, My Profile/Settings na dnu. *(Redosled građenja popravljen: pages pre sidebara.)*
- ✅ 3.3 Context panel — Assistant/AI Model/Capabilities/Memory + 🔒 footer; update API.
- ✅ 3.4 EventBus — MODEL_*/MEMORY_UPDATED/PROFILE_UPDATED subscribe; NEW_CHAT_REQUESTED publish; cleanup u closeEvent.
- ✅ 3.5 Bez lokalnog QSS (invariant test).
- ✅ 3.6 HomePage — AssistantHeroCard (✦, Start Conversation), Snapshot/Quick Actions grid; nula inline hex.

## FAZA 4 — Migracija stranica 🟡 (10/11)

- ✅ **4.1 Mapa ruta** — `docs/pages_map.md` (13 stranica + Home; sidebar: Primarna/ADVANCED/dno).
- ✅ **4.2 Chat** — workspace header (ime + ● Local AI + 📎 Files / 🖼 Vision (disabled — nema multimodalne inferencije) / 🧠 Memory), ➤ send (#send_button), sekundarne dugmad; nula inline hex.
- ✅ **4.3 Memory** — konstante iz WORKSPACE tokena; danger/emerald btn CSS iz palete.
- ✅ **4.4 Knowledge** — već čist (bez inline hex).
- ✅ **4.5 Models** — status label boje iz palete; (4.5b Vision: odbijen — dugme disabled).
- ✅ **4.6 Capabilities** — WORKSPACE tokeni.
- ✅ **4.7 Projects** — WORKSPACE tokeni (+_BLUE info akcenat van palete, dokumentovan).
- ✅ **4.8 Agents/Tools/Automation/Workflow** — agents_page, agent_editor_dialog, tools_page na tokenima.
- ✅ **4.8b Voice** — bez inline hex (bio čist).
- ⬜ **4.9 Settings kao stranica** — SettingsDialog je i dalje dialog; ⚙ je otvara. TODO: napraviti pravu "Settings" stranicu u shell-u (dialog ostaje za napredne postavke).
- ✅ **4.10 SysTray/QThread** — model load worker radi (E2E potvrđeno svaki run); MainWindow se kreira nevidljiv (tray funkcionalnost se koristi samo iz legacy prozora — puna tray integracija u AppShell tek sa 8.1 odlukom).

## FAZA 5 — Wizard redizajn ⬜

- ⬜ 5.1 Dinamički step indikator (StepIndicator komponenta spremna!)
- ⬜ 5.2 Custom bottom bar
- ⬜ 5.3 Prava instalacija umesto simulacije
- ⬜ 5.4 Wizard + design system

## FAZA 6 — Model integracija ✅

- ✅ **6.1 Qwen2.5-Coder-7B aktivan na GPU** — CUDA wheel v0.3.35-cu132 + nvidia-cublas/cuda-runtime cu13; postojeći `_add_cuda_dll_directories()` pokriva cu13/bin/x86_64. **E2E: 999 GPU slojeva, 70.8 tok/s, load 8.7s, odgovor na srpskom.**
- ✅ **6.2 Phi-4-mini** — dostupan kroz isti discovery (3.15GB Q6_K_L).
- ✅ **6.3 Parametri** — n_ctx 4096, max_tokens 1024, n_threads 8; model_name očišćen (default = najmanji chat-compatible).
- ✅ **6.4 Embeddings** — stub ostaje (nema validnog kandidata; dokumentovano).

**Bonus fix:** ConfigManager sada čita `utf-8-sig` (BOM tolerancija — PowerShell Set-Content UTF8 piše BOM).

---

## FAZA 7 — Voice (opciono) ⬜

- ⬜ 7.1–7.3 (STT/TTS testiranje; wake word stub)

## FAZA 8 — Čišćenje ⬜

- ⬜ 8.1–8.5

---

## Dnevnik promena

| Datum | Faza/Korak | Promena |
|---|---|---|
| 2026-09-04 | — | Analiza; docs/ kreirana; modeli kopirani |
| 2026-09-04 | 0.1–0.5 | FAZA 0: git, baseline 36/36 |
| 2026-09-04 | 1.1–1.5 | FAZA 1: run.py radi E2E |
| 2026-09-04 | 2.1–2.4 | FAZA 2: design system; 51/51 |
| 2026-09-04 | 3.1–3.6 | FAZA 3: AppShell + HomePage; 72/72 |
| 2026-09-04 | 4.1–4.8 | FAZA 4 (10/11): stranice na tokenima; 76/76; pages_map.md |
| 2026-09-04 | 6.1–6.4 | FAZA 6: **GPU radi!** CUDA wheel; settings 4096/1024/8; BOM fix; 80/80; GUI E2E sa GPU load 35s |

---

## Poznati otvoreni problemi

1. ~~llama-cpp-python CPU-only~~ **REŠENO** — CUDA wheel (cu132) + cu13 runtime; GPU full offload verifikovan E2E.
2. **4.9 Settings stranica** — SettingsDialog je dialog; treba wrapper stranica u AppShell (sledeći korak).
3. **Legacy MainWindow** — kreira se nevidljiv u start(); tray funkcionalnost vezana za njega; odluka o tray integraciji u 8.1.
4. **Dupliran konfig mehanizam** — ConfigManager primaran (8.1).
5. **Vision multimodalna inferencija** — ne implementirana; 🖼 dugme disabled (4.5b).
6. **Wizard sidebar step stanja** — StepIndicator komponenta gotova, wizard je ne koristi još (Faza 5.1).
