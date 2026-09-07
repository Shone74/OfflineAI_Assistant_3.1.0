# Design System — "Graphite + Emerald" (Official Theme)

**Source of truth:** `design_previews/*.py` (HTML previews + PySide6 workspace prototype)
**Purpose:** Reference for PHASE 2 (tokens.py / qss.py / components.py). Nothing in this document is invented — everything is extracted from the preview files.

---

## 1. Two palette modes

The official design uses **two variants** of the Graphite+Emerald theme:

| Mode | Where it is used | Surface | Emerald |
|---|---|---|---|
| **Installer/Wizard** (darker, greener) | Welcome → Complete wizard screens | `#151819` | `#1D8A68` |
| **Workspace** (lighter) | Main application after installation | `#202326` | `#27C48A` |

Decision (step 2.4b): both modes live in `tokens.py`; the wizard uses the installer mode, AppShell the workspace mode.

---

## 2. Installer/Wizard palette (complete values)

### Surfaces and borders
| Role | Hex |
|---|---|
| Page background | `#0D1010` |
| Main surface (installer window) | `#151819` |
| Sidebar | `#111516` |
| Card | `#1C2221` |
| Dark card | `#191F1E` |
| Card border | `#29302E` |
| Sidebar border | `#202624` |
| Bottom bar border | `#252B29` |
| Input/secondary button border | `#343C39` |
| Input background | `#151819` |
| Secondary hover background | `#202624`, `#29302E` |

### Emerald accents
| Role | Hex |
|---|---|
| Primary color (buttons, logo, progress) | `#1D8A68` |
| Primary hover | `#249E78` |
| Emerald text (current step, statuses) | `#62C7A3` |
| Success background (✓ icons) | `#245846` |
| Success text | `#7DE0B7` |
| Success swatch | `#45B88A` |
| Logo text | `#E8FFF6` |
| Emerald tints | `rgba(29,138,104, 0.06–0.35)` |

### Text
| Role | Hex |
|---|---|
| Primary | `#EDF3F0` |
| Secondary | `#A5AFAB` |
| Descriptive | `#8C9692` |
| Muted | `#737D79` |
| Dark (inactive steps) | `#59625F` |

### Status colors
| Status | Hex / rgba |
|---|---|
| Success | `#62C7A3` / tint `rgba(69,184,138,0.12)` |
| Warning | `#D6A24A` / tint `rgba(214,162,74,0.07–0.20)` / text `#AFA08A` |
| Error | `#D96565` |

---

## 3. Workspace palette (main application)

| Role | Hex |
|---|---|
| `GRAPHITE` (main bg, topbar) | `#202326` |
| `GRAPHITE_LIGHT` (cards, hover) | `#292D31` |
| `GRAPHITE_DARK` (sidebar, context panel) | `#181A1D` |
| `BORDER` | `#373C41` |
| `EMERALD` (primary) | `#27C48A` |
| `EMERALD_DARK` (hover) | `#1E9D70` |
| `TEXT_PRIMARY` | `#F1F3F4` |
| `TEXT_SECONDARY` | `#A8AFB5` |
| `RED` | `#E35D6A` |
| `YELLOW` | `#D9B44A` |
| Text on primary button | `#101513` |

---

## 4. Typography

- **Font:** "Segoe UI" (entire design)
- Wizard: titles 25–29px/500, descriptions 11–14px, card titles 8px/uppercase/letter-spacing 0.4px, values 10px/600, buttons 11px
- Workspace: `page_title` 22pt/600, `assistant_name` 16pt/600, `section_title` 12pt/600, body 10pt
- Warning: the current ThemeManager globally sets 12pt — too large relative to the design (fix in phase 2)

---

## 5. Components (list for components.py)

| Component | Spec |
|---|---|
| **Installer window** | 900×600, radius 12, shadow `0 25px 70px rgba(0,0,0,0.55)` |
| **Sidebar (wizard)** | 245px, brand logo 42×42 radius 10 emerald, steps list (default/completed/current states) |
| **Step states** | default text `#59625F`; completed `#A5AFAB` + icon `#245846`/`#7DE0B7` ✓; current `#62C7A3` + bg `rgba(29,138,104,0.12)` + icon `#1D8A68` white |
| **Card** | bg `#1C2221`/`#191F1E`, border `#29302E`, radius 7–9 |
| **Badge** (RECOMMENDED) | bg `rgba(29,138,104,0.18)`, `#62C7A3`, 8px/700, letter-spacing 0.5 |
| **Status chip** | READY emerald / LIMITED warning `#D6A24A`, uppercase 9px, letter-spacing 0.4 |
| **Banner** (success/info/warning) | radius 8, bg tint 0.07–0.08 + border 0.18–0.35 |
| **Storage bar** | height 4px, track `#29302E`, fill `#1D8A68` |
| **Progress bar** | height 7px, radius 5, track `#29302E`, fill `#1D8A68`, percentage `#62C7A3` |
| **Spinner** | 27px circle, border 3px `#29302E`, top `#1D8A68`, spin 1s |
| **Install-step chips** | done: `#62C7A3` + border `rgba(29,138,104,0.35)`; active: tint 0.08 + border 0.55 |
| **Capability chip** | active `rgba(29,138,104,0.14)`/`#62C7A3` "✓"; inactive `rgba(89,98,95,0.12)`/`#59625F` "✕" |
| **Primary button** | emerald bg, darker hover, weight 600, radius 6, padding 9×17–20 |
| **Secondary button** | transparent, text `#A5AFAB`, border `#343C39` |
| **Disabled button** | bg `#202624`, `#59625F`, border `#29302E` |
| **Input** | bg `#151819`, border `#343C39`, radius 5; workspace: bg `#292D31`, border `#373C41` radius 7, focus border emerald |
| **Topbar** | bg GRAPHITE, border-bottom BORDER; ☰ + assistant name (12pt/600) + stretch + "● Local" (emerald, 600) + Context + ⚙ |
| **Sidebar (workspace)** | GRAPHITE_DARK, border-right; assistant name (13pt emerald), nav buttons transparent radius 6 padding 10×12, hover GRAPHITE_LIGHT, selected: emerald text |
| **Context panel** | GRAPHITE_DARK, border-left; sections Assistant/AI Model/Capabilities/Memory + 🔒 privacy footer (emerald) |

---

## 6. Layout structures

### Wizard (7 screens, 900×600)
`Welcome → System Check → AI Model → Locations → Summary → Installation → Complete`
- Left sidebar 245px (brand + steps + "100% Offline" footer)
- Right content (padding 30–42px) + bottom bar (version on the left, buttons on the right)

### Workspace (1500×900)
- **Topbar** (full width)
- **QSplitter:** `[sidebar 240px | pages (QStackedWidget) | context 280px]`
- Sidebar nav: Home(🏠), Chat(💬), Memory(🧠), Knowledge(📚), Capabilities(🧩), Projects(🗂) + New Conversation + My Profile + Settings
- Context panel sections: Assistant (name, "Balanced · Serbian"), AI Model (name, "● Ready · GPU"), Capabilities list, Memory ("N relevant memories"), footer "🔒 Local AI — Your data stays on this device"
- Chat page: header (name + ● Local AI), messages (assistant name in emerald, HTML), capability buttons (📎 Files, 🖼 Vision, 🧠 Memory), input + ➤ send (55px, emerald, text `#101513`)

---

## 7. QSS selectors (objectName convention from the workspace prototype)

`#topbar`, `#sidebar`, `#context_panel`, `#nav_button`, `#primary_button`, `#secondary_button`, `#status_local`, `#page_title`, `#section_title`, `#assistant_name`, `#assistant_card`, `#nav_list`

---

## 8. Implementation state vs design (gap summary)

| Area | State | What is needed |
|---|---|---|
| ThemeManager `grey_emerald`/`dark` | uses the wizard palette, hardcoded | derive from tokens.py; add the workspace mode |
| AppShell | structurally faithful (splitter, objectNames) but hardcoded workspace palette, ignores ThemeManager | topbar, toggle buttons, selected states, ThemeManager integration |
| WelcomeWizard (1743 lines) | all 7 steps implemented, wizard palette | dynamic step highlight, custom bottom bar, shared components |
| home_page StatusCard | wizard palette (`#1C2221`) | workspace card palette (`#292D31`) |
| Shared components | do not exist (all inline) | components.py library |
| main_window.py (1591 lines) | architecturally different (statusbar, menu) | migrate functionality into AppShell (phase 4), do not style it |
