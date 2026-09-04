# QA Checklist — Verifikacija bez regresije

**Namena:** Definiše šta znači "funkcionalnost ostaje ispravna kroz celu aplikaciju". Svaki korak iz plana mora proći relevantne stavke pre nego što se obeleži kao ✅ u current_status.md.

---

## 1. Regression smoke suite (obavezno posle SVAKOG koraka)

```powershell
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -m pytest tests/ -v
```
- Nula palih testova (baseline iz faze 0.3 + novi testovi)
- Nema novih warning-a u logu vs baseline

## 2. Launch provera (posle UI koraka)

```powershell
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" run.py
```
- App se pokreće BEZ traceback-a u konzoli i bez crash-a
- Vidljiv je samo jedan glavni prozor (AppShell) — bez treperenja starog MainWindow-a
- Logovi u `%LOCALAPPDATA%\OfflineAI\logs\` bez ERROR unosa novog nastanka

## 3. Funkcionalna matrica (E2E — faza 8.4, ali ključne stavke i tokom faza)

| # | Funkcija | Kako se verifikuje | Faze koje je diraju |
|---|---|---|---|
| F1 | Chat streaming sa stvarnim modelom | Poruka → tokeni se pojavljuju; odgovor kompletan | 1, 3, 4.2, 6.1 |
| F2 | GPU offload | `nvidia-smi` pokazuje VRAM tokom generacije | 6.1 |
| F3 | Model discovery (models/llm + E:/models ako u putanjama) | Models stranica lista oba kopirana modela | 4.5, 6.1 |
| F4 | Aktivacija/drugi model | Switch na Phi-4-mini i nazad radi | 4.5, 6.2 |
| F5 | Memorija: add/forget | Add Memory → restart → memory opstaje | 4.3 |
| F6 | "remember..." okidač u chatu | Eksplicitna naredba pamćenja se potvrđuje | 4.2, 4.3 |
| F7 | Knowledge indeksiranje + pretraga | Dodaj .md/.txt izvor → upit preko KnowledgeSearchTool-a | 4.4 |
| F8 | Tool pozivi (tool_calling) | Agent izvršava sistem tool sa permission promptom | 4.2, 4.8 |
| F9 | Permission sloj (ASK) | Rizican tool zahteva potvrdu | 4.8 |
| F10 | Projects create/open | Novi projekat → settings override radi | 4.7 |
| F11 | Automation workflow | Pokrenuti ugrađeni system_check workflow | 4.8 |
| F12 | Voice STT/TTS test dugmad | Reprodukcija + snimak | 4.8b |
| F13 | Settings perzistencija | Promena teme/modela → restart → opstaje | 3.5, 4.9 |
| F14 | System tray | Minimizacija u tray + restore | 4.10 |
| F15 | Wizard prvi-run | (rename settings first_run.completed=false) → wizard teče svih 7 koraka | 5.x |
| F16 | Wizard: prava instalacija | Koraci rade stvarne akcije (folderi, provere) | 5.3 |
| F17 | Navigacija svih stranica | Svaka ruta iz sidebara otvara stranicu bez greške | 3.2, 4.x |
| F18 | Context panel podaci | Model/memorija/capabilities odražavaju stvarno stanje | 3.3, 3.4 |
| F19 | Topbar toggle | ☰ i Context dugmad skrivaju/prikazuju panele | 3.1 |
| F20 | Restart perzistencija | Ceo ciklus → restart → sve postavke/konverzacije tu | 8.4 |

## 4. Vizuelne provere (posle design koraka)

- Poređenje sa `Izgled Aplikaccije/` preview-ima (side-by-side)
- Palete: wizard ekran koristi installer paletu, app koristi workspace paletu — nema mešanja
- Nema hardkodiranih hex vrednosti van `ui/design/tokens.py` (grep provera u 2.1)
- Fontovi Segoe UI, veličine po design_system.md §4

## 5. Zabrane (anti-regresija pravila)

- NE brisati nijednu stranicu/funkcionalnu rutu iz MainWindow dok se ne preusmeri u AppShell
- NE menjati potpise javnih API-ja core/ai/ dok ne prođe smoke suite
- NE dirati `%LOCALAPPDATA%\OfflineAI\` ručno tokom testova (osim renames za wizard test)
- Svaki korak = commit (vidljiv diff; lakši rollback)
