"""Planner — turns a goal into an ordered list of :class:`Task` objects.

Two implementations ship with the stub engine:
    * :class:`StubPlanner`     — keyword → tool map (zero dependencies)
    * :class:`LLMPlanner`      — asks the LLM engine; degrades to ``StubPlanner``
                                when the engine is missing or the output is malformed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from agent.task import Task
from core.logger import get_logger

if TYPE_CHECKING:
    from ai.engine.llm_engine import GenerationConfig, LLMEngine
    from tools.base import ToolRegistry


_SYSTEM_TOOL_KEYWORDS = {
    "system_info": ("specifikacija", "kakav računar", "system info", "info o sistemu"),
    "open_application": ("otvori", "start", "pokreni", "launch"),
    "read_file": ("pročitaj", "procitaj", "read file", "otvori fajl"),
    "search_files": ("pretraži", "pretrazi", "search files", "pronađi"),
}


logger = get_logger("agent.planner")


class Planner:
    """Abstract planner interface."""

    def __init__(
        self, tool_registry: ToolRegistry | None = None, system_prompt: str = "",
        tool_whitelist: list[str] | None = None, memory_context: str = "",
        knowledge_context: str = "", project_context: str = "",
        profile: dict | None = None,
    ) -> None:
        self._tool_registry = tool_registry
        self._system_prompt = system_prompt
        self._tool_whitelist = tool_whitelist
        self._memory_context = memory_context
        self._knowledge_context = knowledge_context
        self._project_context = project_context
        self._profile = profile if profile is not None else {}

    @property
    def tool_registry(self) -> ToolRegistry | None:
        return self._tool_registry

    @property
    def system_prompt(self) -> str:
        return self._system_prompt

    @property
    def tool_whitelist(self) -> list[str] | None:
        return self._tool_whitelist

    @tool_whitelist.setter
    def tool_whitelist(self, value: list[str] | None) -> None:
        self._tool_whitelist = value

    @property
    def memory_context(self) -> str:
        return self._memory_context

    @memory_context.setter
    def memory_context(self, value: str) -> None:
        self._memory_context = value

    @property
    def knowledge_context(self) -> str:
        return self._knowledge_context

    @knowledge_context.setter
    def knowledge_context(self, value: str) -> None:
        self._knowledge_context = value

    @property
    def project_context(self) -> str:
        return self._project_context

    @project_context.setter
    def project_context(self, value: str) -> None:
        self._project_context = value

    @property
    def profile(self) -> dict | None:
        return self._profile

    @profile.setter
    def profile(self, value: dict | None) -> None:
        self._profile = value if value is not None else {}

    def plan(self, goal: str, max_tasks: int = 8) -> list[Task]:
        raise NotImplementedError


class StubPlanner(Planner):
    """Rule-based planner — maps goal keywords to known tool calls."""

    def __init__(self, tool_registry: ToolRegistry | None = None, profile: dict | None = None, system_prompt: str = "", tool_whitelist: list[str] | None = None, memory_context: str = "", knowledge_context: str = "", project_context: str = "") -> None:
        super().__init__(tool_registry=tool_registry, system_prompt=system_prompt, tool_whitelist=tool_whitelist, memory_context=memory_context, knowledge_context=knowledge_context, project_context=project_context, profile=profile)

    def plan(self, goal: str, max_tasks: int = 8) -> list[Task]:
        lowered = goal.lower()
        tasks: list[Task] = []

        def _match(tool_name: str) -> bool:
            return any(kw in lowered for kw in _SYSTEM_TOOL_KEYWORDS[tool_name])

        if _match("system_info"):
            tasks.append(Task.of("Prikaži sistemske informacije", tool_name="system_info"))
            return tasks[:max_tasks]

        if _match("open_application"):
            app = self._extract_app(lowered)
            tasks.append(
                Task.of(f"Otvori {app}", tool_name="open_application", params={"program": app})
            )
            return tasks[:max_tasks]

        if _match("read_file"):
            path = self._extract_path(lowered)
            if path:
                tasks.append(
                    Task.of(f"Pročitaj {path}", tool_name="read_file", params={"path": path})
                )
            return tasks[:max_tasks]

        if _match("search_files"):
            pattern, directory = self._extract_search(lowered)
            tasks.append(
                Task.of(
                    f"Pretraži {pattern}",
                    tool_name="search_files",
                    params={"pattern": pattern, "directory": directory},
                )
            )
            return tasks[:max_tasks]

        # Fallback: no tool matches → a plain conversational step.
        desc = goal.strip().rstrip("?")[:80] or "Odgovori na pitanje"
        tasks.append(Task.of(desc))
        return tasks[:max_tasks]

    @staticmethod
    def _extract_app(lowered: str) -> str:
        for trigger in _SYSTEM_TOOL_KEYWORDS["open_application"]:
            if trigger in lowered:
                after = lowered.split(trigger, 1)[1].strip(" .,-")
                return after.split()[0] if after else "calculator"
        return "calculator"

    @staticmethod
    def _extract_path(lowered: str) -> str | None:
        match = re.search(r"[\w\\/][\w\\\-\.\/ ]*\.\w{2,5}", lowered)
        return match.group(0).strip() if match else None

    @staticmethod
    def _extract_search(lowered: str) -> tuple[str, str | None]:
        pattern = "*.txt"
        directory: str | None = None
        dir_match = re.search(r"u\b\s+(?P<dir>[^\s]+\b)", lowered)
        if dir_match:
            directory = dir_match.group("dir")
        file_match = re.search(
            r"(?:fajl|fajlovi|fajlove|fajleve|file|files|datoteka|datoteke|datotei)"
            r"\s+(?P<pattern>\S+)",
            lowered,
        )
        # Only accept the match if the captured pattern looks like a file pattern
        # (contains a glob char or an extension), otherwise keep the default.
        if file_match:
            candidate = file_match.group("pattern")
            if "*" in candidate or "?" in candidate or "." in candidate:
                pattern = candidate
        return pattern, directory


class LLMPlanner(Planner):
    """LLM-based planner with automatic fallback to :class:`StubPlanner`."""

    def __init__(
        self,
        llm_engine: LLMEngine | None,
        tool_registry: ToolRegistry | None = None,
        max_tokens: int = 256,
        profile: dict | None = None,
        system_prompt: str = "",
        tool_whitelist: list[str] | None = None,
        memory_context: str = "",
        knowledge_context: str = "",
        generation_config: GenerationConfig | None = None,
        project_context: str = "",
    ) -> None:
        super().__init__(
            tool_registry=tool_registry, system_prompt=system_prompt,
            tool_whitelist=tool_whitelist, memory_context=memory_context,
            knowledge_context=knowledge_context, project_context=project_context,
            profile=profile,
        )
        self._engine = llm_engine
        self._fallback = StubPlanner(
            tool_registry=tool_registry, system_prompt=system_prompt,
            tool_whitelist=tool_whitelist, memory_context=memory_context,
            knowledge_context=knowledge_context, project_context=project_context,
            profile=profile,
        )
        self._max_tokens = max_tokens
        self._generation_config = generation_config

    def plan(self, goal: str, max_tasks: int = 8) -> list[Task]:
        if self._engine is None or not self._engine.is_ready:
            return self._fallback.plan(goal, max_tasks)
        try:
            prompt = self._build_prompt(goal, max_tasks)
            raw = "".join(self._engine.generate_stream(prompt, config=self._generation_config))
            parsed = self._parse_plan(raw)
            if parsed:
                return parsed[:max_tasks]
            logger.warning(
                "LLMPlanner.parse_plan returned None for goal '%s' "
                "(falling back to StubPlanner)", goal[:80],
            )
        except Exception as exc:  # noqa: BLE001 — parse failed, fall back to stub
            logger.warning(
                "LLMPlanner.plan failed for goal '%s' (%s: %s) — "
                "falling back to StubPlanner", goal[:80], type(exc).__name__, exc,
            )
        return self._fallback.plan(goal, max_tasks)

    def _build_prompt(self, goal: str, max_tasks: int) -> str:
        tool_names = self._available_tools()

        profile_context = ""
        profile = getattr(self, "_profile", None)

        if profile:
            identity = profile.get("identity", {})
            communication = profile.get("communication", {})
            personality = profile.get("personality", {})
            behavior = profile.get("behavior", {})
            boundaries = profile.get("boundaries", {})

            name = identity.get("name")
            description = identity.get("description")
            areas = personality.get("traits", [])
            humor = personality.get("humor")
            proactivity = personality.get("proactivity")
            tone = communication.get("tone")
            formality = communication.get("formality")
            response_style = communication.get("response_style")
            resp_approach = behavior.get("response_approach")
            uncertainty = behavior.get("uncertainty_handling")
            question_style = behavior.get("question_style")
            custom = boundaries.get("custom_instructions")

            profile_lines = []

            if name:
                profile_lines.append(f"Assistant identity: {name}.")
            if description:
                profile_lines.append(f"Assistant description: {description}.")
            profile_lines.append("Assistant knowledge areas: " + ", ".join(areas) + ".")
            if humor is not None:
                if humor < 0.5:
                    profile_lines.append("Assistant humor level: low.")
                elif humor > 0.7:
                    profile_lines.append("Assistant humor level: high.")
            if proactivity is not None:
                if proactivity < 0.5:
                    profile_lines.append("Assistant proactivity: reactive.")
                else:
                    profile_lines.append("Assistant proactivity: proactive.")
            if tone and tone != "neutral":
                profile_lines.append(f"Communication tone: {tone}.")
            if formality and formality != "neutral":
                profile_lines.append(f"Formality level: {formality}.")
            if response_style and response_style != "balanced":
                profile_lines.append(f"Response style: {response_style}.")
            if resp_approach:
                profile_lines.append(f"Response approach: {resp_approach}.")
            if uncertainty:
                profile_lines.append(f"Uncertainty handling: {uncertainty}.")
            if question_style:
                profile_lines.append(f"Question style: {question_style}.")
            if custom:
                profile_lines.append(f"Custom instructions: {custom}")

            if profile_lines:
                profile_context = (
                    "Assistant profile context:\n"
                    + "\n".join(profile_lines)
                    + "\n"
                )

        system_prompt_context = ""
        sp = getattr(self, "_system_prompt", None)
        if sp:
            system_prompt_context = f"Agent system prompt:\n{sp}\n"

        memory_context_str = ""
        mc = getattr(self, "_memory_context", None)
        if mc:
            memory_context_str = f"Agent memory context:\n{mc}\n"

        knowledge_context_str = ""
        kc = getattr(self, "_knowledge_context", None)
        if kc:
            knowledge_context_str = (
                "Agent knowledge context (may be incomplete — use search_knowledge "
                f"for specific queries):\n{kc}\n"
            )

        project_context_str = ""
        pc = getattr(self, "_project_context", None)
        if pc:
            project_context_str = f"Project context:\n{pc}\n"

        return (
            f"{system_prompt_context}{profile_context}{project_context_str}"
            f"{memory_context_str}{knowledge_context_str}"
            f"Razlozi sledeci cilj u maksimalno {max_tasks} koraka. "
            f"Za svaki korak izaberi alat iz: {tool_names}. "
            f"Odgovori iskljucivo JSON nizom objekata "
            f'{{"description": str, "tool_name": str|null, "params": dict}}.\n'
            f"Cilj: {goal}\nPlan:"
        )

    def _available_tools(self) -> list[str]:
        if self._tool_registry is None:
            return []
        # Use the unified schema exporter so Chat and Agent paths share
        # the same metadata/schema source (Phase 2A).
        from ai.engine.tool_calling import ToolSchemaExporter

        exporter = ToolSchemaExporter(registry=self._tool_registry)
        schemas = exporter.export_schemas_for_llm()
        all_tools = [s.get("function", {}).get("name", "") for s in schemas]
        # None or empty whitelist → all tools (backward compatible).
        if self._tool_whitelist:
            return [t for t in all_tools if t in self._tool_whitelist]
        return all_tools

    @staticmethod
    def _parse_plan(raw: str) -> list[Task] | None:
        import json

        try:
            data = json.loads(raw.strip())
        except Exception:  # noqa: BLE001 — parse failed, fall back to stub
            return None
        if not isinstance(data, list):
            return None
        tasks: list[Task] = []
        for item in data:
            if isinstance(item, dict):
                tasks.append(
                    Task(
                        description=item.get("description", ""),
                        tool_name=item.get("tool_name"),
                        params=item.get("params"),
                    )
                )
        return tasks or None
