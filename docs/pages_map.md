# Mapa stranica — AppShell rute (Faza 4, korak 4.1)

**Izvor:** `app/application_final.py` (`_build_pages`) + `ui/main_window.py` (legacy).
**Pravilo:** nijedna funkcionalna stranica se ne gubi — sve imaju rutu u AppShell-u.

## Aktivne rute u AppShell-u (13 + Home)

| Ruta | Widget | Sidebar sekcija | Legacy ekvivalent (MainWindow) | Funkcija |
|---|---|---|---|---|
| Home | `HomePage` | Primarna | — (nova) | Status hub, hero, quick actions |
| Assistant Hub | `AssistantHub` | — (samo navigator) | AssistantHub | Profil asistenta |
| Chat | `ChatWidget` | Primarna 💬 | ChatWidget + ConversationSidebar | Chat sa streamingom |
| Memory | `MemoryPage` | Primarna 🧠 | MemoryPage | Pregled/dodavanje sećanja |
| Knowledge | `KnowledgeDashboard` | Primarna 📚 | KnowledgeDashboard | Izvori znanja, RAG |
| Models | `ModelsPage` | ADVANCED 📦 | ModelsPage | Otkrivanje/aktivacija modela |
| Capabilities | `CapabilitiesPage` | Primarna 🧩 | CapabilitiesPage | Capability flagovi modela |
| Projects | `ProjectsPage` | Primarna 🗂 | ProjectsPage | Projekti/workspace-i |
| Agents | `AgentsPage` | ADVANCED 🤖 | AgentsPage | Kreiranje/putnja agenata |
| Tools | `ToolsPage` | ADVANCED 🔧 | ToolsPage | Registry alata, permissions |
| Voice | `VoicePage` | ADVANCED 🎤 | VoicePage | STT/TTS konfiguracija |
| Automation | `AutomationDashboard` | ADVANCED ⚡ | AutomationDashboard | Workflow-i, scheduler |
| Workflow | `WorkflowBuilder` | ADVANCED 🧪 | WorkflowBuilder | Workflow builder |
| Settings | `SettingsDialog` (dialog) | ⚙ dugme | SettingsDialog | Sve postavke |

## Sidebar grupisanje (iz app_shell.py)

- **Primarna:** Home, Chat, Memory, Knowledge, Capabilities, Projects
- **ADVANCED:** Models, Agents, Tools, Voice, Automation, Workflow
- **Dno:** 👤 My Profile (→ Settings), ⚙ Settings

## Odluke

- `SettingsDialog` ostaje dialog (po legacy dizajnu) — ⚙ u topbaru i sidebaru ga otvara kroz rutu "Settings" ako je u page listi (trenutno NIJE widget page — otvara se iz Menija). **TODO 4.9:** dodati Settings kao pravu stranicu.
- `main_original.py --test-runtime` ne dira UI (runtime acceptance test) — van mape.

## Status migracije (ažurira se kroz Fazom 4)

| Korak | Stranica | Stil po dizajnu | Funkcionalno u shell-u | Test |
|---|---|---|---|---|
| 4.2 | Chat | ⬜ | ✅ (radi iz Faze 1) | ⬜ |
| 4.3 | Memory | ⬜ | ✅ | ⬜ |
| 4.4 | Knowledge | ⬜ | ✅ | ⬜ |
| 4.5 | Models | ⬜ | ✅ | ⬜ |
| 4.6 | Capabilities | ⬜ | ✅ | ⬜ |
| 4.7 | Projects | ⬜ | ✅ | ⬜ |
| 4.8 | Agents/Tools/Automation/Workflow | ⬜ | ✅ | ⬜ |
| 4.8b | Voice | ⬜ | ✅ | ⬜ |
| 4.9 | Settings | ⬜ | ⚠️ dialog, ne stranica | ⬜ |
| 4.10 | SysTray/QThread | ➖ | ✅ (worker iz start()) | ⬜ |
