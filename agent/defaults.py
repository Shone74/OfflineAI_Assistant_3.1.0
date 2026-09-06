"""Built-in specialized agents — seeded on first run.

These agents cover the most common assistant use-cases so a fresh
installation is immediately useful.  Each agent is persisted through
:class:`agent.repository.AgentRepository` (SQLite ``agents`` table) only
when its name does not already exist — user edits are never overwritten.

Every definition follows the same contract the AgentEditorDialog produces:
``name``, ``description``, ``system_prompt``, ``model_name`` (empty string
means "use the active model"), ``enabled``, ``tool_whitelist`` (``None``
means "all tools allowed") and ``permission_profile``.
"""

from __future__ import annotations

from typing import Any

from core.logger import get_logger

logger = get_logger("agent.defaults")

# Tool names that exist in the default registry (tools/*):
#   read_file, search_files, list_directory, file_metadata, write_file,
#   create_directory, copy_file, move_file, delete_file,
#   calculate, date_time, clipboard_read, clipboard_write,
#   system_info, process_info, open_application, search_knowledge

BUILTIN_AGENTS: list[dict[str, Any]] = [
    {
        "name": "Researcher",
        "description": (
            "Searches, consolidates and summarizes information from the local "
            "knowledge base and files. Ideal for research questions and "
            "material preparation."
        ),
        "system_prompt": (
            "You are the Researcher agent. Locate relevant information using "
            "the knowledge base and file tools, then produce a clear, "
            "structured summary with sources. If information is missing, say "
            "so explicitly instead of guessing. Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["search_knowledge", "search_files", "read_file",
                           "list_directory", "file_metadata", "date_time"],
        "permission_profile": "default",
    },
    {
        "name": "Writer",
        "description": (
            "Writes and polishes texts — emails, documents, announcements, "
            "drafts. Adjusts tone and length on request."
        ),
        "system_prompt": (
            "You are the Writer agent. Draft and refine text with correct "
            "grammar, consistent tone and a clear structure. Ask for the "
            "target audience and format when unclear. Respond in the user's "
            "language; keep the user's language in the produced text."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": None,  # all tools (clipboard for transferring text)
        "permission_profile": "default",
    },
    {
        "name": "Coder",
        "description": (
            "Helps with programming — writes, explains and reviews code, "
            "reads files from disk and gives concrete change suggestions."
        ),
        "system_prompt": (
            "You are the Coder agent. Read the relevant source files before "
            "answering, propose minimal precise changes, and prefer complete "
            "working code blocks over prose. Point out edge cases and tests. "
            "Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["read_file", "search_files", "list_directory",
                           "file_metadata", "write_file", "calculate",
                           "date_time"],
        "permission_profile": "default",
    },
    {
        "name": "Analyst",
        "description": (
            "Analyzes data and numbers — calculates, compares and turns "
            "raw results into clear conclusions."
        ),
        "system_prompt": (
            "You are the Analyst agent. Break the request into measurable "
            "steps, use the calculate tool for exact arithmetic, and present "
            "conclusions with the reasoning behind them. Quantify uncertainty "
            "where relevant. Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["calculate", "date_time", "search_knowledge",
                           "read_file", "search_files"],
        "permission_profile": "default",
    },
    {
        "name": "File Manager",
        "description": (
            "Organizes files and folders — finds, copies, moves and "
            "shows directory contents."
        ),
        "system_prompt": (
            "You are the File Manager agent. Locate files and directories, "
            "report their metadata clearly, and perform file operations only "
            "after confirming the exact paths with the user. Never guess a "
            "path — search for it first. Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["search_files", "list_directory", "file_metadata",
                           "read_file", "copy_file", "move_file",
                           "create_directory"],
        "permission_profile": "default",
    },
    {
        "name": "System Monitor",
        "description": (
            "Monitors system state — CPU, memory, processes — and gives "
            "optimization recommendations."
        ),
        "system_prompt": (
            "You are the System Monitor agent. Gather system information "
            "with the system and process tools, highlight anomalies, and "
            "suggest concrete next steps. Keep readings factual, never "
            "speculative. Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["system_info", "process_info", "date_time"],
        "permission_profile": "default",
    },
    {
        "name": "Planner",
        "description": (
            "Breaks complex goals down into clear steps and coordinates "
            "execution with the assistant's other tools."
        ),
        "system_prompt": (
            "You are the Planner agent. Decompose the goal into a short "
            "ordered list of concrete, verifiable steps, note which ones need "
            "tools or user confirmation, and identify risks. Keep the plan "
            "realistic in scope. Respond in the user's language."
        ),
        "model_name": "",
        "enabled": True,
        "tool_whitelist": ["date_time", "search_knowledge", "search_files"],
        "permission_profile": "default",
    },
]


def seed_builtin_agents(repository: Any) -> int:
    """Persist the built-in agents that do not exist yet.

    Returns the number of agents created (0 when everything already
    exists or the repository is unavailable).  Never raises — seeding is
    best-effort so application startup cannot fail because of it.
    """
    if repository is None:
        return 0
    created = 0
    from database.models import Agent

    for spec in BUILTIN_AGENTS:
        try:
            if repository.get_agent_by_name(spec["name"]) is not None:
                continue
            repository.create_agent(
                Agent(
                    name=spec["name"],
                    description=spec["description"],
                    system_prompt=spec["system_prompt"],
                    model_name=spec["model_name"],
                    enabled=spec["enabled"],
                    tool_whitelist=list(spec["tool_whitelist"])
                    if spec["tool_whitelist"] is not None
                    else None,
                    permission_profile=spec["permission_profile"],
                )
            )
            created += 1
            logger.info("Seeded built-in agent: %s", spec["name"])
        except Exception:
            logger.debug("Could not seed agent %s", spec.get("name"), exc_info=True)
    if created:
        logger.info("Seeded %d built-in agent(s)", created)
    return created
