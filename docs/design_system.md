# Design System — "Graphite + Emerald" (Zvanična tema)

**Izvor istine:** `Izgled Aplikaccije/*.py` (HTML preview-i + PySide6 workspace prototip)
**Namena:** Referenca za FAZU 2 (tokens.py / qss.py / components.py). Ništa u ovom dokumentu se ne izmišlja — sve je izvučeno iz preview fajlova.

---

## 1. Dva režima palete

Zvanični dizajn koristi **dve varijante** Graphite+Emerald teme:

| Režim | Gde se koristi | Površina | Emerald |
|---|---|---|---|
| **Installer/Wizard** (tamniji, zeleniji) | Welcome → Complete ekran čarobnjaka | `#151819` | `#1D8A68` |
| **Workspace** (svetliji) | Glavna aplikacija nakon instalacije | `#202326` | `#27C48A` |

Odluka (korak 2.4b): oba režima žive u `tokens.py`; wizard koristi installer režim, AppShell workspace režim.

---

## 2. Installer/Wizard paleta (kompletne vrednosti)

### Površine i borderi
| Uloga | Hex |
|---|---|
| Page background | `#0D1010` |
| Glavni surface (installer prozor) | `#151819` |
| Sidebar | `#111516` |
| Kartica | `#1C2221` |
| Tamna kartica | `#191F1E` |
| Border kartice | `#29302E` |
| Border sidebar-a | `#202624` |
| Border bottom trake | `#252B29` |
| Border inputa/sekundarne dugmadi | `#343C39` |
| Input pozadina | `#151819` |
| Hover sekundarne pozadine | `#202624`, `#29302E` |

### Emerald akcenti
| Uloga | Hex |
|---|---|
| Primarna boja (dugmad, logo, progress) | `#1D8A68` |
| Hover primarne | `#249E78` |
| Emerald tekst (current step, statusi) | `#62C7A3` |
| Success pozadina (✓ ikonice) | `#245846` |
| Success tekst | `#7DE0B7` |
| Success swatch | `#45B88A` |
| Logo tekst | `#E8FFF6` |
| Emerald tints | `rgba(29,138,104, 0.06–0.35)` |

### Tekst
| Uloga | Hex |
|---|---|
| Primarni | `#EDF3F0` |
| Sekundarni | `#A5AFAB` |
| Opisni | `#8C9692` |
| Muted | `#737D79` |
| Dark (neaktivni koraci) | `#59625F` |

### Status boje
| Status | Hex / rgba |
|---|---|
| Success | `#62C7A3` / tint `rgba(69,184,138,0.12)` |
| Warning | `#D6A24A` / tint `rgba(214,162,74,0.07–0.20)` / tekst `#AFA08A` |
| Error | `#D96565` |

---

## 3. Workspace paleta (glavna aplikacija)

| Uloga | Hex |
|---|---|
| `GRAPHITE` (glavni bg, topbar) | `#202326` |
| `GRAPHITE_LIGHT` (kartice, hover) | `#292D31` |
| `GRAPHITE_DARK` (sidebar, context panel) | `#181A1D` |
| `BORDER` | `#373C41` |
| `EMERALD` (primarna) | `#27C48A` |
| `EMERALD_DARK` (hover) | `#1E9D70` |
| `TEXT_PRIMARY` | `#F1F3F4` |
| `TEXT_SECONDARY` | `#A8AFB5` |
| `RED` | `#E35D6A` |
| `YELLOW` | `#D9B44A` |
| Tekst na primary dugmetu | `#101513` |

---

## 4. Tipografija

- **Font:** "Segoe UI" (celi dizajn)
- Wizard: naslovi 25–29px/500, opisi 11–14px, kartice-title 8px/uppercase/letter-spacing 0.4px, vrednosti 10px/600, dugmad 11px
- Workspace: `page_title` 22pt/600, `assistant_name` 16pt/600, `section_title` 12pt/600, telo 10pt
- Upozorenje: trenutni ThemeManager globalno postavlja 12pt — preveliko u odnosu na dizajn (ispravka u fazi 2)

---

## 5. Komponente (spisak za components.py)

| Komponenta | Spec |
|---|---|
| **Installer prozor** | 900×600, radius 12, senka `0 25px 70px rgba(0,0,0,0.55)` |
| **Sidebar (wizard)** | 245px, brand logo 42×42 radius 10 emerald, steps lista (default/completed/current stanja) |
| **Step stanja** | default tekst `#59625F`; completed `#A5AFAB` + ikonica `#245846`/`#7DE0B7` ✓; current `#62C7A3` + bg `rgba(29,138,104,0.12)` + ikonica `#1D8A68` bela |
| **Kartica** | bg `#1C2221`/`#191F1E`, border `#29302E`, radius 7–9 |
| **Badge** (RECOMMENDED) | bg `rgba(29,138,104,0.18)`, `#62C7A3`, 8px/700, letter-spacing 0.5 |
| **Status chip** | READY emerald / LIMITED warning `#D6A24A`, uppercase 9px, letter-spacing 0.4 |
| **Banner** (success/info/warning) | radius 8, tint pozadine 0.07–0.08 + border 0.18–0.35 |
| **Storage bar** | visina 4px, track `#29302E`, fill `#1D8A68` |
| **Progress bar** | visina 7px, radius 5, track `#29302E`, fill `#1D8A68`, procenat `#62C7A3` |
| **Spinner** | 27px krug, border 3px `#29302E`, top `#1D8A68`, spin 1s |
| **Install-step chipovi** | done: `#62C7A3` + border `rgba(29,138,104,0.35)`; active: tint 0.08 + border 0.55 |
| **Capability chip** | aktivan `rgba(29,138,104,0.14)`/`#62C7A3` "✓"; neaktivan `rgba(89,98,95,0.12)`/`#59625F` "✕" |
| **Primary dugme** | bg emerald, hover tamnije, weight 600, radius 6, padding 9×17–20 |
| **Secondary dugme** | transparentno, tekst `#A5AFAB`, border `#343C39` |
| **Disabled dugme** | bg `#202624`, `#59625F`, border `#29302E` |
| **Input** | bg `#151819`, border `#343C39`, radius 5; workspace: bg `#292D31`, border `#373C41` radius 7, focus border emerald |
| **Topbar** | bg GRAPHITE, border-bottom BORDER; ☰ + ime asistenta (12pt/600) + stretch + "● Local" (emerald, 600) + Context + ⚙ |
| **Sidebar (workspace)** | GRAPHITE_DARK, border-right; ime asistenta (13pt emerald), nav dugmad transparent radius 6 padding 10×12, hover GRAPHITE_LIGHT, selected: emerald tekst |
| **Context panel** | GRAPHITE_DARK, border-left; sekcije Assistant/AI Model/Capabilities/Memory + 🔒 privacy footer (emerald) |

---

## 6. Layout strukture

### Wizard (7 ekrana, 900×600)
`Welcome → System Check → AI Model → Locations → Summary → Installation → Complete`
- Levo sidebar 245px (brand + steps + "100% Offline" footer)
- Desno content (padding 30–42px) + bottom traka (verzija levo, dugmad desno)

### Workspace (1500×900)
- **Topbar** (puna širina)
- **QSplitter:** `[sidebar 240px | pages (QStackedWidget) | context 280px]`
- Sidebar nav: Home(🏠), Chat(💬), Memory(🧠), Knowledge(📚), Capabilities(🧩), Projects(🗂) + New Conversation + My Profile + Settings
- Context panel sekcije: Assistant (ime, "Balanced · Serbian"), AI Model (ime, "● Ready · GPU"), Capabilities lista, Memory ("N relevant memories"), footer "🔒 Local AI — Your data stays on this device"
- Chat strana: header (ime + ● Local AI), poruke (ime asistenta emerald, HTML), capability dugmad (📎 Files, 🖼 Vision, 🧠 Memory), input + ➤ send (55px, emerald, tekst `#101513`)

---

## 7. QSS selektori (objectName konvencija iz workspace prototipa)

`#topbar`, `#sidebar`, `#context_panel`, `#nav_button`, `#primary_button`, `#secondary_button`, `#status_local`, `#page_title`, `#section_title`, `#assistant_name`, `#assistant_card`, `#nav_list`

---

## 8. Stanje implementacije vs dizajn (gap sažetak)

| Oblast | Stanje | Šta treba |
|---|---|---|
| ThemeManager `grey_emerald`/`dark` | koristi wizard paletu, hardkodirano | izvodi iz tokens.py; dodati workspace režim |
| AppShell | strukturno veran (splitter, objectNames) ali hardkodirana workspace paleta, ignoriše ThemeManager | topbar, toggle dugmad, selected stanja, ThemeManager integracija |
| WelcomeWizard (1743 lin.) | sva 7 koraka implementirana, wizard paleta | dinamički step highlight, custom bottom bar, deljene komponente |
| home_page StatusCard | wizard paleta (`#1C2221`) | workspace paleta kartica (`#292D31`) |
| Deljene komponente | ne postoje (sve inline) | components.py biblioteka |
| main_window.py (1591 lin.) | arhitekturno drugačiji (statusbar, meni) | funkcionalnost migrira u AppShell (faza 4), ne stilizovati ga |
