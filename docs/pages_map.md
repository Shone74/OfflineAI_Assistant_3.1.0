# Page Map — AppShell Routes (Phase 4, step 4.1)

**Source:** `app/application_final.py` (`_build_pages`) + `ui/main_window.py` (legacy).
**Rule:** no functional page is lost — all of them have a route in AppShell.

## Active routes in AppShell (13 + Home)

| Route | Widget | Sidebar section | Legacy equivalent (MainWindow) | Function |
|---|---|---|---|---|
| Home | `HomePage` | Primary | — (new) | Status hub, hero, quick actions |
| Assistant Hub | `AssistantHub` | — (navigator only) | AssistantHub | Assistant profile |
| Chat | `ChatWidget` | Primary 💬 | ChatWidget + ConversationSidebar | Chat with streaming |
| Memory | `MemoryPage` | Primary 🧠 | MemoryPage | Memory overview/addition |
| Knowledge | `KnowledgeDashboard` | Primary 📚 | KnowledgeDashboard | Knowledge sources, RAG |
| Models | `ModelsPage` | ADVANCED 📦 | ModelsPage | Model discovery/activation |
| Capabilities | `CapabilitiesPage` | Primary 🧩 | CapabilitiesPage | Model capability flags |
| Projects | `ProjectsPage` | Primary 🗂 | ProjectsPage | Projects/workspaces |
| Agents | `AgentsPage` | ADVANCED 🤖 | AgentsPage | Creating/managing agents |
| Tools | `ToolsPage` | ADVANCED 🔧 | ToolsPage | Tool registry, permissions |
| Voice | `VoicePage` | ADVANCED 🎤 | VoicePage | STT/TTS configuration |
| Automation | `AutomationDashboard` | ADVANCED ⚡ | AutomationDashboard | Workflows, scheduler |
| Workflow | `WorkflowBuilder` | ADVANCED 🧪 | WorkflowBuilder | Workflow builder |
| Settings | `SettingsDialog` (dialog) | ⚙ button | SettingsDialog | All settings |

## Sidebar grouping (from app_shell.py)

- **Primary:** Home, Chat, Memory, Knowledge, Capabilities, Projects
- **ADVANCED:** Models, Agents, Tools, Voice, Automation, Workflow
- **Bottom:** 👤 My Profile (→ Settings), ⚙ Settings

## Decisions

- `SettingsDialog` remains a dialog (per the legacy design) — ⚙ in the topbar and sidebar opens it via the "Settings" route if it is in the page list (currently NOT a widget page — it opens from the Menu). **TODO 4.9:** add Settings as a proper page.
- `main_original.py --test-runtime` does not touch the UI (runtime acceptance test) — outside the map.

## Migration status (updated throughout Phase 4)

| Step | Page | Design-compliant style | Functional in the shell | Test |
|---|---|---|---|---|
| 4.2 | Chat | ⬜ | ✅ (works from Phase 1) | ⬜ |
| 4.3 | Memory | ⬜ | ✅ | ⬜ |
| 4.4 | Knowledge | ⬜ | ✅ | ⬜ |
| 4.5 | Models | ⬜ | ✅ | ⬜ |
| 4.6 | Capabilities | ⬜ | ✅ | ⬜ |
| 4.7 | Projects | ⬜ | ✅ | ⬜ |
| 4.8 | Agents/Tools/Automation/Workflow | ⬜ | ✅ | ⬜ |
| 4.8b | Voice | ⬜ | ✅ | ⬜ |
| 4.9 | Settings | ⬜ | ⚠️ dialog, not a page | ⬜ |
| 4.10 | SysTray/QThread | ➖ | ✅ (worker from start()) | ⬜ |
