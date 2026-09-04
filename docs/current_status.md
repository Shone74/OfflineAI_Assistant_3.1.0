# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04 (Faza 3 završena)
**Trenutna faza:** FAZA 4 — Migracija stranica na AppShell
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
| 4 | Migracija stranica | 11 | 0 | 0% |
| 5 | Wizard redizajn | 4 | 0 | 0% |
| 6 | Model integracija | 4 | 0 | 0% |
| 7 | Voice (opciono) | 3 | 0 | 0% |
| 8 | Čišćenje i završetak | 5 | 0 | 0% |

**Ukupno: 20 / 47 koraka (43%)**

**Test suite: 72/72 prolazi** (baseline 36 + design 15 + shell 21)

---

## FAZA 0 — Priprema i sigurnosna mreža ✅

- ✅ **0.1 Git repozitorijum** — `git init`, `.gitignore` (bez GGUF/keševa), initial commit (161 fajl).
- ✅ **0.2 Zavisnosti** — `scipy` + `nvidia-ml-py3` instalirani; svi importi rade; `pip check` čist.
- ✅ **0.3 Baseline test suite** — `tests/conftest.py` (OFFLINE_AI_TEST_MODE + offscreen) + `tests/test_baseline_smoke.py` (23 testa: core, ai, memory, knowledge, tools, security, agent, database, UI). **36/36 prolazi.** pytest-qt instaliran.
- ✅ **0.4 Verifikacija NameError buga** — Potvrđen na `application_final.py:43,50,51`.
- ✅ **0.5 Provera settings.json** — Loše vrednosti identifikovane (korekcija u 6.3).

---

## FAZA 1 — Stabilizacija launchera ✅

- ✅ **1.1 NameError popravka** — `_build_pages(manager, navigator)` prima navigator kao argument; `main()` koristi `shell_holder` dict.
- ✅ **1.2 Double-boot uklonjen** — `ApplicationManager.start(show_main_window: bool = True)`; final bootstrap: `start(show_main_window=False)`.
- ✅ **1.3 Entry point ujednačen** — pyproject: `offline-ai-final = "app.application_final:main"`.
- ✅ **1.4 requirements.txt** — +requests, +pywin32; requirements-dev.txt; optional extras dokumentovani.
- ✅ **1.5 Python verzija** — `requires-python = ">=3.11"`; ruff/mypy target py311.

**E2E:** `python run.py` radi — 13 modela otkriveno, model se učitava u pozadini, 22s+ bez crash-a.

---

## FAZA 2 — Design system ✅

- ✅ **2.1 `ui/design/tokens.py`** — WORKSPACE (`#202326/#27C48A`) + INSTALLER (`#151819/#1D8A68`) palete kao `Palette` dataclass sa `tint()` helperima; tipografija, radius. Jedini izvor hex vrednosti.
- ✅ **2.2 `ui/design/qss.py`** — builder: `_base()` + `shell_qss()` + `chat_qss()` + `wizard_qss()` + `build_full_qss()`; svi objectName selektori iz workspace prototipa.
- ✅ **2.3 `ui/design/components.py`** — Card, Banner, Badge, StatusChip, StorageBar, InstallProgressBar, CapabilityChip, **StepIndicator** (default ○ / current ● / completed ✓), make_primary/secondary_button.
- ✅ **2.4 ThemeManager ↔ tokens** — ThemeManager generiše QSS iz tokena; `grey_emerald`=workspace, `dark`/`installer`=installer režim; legacy light/cyber → fallback na zvaničnu temu; Settings combo = 2 zvanične teme. *(2.4b odluka: obe palete žive u tokens — wizard installer, app workspace.)*

Testovi: 15 novih (vrednosti tokena, QSS selektori, nema mešanja paleta, StepIndicator stanja, ThemeManager). **51/51 u trenutku faze.**

---

## FAZA 3 — Redizajn AppShell ✅

- ✅ **3.1 Topbar** — ☰ (toggle sidebar), ime asistenta (#topbar_title), stretch, `● Local` (#status_local), Context (toggle panel), ⚙ Settings.
- ✅ **3.2 Sidebar** — checked/selected stanje na aktivnoj ruti, `＋ New Conversation` (#new_conversation), primarna navigacija (Home/Chat/Memory/Knowledge/Capabilities/Projects), ADVANCED sekcija (Models/Agents/Tools/Voice/Automation/Workflow), 👤 My Profile + ⚙ Settings na dnu. *(Popravljen redosled građenja: pages pre sidebara da bi se ADVANCED sekcija popunila.)*
- ✅ **3.3 Context panel** — sekcije Assistant/AI Model/Capabilities/Memory + 🔒 privacy footer; public API: `update_model_status()`, `update_memory_count()`, `set_assistant_name()`.
- ✅ **3.4 EventBus** — subscribe: MODEL_LOADED/UNLOADED/LOAD_FAILED, MEMORY_UPDATED, PROFILE_UPDATED; NEW_CHAT_REQUESTED publish kroz bus (ApplicationManager već osluškuje i čisti STM); `_unsubscribe_events()` u closeEvent.
- ✅ **3.5 AppShell ↔ ThemeManager** — lokalni QSS potpuno uklonjen (`styleSheet() == ""` invariant u testu); svi stilovi iz ThemeManager-a.
- ✅ **3.6 HomePage** — `AssistantHeroCard` (✦, ime, status, Start Conversation), Snapshot 2×2, Quick Actions 2×2; StatusCard nasleđuje design Card; **nula inline hex vrednosti**.

Testovi: 21 novi (topbar, toggle, selected nav, advanced sekcija, context API, event bus, hero). **72/72 prolazi. GUI E2E: 22s bez greške.**

---

## FAZA 4 — Migracija stranica na AppShell

- ⬜ 4.1 Popis stranica i mapa ruta
- ⬜ 4.2 Chat u shell-u (streaming + stvarni model)
- ⬜ 4.3 Memory strana
- ⬜ 4.4 Knowledge strana
- ⬜ 4.5 Models strana (uključuje 4.5b Vision odluku)
- ⬜ 4.6 Capabilities strana
- ⬜ 4.7 Projects strana
- ⬜ 4.8 Agents/Tools/Automation/Workflow (kao-funkcionalno)
- ⬜ 4.8b Voice strana
- ⬜ 4.9 Settings
- ⬜ 4.10 SysTray/QThread preživljavanje

*Napomena: stranice se VEĆ grade u `_build_pages()` i rade unutar AppShell-a (faza 1 verifikovana E2E). Faza 4 je stilska dorada svake stranice po dizajnu + provera funkcionalnosti unutar novog shell-a.*

---

## FAZA 5 — Wizard redizajn

- ⬜ 5.1 Dinamički step indikator
- ⬜ 5.2 Custom bottom bar
- ⬜ 5.3 Prava instalacija umesto simulacije
- ⬜ 5.4 Wizard + design system

---

## FAZA 6 — Model integracija

- ⬜ 6.1 Aktivacija Qwen2.5-Coder-7B (primarni)
- ⬜ 6.2 Phi-4-mini (rezervni)
- ⬜ 6.3 Inference parametri (n_ctx 4096, max_tokens 1024, threads)
- ⬜ 6.4 Embeddings odluka (stub ostaje)

---

## FAZA 7 — Voice (opciono)

- ⬜ 7.1 STT faster-whisper
- ⬜ 7.2 TTS pyttsx3
- ⬜ 7.3 Wake word — ostaje stub

---

## FAZA 8 — Čišćenje

- ⬜ 8.1 Dead weight uklanjanje
- ⬜ 8.2 Folder "Izgled Aplikaccije" — zadržati, dokumentovati
- ⬜ 8.3 README/START_HERE ažuriranje
- ⬜ 8.4 E2E testiranje
- ⬜ 8.5 Lint + typecheck

---

## Dnevnik promena

| Datum | Faza/Korak | Promena |
|---|---|---|
| 2026-09-04 | — | Analiza završena; kreirana docs/ dokumentacija (6 dokumenata); modeli kopirani u `models/llm/` |
| 2026-09-04 | 0.1–0.5 | FAZA 0: git init, baseline suite 36/36 green, zavisnosti |
| 2026-09-04 | 1.1–1.5 | FAZA 1: NameError popravljen, double-boot uklonjen, requirements/py>=3.11; **run.py radi E2E** |
| 2026-09-04 | 2.1–2.4 | FAZA 2: design system (tokens/qss/components), ThemeManager iz tokena; 51/51 |
| 2026-09-04 | 3.1–3.6 | FAZA 3: AppShell redizajn (topbar/sidebar/context/EventBus/no-local-QSS) + HomePage hero; 72/72; GUI E2E ok |

---

## Poznati otvoreni problemi

1. **llama-cpp-python CPU-only na 3.11** — PyPI wheel 0.3.35 bez CUDA (`supports_gpu_offload: False`). Za Fazom 6: custom CUDA wheel. RTX 3080 trenutno neiskorišćena.
2. **llama-cpp-python nije dostupan za Python 3.14** — razvoj na 3.11.9.
3. **Vision multimodalna inferencija nije implementirana** — Qwen2.5-VL se NE koristi.
4. **`ai/max_tokens` = 204 i `n_ctx` = 512** — ispravka u 6.3.
5. **Dupliran konfig mehanizam** — ConfigManager primaran (faza 8.1).
6. **Legacy MainWindow (1591 lin.)** — kreira se (ne pokazuje) u start(); migracija u Fazi 4, uklanjanje u 8.1.
