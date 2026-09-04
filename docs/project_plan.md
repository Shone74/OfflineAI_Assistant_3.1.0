# Project Plan — Redizajn Offline AI Assistant

**Verzija plana:** 1.0
**Datum kreiranja:** 2026-09-04
**Cilj:** Redizajn aplikacije prema referentnom dizajnu iz `Izgled Aplikaccije/` uz **nultu regresiju funkcionalnosti** — sve što danas radi mora nastaviti da radi kroz celu aplikaciju.

---

## 0. Reference

| Šta | Gde |
|---|---|
| Dizajn preview-i (HTML/Python) | `Izgled Aplikaccije/` — 9 fajlova |
| Glavni workspace dizajn (PySide6) | `Izgled Aplikaccije/assistant_workspace_preview.py` |
| Zvanična tema spec | `Izgled Aplikaccije/official_theme_preview.py` |
| Izveštaj o dizajn sistemu | `docs/design_system.md` |
| Izveštaj o modelima | `docs/models_report.md` |
| Trenutni status | `docs/current_status.md` |

---

## 1. Faze plana (mapa koraka)

Svaka faza se sastoji od koraka. Korak je završen tek kad je verifikovan (vidi §3). Status se ažurira u `docs/current_status.md` nakon svakog uspešno rešenog koraka.

---

### FAZA 0 — Priprema i sigurnosna mreža (čini regresiju nemogućom)

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 0.1 | Postavljanje git repozitorijuma | `git init`, početni commit celog projekta (bez `__pycache__`, `.pytest_cache`, `models/llm/*.gguf` — dodati `.gitignore`). Svaka faza = grananja/pod-grananje sa commit-ima po koraku. | `git log` pokazuje početno stanje |
| 0.2 | Instalacija zavisnosti u Python 3.11 env | `scipy`, `nvidia-ml-py3` (nedostaju u 3.11 pip listu); pytest+pytest-qt postoje. `llama-cpp-python 0.3.35` već instaliran. | `pip check` čist; `python -c "import llama_cpp, PySide6, scipy"` |
| 0.3 | Baseline test suite — snimanje "zlatnog stanja" | Napisati regression smoke suite: pokretanje headless (`QT_QPA_PLATFORM=offscreen`, `OFFLINE_AI_TEST_MODE=1`) + postojećih 9 testova + novih smoke testova za Assistant, ModelManager, memory, RAG, tools (stub engine). Snimiti baseline izlaz u `docs/baseline/`. | Svi baseline testovi prolaze; baseline fajl postoji |
| 0.4 | Verifikacija buga `NameError` u launcheru | Dokumentovati tačno ponašanje `run.py` → `application_final.main()` (`navigator` nije u scope-u). Rešenje je u 1.1. | Reprodukcija greške zabeležena u statusu |
| 0.5 | Provera postavki `settings.json` | `models_dir` trenutno `E:/models`, `model_search_paths` samo AppData. Uskladiti sa novim rasporedom (vidi models_report §3). | Settings validan, modeli se otkrivaju |

---

### FAZA 1 — Stabilizacija launchera i uklanjanje kritičnih bugova

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 1.1 | Popravka `application_final.py` | `navigator` se definisao lokalno u `main()`, a koristi u `_build_pages()` (linije 43, 50, 51) → NameError. Refaktor: `_build_pages(manager, navigator)`. | `run.py` pokreće aplikaciju bez exception-a |
| 1.2 | Uklanjanje double-boot obrasca | `manager.start()` kreira i prikazuje MainWindow, pa ga final bootstrap odmah zatvara. Prepraviti bootstrap tako da se MainWindow NE prikazuje kad je AppShell aktivan (parametar show_window=False ili novi bootstrap path bez starog prozora). | Pri startu se vidi samo jedan prozor; nema treperenja |
| 1.3 | Ujednačavanje entry pointa | pyproject script → `app.application_final:main`, run.py → isto. Ukloniti konflikt. | `python run.py` i `offline-ai-final` rade identično |
| 1.4 | Usklađivanje requirements.txt | Dodati: `requests`, `pywin32` (Windows marker), opciono `openwakeword`, `faiss-cpu`, `sentence-transformers`, `croniter` kao opciona proširenja (odvojiti requirements-dev.txt: pytest, pytest-qt, ruff, mypy). | `pip install -r requirements.txt` dovoljno za pun rad |
| 1.5 | Eksplicitna Python verzija | Kod je testiran na 3.11.9 (sve zavisnosti rade), pyproject traži >=3.13 (na 3.14 fali llama-cpp). Odluka: requires-python `>=3.11` uz dokumentaciju da je 3.11 verified. | pyproject/README usklađeni |

---

### FAZA 2 — Design system (temelj redizajna)

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 2.1 | Kreiranje `ui/design/tokens.py` | Sve hex vrednosti iz design_system.md kao Python konstante: `GRAPHITE`, `GRAPHITE_LIGHT`, `GRAPHITE_DARK`, `EMERALD`, `EMERALD_DARK`, `TEXT_PRIMARY`, `TEXT_SECONDARY`, `BORDER`, `RED`, `YELLOW`, + wizard nijanse (#151819, #1D8A68, #62C7A3...) i rgba tint formule. JEDAN izvor istine za sve boje. | Import modula radi; nema hardkodiranih hex vrednosti van tokens.py (grep provera) |
| 2.2 | Kreiranje QSS builder biblioteke `ui/design/qss.py` | Funkcije koje generišu QSS za: topbar, sidebar, context panel, nav_button, primary/secondary/disabled dugmad, kartice, inpute, badge-e, chipove, banner-e, progress bar, spinner. | Unit test: generisani QSS sadrži sve selektore |
| 2.3 | Komponente `ui/design/components.py` | Reusable Qt widgeti: `Card`, `Badge`, `StatusChip`, `Banner`, `StorageBar`, `InstallStepChips`, `Spinner`, `CapabilityChip`, `StepIndicator` (za wizard sidebar). | Widget testovi (kreiranje, API, stil) |
| 2.4 | Integracija ThemeManager ↔ design tokens | ThemeManager postaje jedini applier QSS-a; `grey_emerald` (workspace) i `dark` (installer) palete iz tokens.py; ukloniti hardkodirane palete iz app_shell.py i welcome_wizard.py. | Promena teme menja izgled celog app-a |
| 2.4b | Odluka o dve palete | Zvanični dizajn sadrži tamniji wizard režim (#151819/#1D8A68) i svetliji workspace režim (#202326/#27C48A). Odluka: zadržati obe — installer/wizard koristi tamniju, glavni app svetliju — oba iz tokens.py. | Obe palete definisane u tokens.py |

---

### FAZA 3 — Redizajn AppShell (glavni prozor)

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 3.1 | Topbar | ☰ (toggle sidebar), ime asistenta, stretch, "● Local" status, "Context" (toggle context panela), ⚙ Settings — po workspace dizajnu. Zastavice `_sidebar_visible`/`_context_visible` konačno dobijaju dugmad. | Klik na ☰/Context radi toggle; status ● Local vidljiv |
| 3.2 | Sidebar sa selected stanjem | Hover + selected indikator (emerald tekst/akcenat) na trenutnoj stranici; "+ New Conversation" i "👤 My Profile" na dnu; navigacija prema dizajnu (emoji ikonice). | Vizuelna provera + navigacija svih stranica radi |
| 3.3 | Context panel | Sekcije: Assistant (ime + "Balanced · Serbian"), AI Model (ime + ● Ready · GPU), Capabilities (✓ lista), Memory (broj relevantnih), privacy footer 🔒. Povezati na stvarne Assistant podatke. | Panel prikazuje stvarne podatke modela/memorije |
| 3.4 | Status integracija (EventBus) | Model load/unload, memory promene, generation events → context panel i statusne label-e putem EventBus-a (bez direktnih referenci). | Simulacija event-a menja panel |
| 3.5 | AppShell ↔ ThemeManager | AppShell prestaje da koristi hardkodirani QSS; sve iz qss.py builder-a; reakcija na promenu teme. | Promena teme iz Settings radi na celom shell-u |
| 3.6 | Home/AssistantHub strana | "Your Assistant" hero kartica sa ✦, status, "Start Conversation" (primary) → navigacija na Chat; "Assistant Snapshot" 2×2 grid; "Quick Actions" 2×2 grid — po dizajnu. | Klik na akcije navigira ispravno |

---

### FAZA 4 — Migracija stranica na AppShell

Cilj: sve funkcionalne stranice rade unutar novog shell-a. Ni jedna stranica se ne gubi — samo se preusmeravaju u AppShell.

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 4.1 | Popis stranica i mapa rute | Popisati sve stranice iz MainWindow (13 stranica) i mapirati na AppShell rute: Home, Assistant Hub, Chat, Memory, Knowledge, Models, Capabilities, Projects, Agents, Tools, Voice, Automation, Workflow + Settings. Identifikovati stranice koje dizajn nema (Agents, Tools, Voice, Automation, Workflow, Models) — odluka: zadržati ih kao "napredne" (vidljive u sidebar-u) jer je funkcionalnost obavezna. | Mapa ruta u status dokumentu; nijedna funkcija nije izgubljena |
| 4.2 | Chat u shell-u | ChatWidget funkcionalnost (streaming, conversation history, tool pozivi) preneti u AppShell Chat stranicu workspace layout-a (header, poruke, capability dugmad 📎 Files / 🖼 Vision / 🧠 Memory, input + send ➤). | Chat radi streaming sa stvarnim modelom (Qwen2.5-Coder) |
| 4.3 | Memory strana | Lista sećanja + "Add Memory" / "Forget Selected" po dizajnu; povezano na MemoryManager. | Dodavanje/brisanje sećanja radi i perzistira |
| 4.4 | Knowledge strana | Lista izvora + "+ Add Knowledge Source"; RAG indeksiranje radi; pretraga iz chata (KnowledgeSearchTool) radi. | Indeksiranje + pretraga testirani |
| 4.5 | Models strana | Otkrivanje, aktivacija, GPU info; prikaz izabranih modela (Qwen2.5-Coder-7B primarni, Phi-4-mini sekundarni). | Aktivacija modela radi; VRAM info tačan |
| 4.5b | Vision odluka | Qwen2.5-VL je VISION_LLM ali multimodalna inferencija NIJE implementirana u pipeline-u. Odluka: ne koristiti VL model za sada; 🖼 Vision dugme u chatu skrati/označi kao "coming soon" (NE implementirati polu-rešenje). | Dugme onemogućeno/označeno |
| 4.6 | Capabilities strana | Checkbox redovi (Text, Programming, Vision, Documents, Voice, Automation) povezani na stvarne capability flagove modela. | Oznake odgovaraju stvarnim flagovima |
| 4.7 | Projects strana | Lista projekata + "+ New Project"; ProfileStack override radi. | Kreiranje/otvaranje projekta radi |
| 4.8 | Agents / Tools / Automation / Workflow | Prebaciti kao-funkcionalno u AppShell (stranice postoje, preusmeriti na nove komponente tek u Fazi 5). Odrediti im mesto u sidebar-u (sekcija "Advanced"). | Sve 4 stranice dostupne i funkcionalne |
| 4.8b | Voice strana | VoicePage funkcionalnost (STT/TTS konfiguracija, test dugmad) u novom dizajnu. | Konfiguracija perzistira; test reprodukcije radi |
| 4.9 | Settings | QComboBox tabovi (General, Assistant, AI/Model, Privacy & Data) po dizajnu; spojiti postojeću SettingsDialog funkcionalnost. | Sve postojeće postavke dostupne |
| 4.10 | Penjanje QThread/SysTray | System tray, shortcut-ovi i QThread workeri iz MainWindow moraju preživeti migraciju (tray ikona, model load worker, generation worker). | Tray radi; model load u pozadini radi |

---

### FAZA 5 — Wizard redizajn (instalacioni tok)

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 5.1 | Dinamički step indikator | WelcomeWizard sidebar: koraci dobijaju completed/current stanja pri promeni stranice (trenutno svi izgledaju isto). STEP_COMPLETED_STYLE/STEP_CURRENT_STYLE već postoje — samo ih povezati. | Prelazak koraka menja sidebar |
| 5.2 | Custom bottom bar | Umesto standardnih QWizard dugmadi: bottom traka sa verzijom levo (v1.2.0 → verzija aplikacije) i Back/Next/Cancel/Install dugmadima po dizajnu. | Vizuelna provera |
| 5.3 | Prava instalacija umesto simulacije | InstallationPage QTimer simulaciju zameniti stvarnim koracima: provera foldera (app/models), kopiranje/verifikacija modela (checksum) gde je primenljivo, kreiranje config struktura. Model download ostaje opcion (modeli su lokalni). | Wizard završava sa stvarno spremnom instalacijom |
| 5.4 | Wizard + design system | Wizard prelazi na tokens.py + qss.py + components.py (ukloniti internu WIZARD_STYLE paletu — dupliranje). | Wizard koristi deljene komponente |

---

### FAZA 6 — Model integracija i poboljšanja

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 6.1 | Aktivacija Qwen2.5-Coder-7B kao primarni model | Model kopiran u `models/llm/` (4.36 GB, Q4_K_M, arch qwen2, tool_calling ✓). Settings: `models_dir` → `models/llm` (project-relative dev mode) ili ostaviti E:/models + search_paths. GPU: auto layers (svi slojevi na RTX 3080, model 4.36GB < 10GB VRAM). | Chat sa stvarnim modelom radi; GPU offload potvrđen (nvidia-smi tokom generacije) |
| 6.2 | Phi-4-mini kao lagani rezervni | Drugi kopirani model (3.08 GB, Q6_K_L) — dostupan za brze odgovore / low-VRAM scenario. | Aktivacija oba modela radi (uzajamno isključenje poznatog ograničenja) |
| 6.3 | Podešavanje inference parametara | `n_ctx` 512 → 4096 (Qwen2.5 podržava 32k; 4k balans za VRAM), `max_tokens` 204 → 1024, n_threads 4 → 8 (fizički jezgara) ili 16. | Odgovori nisu seckani; kontekst drži celu konverzaciju |
| 6.3b | Reset loših postavki | `model_name: "qwen-7b"` ne odgovara nijednom otkrivenom modelu — očistiti da se koristi default discovery (pick_default_model) ili eksplicitno "Qwen2.5-Coder-7B". | Postavke konzistentne sa otkrivenim modelima |
| 6.4 | Embeddings za memoriju/RAG (opciono) | `memory.embedding_model: "stub"` — razmotriti dodavanje embedding modela iz E:\models nema validnog kandidata (mmproj je PROJECTOR, ne EMBEDDING) → zadržati stub ili dodati bge-micro GGUF kasnije. | Zabeležena odluka u statusu |

---

### FAZA 7 — Glas (voice) funkcionalnost (opciona, po dizajnu dizajnirana kao secondary)

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 7.1 | STT with faster-whisper | Model "base" u `models/voice/stt/`; language sr (postavka postoji). Test: snimljeni WAV → tekst. | Transkripcija radi |
| 7.2 | TTS pyttsx3 | Voice postavka Hazel EN-GB postoji; za srpski skinuti dostupne SAPI glasove. | Reprodukcija radi |
| 7.3 | Wake word (opciono) | openwakeword nije u requirements; stub fallback postoji. Ostaviti stub. | Zabeleženo |

---

### FAZA 8 — Čišćenje i završetak

| # | Korak | Detalji | Verifikacija |
|---|---|---|---|
| 8.1 | Uklanjanje dead weight | Odlučiti sudbinu: praznih foldera (assets/, data/, config/ itd. — zadržati uz .gitignore), `Izgled Aplikaccije/` (zadržati kao dizajn referencu), `main_original.py` (zadržati za --test-runtime), dupliran settings mehanizam (ConfigManager kao primaran). | Struktura čista, dokumentovano |
| 8.2 | Typo fix "Izgled Aplikaccije" | Preimenovati folder u "Izgled Aplikacije" ili zadržati (putanje u docs moraju odražavati stvarno ime). Odluka: zadržati ime, dokumentovati. | Dokumentovano |
|  Izgled | — | — | — |
| 8.3 | Ažuriranje README/START_HERE | Nove upute, hardverski zahtevi, model setup (models/llm), dizajn dokumentacija. | README tačan |
| 8.4 | Finalno testiranje E2E | Pun ciklus: wizard → chat sa stvarnim modelom → memorija → knowledge → voice → settings → restart perzistencija. | E2E checklist green |
| 8.5 | Lint + typecheck | ruff (line-length 100, py313→py311 target), mypy (3.11). | ruff/mypy čisti (tolerancija za legacy) |

---

## 2. Redosled izvršavanja (zavisnosti)

```
FAZA 0 (sigurnosna mreža)
  └─→ FAZA 1 (stabilizacija launcher-a)  ← blokira SVE
        └─→ FAZA 2 (design system)       ← blokira 3, 4, 5
              ├─→ FAZA 3 (AppShell redizajn)
              │     └─→ FAZA 4 (migracija stranica) ← duža faza
              │           └─→ FAZA 6 (modeli) — može i ranije, nezavisno od UI faza
              └─→ FAZA 5 (wizard)
  FAZA 7 (voice) — nezavisna, može paralelno od faze 4
FAZA 8 (čišćenje) — na kraju svega
```

Ključno pravilo: **modeli (6.1–6.3) mogu se aktivirati odmah nakon faze 1** za testiranje chata tokom razvoja UI faza.

---

## 3. Pravila verifikacije (definition of done)

Svaki korak mora:
1. Prolaziti ceo test suite (baseline + novi testovi) — **nula regresija**.
2. Biti testiran headless: `QT_QPA_PLATFORM=offscreen`, `OFFLINE_AI_TEST_MODE=1`.
3. Biti testiran sa stvarnim modelom gde je primenljivo (chat, streaming, GPU).
4. Ažurirati `docs/current_status.md` (status, datum, dokaz).
5. Commit po koraku sa opisom faze/koraka.

Test komande:
```powershell
# Headless test suite
$env:QT_QPA_PLATFORM="offscreen"; $env:OFFLINE_AI_TEST_MODE="1"
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" -m pytest tests/ -v

# Stvarni model smoke test
& "C:\Users\Bota\AppData\Local\Programs\Python\Python311\python.exe" main_original.py --test-runtime
```

---

## 4. Rizici i mitigacije

| Rizik | Verovatnoća | Mitigacija |
|---|---|---|
| llama-cpp-python na 3.14 ne postoji | Visok (potvrđeno) | Koristiti Python 3.11.9 (verified env) za razvoj i testove |
| Regresija Assistant funkcionalnosti pri migraciji UI | Srednji | Faza 0 baseline suite + migracija "kao-funkcionalno" pa stilizovanje (4.8) |
| Vision (Qwen2.5-VL) ne radi multimodalno | Potvrđeno (izveštaj) | Ne koristiti VL model; Vision dugme označiti "coming soon" |
| Oba modela u VRAM istovremeno ne mogu | Sigurno (4.36+3.08>10 ali pojedinačno OK) | Aktivacija jednog u datom trenutku (postojeće ograničenje) |
| Wizard instalacija piše po vanjskim diskovima | Nizak | Wizard koristi project/AppData foldere |
| Dve palete prave nedoslednost | Srednji | Faza 2 tokens.py — jedan izvor istine |
