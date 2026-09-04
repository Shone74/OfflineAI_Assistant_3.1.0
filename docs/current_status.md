# Current Status — Redizajn Offline AI Assistant

**Poslednje ažuriranje:** 2026-09-04
**Trenutna faza:** FAZA 0 — Priprema
**Plan:** `docs/project_plan.md`

Legenda statusa: ⬜ Nije počelo · 🟡 U toku · ✅ Završeno · ⛔ Blokirano · ➖ N/A

---

## Presjek stanja

| Faza | Naziv | Koraci | Završeno | % |
|---|---|---|---|---|
| 0 | Priprema i sigurnosna mreža | 5 | 3 | 60% |
| 1 | Stabilizacija launchera | 5 | 0 | 0% |
| 2 | Design system | 4 | 0 | 0% |
| 3 | Redizajn AppShell | 6 | 0 | 0% |
| 4 | Migracija stranica | 11 | 0 | 0% |
| 5 | Wizard redizajn | 4 | 0 | 0% |
| 6 | Model integracija | 4 | 0 | 0% |
| 7 | Voice (opciono) | 3 | 0 | 0% |
| 8 | Čišćenje i završetak | 5 | 0 | 0% |

**Ukupno: 3 / 47 koraka (6%)**

---

## FAZA 0 — Priprema i sigurnosna mreža

- ✅ **0.2 Zavisnosti u Python 3.11** — `llama-cpp-python 0.3.35`, `PySide6 6.11.1`, `pytest 9.1.1`, `faster-whisper`, `sounddevice`, `pyttsx3`, `requests`, `pywin32` prisutni. Nedostaju `scipy`, `nvidia-ml-py3` (za 0.2 cleanup pre testa).
- ✅ **0.4 Verifikacija NameError buga** — Potvrđeno: `app/application_final.py:43,50,51` koristi `navigator` definisan tek u `main()` (linija 90) → `NameError: name 'navigator' is not defined` pri svakom pokretanju `run.py`. Launcher je potvrđeno pokvaren. Rešenje planirano u 1.1.
- ✅ **0.5 Provera settings.json** — `%LOCALAPPDATA%\OfflineAI\config\settings.json` postoji. Pronađene loše vrednosti: `models_dir: "E:/models"` (radi, ali neusklađeno sa novim rasporedom), `model_search_paths` samo AppData, `model_name: "qwen-7b"` (ne odgovara nijednom modelu), `n_ctx: 512` (premalo), `max_tokens: 204` (premalo). Korekcije planirane u 6.1/6.3.
- ⬜ 0.1 Git repozitorijum
- ⬜ 0.3 Baseline test suite

---

## FAZA 1 — Stabilizacija launchera

- ⬜ 1.1 Popravka `application_final.py` NameError
- ⬜ 1.2 Uklanjanje double-boot obrasca
- ⬜ 1.3 Ujednačavanje entry pointa
- ⬜ 1.4 Usklađivanje requirements.txt
- ⬜ 1.5 Python verzija >=3.11

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
| 2026-09-04 | — | Analiza projekta završena; kreirani: project_plan.md, current_status.md, design_system.md, models_report.md, environment.md; kopirani modeli u `models/llm/` (Qwen2.5-Coder-7B 4.36GB, Phi-4-mini 3.08GB) |
| 2026-09-04 | 0.2 | Verifikovan Python 3.11.9 env — sve ključne zavisnosti prisutne |
| 2026-09-04 | 0.4 | Potvrđen NameError bug u launcheru (application_final.py:43,50,51) |
| 2026-09-04 | 0.5 | Analiziran settings.json — identifikovane loše vrednosti (models_dir, model_name, n_ctx, max_tokens) |

---

## Poznati otvoreni problemi (van plana koraka)

1. **llama-cpp-python nije dostupan za Python 3.14** — razvoj/testovi moraju na 3.11.9 (vidi environment.md).
2. **Vision multimodalna inferencija nije implementirana** u chat pipeline-u (mmproj se klasifikuje kao PROJECTOR, ne koristi se). Qwen2.5-VL iz E:\models se NE koristi.
3. **MM Projekat u PyInstalleru** — installer/ ima generatore; nisu testirani sa novim UI-jem (odloženo do faze 8).
4. **`ai/max_tokens` = 204 trenutno seče duge odgovore** — ispravka u 6.3.
5. **Dupliran konfig mehanizam** (settings.json + DB settings tabela) — ConfigManager ostaje primaran (faza 8.1).
