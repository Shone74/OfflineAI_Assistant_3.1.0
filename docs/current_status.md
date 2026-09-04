# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04 (Faza 1 završena)
**Trenutna faza:** FAZA 2 — Design system
**Plan:** `docs/project_plan.md`

Legenda statusa: ⬜ Nije počelo · 🟡 U toku · ✅ Završeno · ⛔ Blokirano · ➖ N/A

---

## Presjek stanja

| Faza | Naziv | Koraci | Završeno | % |
|---|---|---|---|---|
| 0 | Priprema i sigurnosna mreža | 5 | 5 | 100% ✅ |
| 1 | Stabilizacija launchera | 5 | 5 | 100% ✅ |
| 2 | Design system | 4 | 0 | 0% |
| 3 | Redizajn AppShell | 6 | 0 | 0% |
| 4 | Migracija stranica | 11 | 0 | 0% |
| 5 | Wizard redizajn | 4 | 0 | 0% |
| 6 | Model integracija | 4 | 0 | 0% |
| 7 | Voice (opciono) | 3 | 0 | 0% |
| 8 | Čišćenje i završetak | 5 | 0 | 0% |

**Ukupno: 10 / 47 koraka (21%)**

**Baseline: 36/36 testova prolazi** (docs/baseline/baseline_2026-09-04.txt)

---

## FAZA 0 — Priprema i sigurnosna mreža ✅

- ✅ **0.1 Git repozitorijum** — `git init`, `.gitignore` (bez GGUF/keševa), initial commit.
- ✅ **0.2 Zavisnosti** — `scipy` + `nvidia-ml-py3` instalirani; svi importi rade; `pip check` čist.
- ✅ **0.3 Baseline test suite** — `tests/conftest.py` (OFFLINE_AI_TEST_MODE + offscreen) + `tests/test_baseline_smoke.py` (23 nova testa: core, ai, memory, knowledge, tools, security, agent, database, UI). **36/36 prolazi.** pytest-qt instaliran. Baseline snimljen.
- ✅ **0.4 Verifikacija NameError buga** — Potvrđen: `app/application_final.py:43,50,51` → `navigator` van scope-a.
- ✅ **0.5 Provera settings.json** — Identifikovane loše vrednosti (`model_name: "qwen-7b"`, `n_ctx: 512`, `max_tokens: 204`) — korekcija u 6.3.

Napomene iz Faze 0: `OLLAMA_MODELS=E:\models` već postavljen globalno (Ollama blob-ovi se automatski otkrivaju).

---

## FAZA 1 — Stabilizacija launchera ✅

- ✅ **1.1 NameError popravka** — `_build_pages(manager, navigator)` sada prima navigator kao argument; `main()` koristi `shell_holder` dict (navigator defnicija pre shell kreiranja). Verifikovano: headless `_build_pages` gradi svih 11 stranica.
- ✅ **1.2 Double-boot uklonjen** — `ApplicationManager.start(show_main_window: bool = True)`; finalni bootstrap poziva `start(show_main_window=False)` → nema treperenja starog MainWindow-a; wizard/welcome tok netaknut.
- ✅ **1.3 Entry point ujednačen** — pyproject script: `offline-ai-final = "app.application_final:main"` (bio `app.application:main`).
- ✅ **1.4 requirements.txt** — dodati `requests`, `pywin32`; `requirements-dev.txt` (pytest, pytest-qt, ruff, mypy); optional extras dokumentovani (voice/vector/scheduler).
- ✅ **1.5 Python verzija** — `requires-python = ">=3.11"`; ruff/mypy target `py311`; uklonjen nepostojeći `qt_api` pytest config.

**E2E verifikacija Faze 1:** `python run.py` (GUI) pokreće aplikaciju, otkriva 13 modela, učitava stvarni model u pozadini, živi 20s+ bez crash-a. AppShell se prikazuje kao primarni prozor.

---

## FAZA 2 — Design system

- ⬜ 2.1 tokens.py
- ⬜ 2.2 qss.py builder
- ⬜ 2.3 components.py
- ⬜ 2.4 ThemeManager ↔ tokens integracija (uključuje 2.4b odluku o dve palete)

---

## FAZA 3 — Redizajn AppShell

- ⬜ 3.1 Topbar (☰, ime, ● Local, Context, ⚙)
- ⬜ 3.2 Sidebar sa selected stanjem + New Conversation + My Profile
- ⬜ 3.3 Context panel sa stvarnim podacima
- ⬜ 3.4 EventBus status integracija
- ⬜ 3.5 AppShell ↔ ThemeManager
- ⬜ 3.6 Home/AssistantHub strana

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
- ⬜ 6.4 Embeddings odluka (stub ostaje — nema validnog kandidata u E:\models)

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
| 2026-09-04 | — | Analiza projekta završena; kreirani: project_plan.md, current_status.md, design_system.md, models_report.md, environment.md, qa_checklist.md; kopirani modeli u `models/llm/` (Qwen2.5-Coder-7B 4.36GB, Phi-4-mini 3.08GB) |
| 2026-09-04 | 0.1–0.5 | FAZA 0 završena: git init (161 fajl), baseline suite 36/36 green, zavisnosti instalirane |
| 2026-09-04 | 1.1–1.5 | FAZA 1 završena: NameError popravljen, double-boot uklonjen, entry point ujednačen, requirements usklađeni, py>=3.11; **run.py sada radi E2E** (GUI start verifikovan 20s+, model load u pozadini) |

---

## Poznati otvoreni problemi

1. **llama-cpp-python CPU-only na 3.11** — PyPI wheel 0.3.35 nema CUDA (`supports_gpu_offload: False`). Rešenje za Fazom 6: custom CUDA wheel (cmake -DGGML_CUDA=ON) ili prebuilt wheel. RTX 3080 trenutno neiskorišćena u inferenci.
2. **llama-cpp-python nije dostupan za Python 3.14** — razvoj ostaje na 3.11.9 (vidi environment.md).
3. **Vision multimodalna inferencija nije implementirana** — Qwen2.5-VL iz E:\models se NE koristi.
4. **`ai/max_tokens` = 204 i `n_ctx` = 512** — ispravka u 6.3.
5. **Dupliran konfig mehanizam** (settings.json + DB settings tabela) — ConfigManager ostaje primaran (faza 8.1).
6. **Legacy MainWindow (1591 lin.)** — i dalje se kreira (ne pokazuje) u start(); puna migracija funkcionalnosti u Fazi 4, uklanjanje u 8.1.
