"""Application launcher tool — opens programs via known aliases or paths."""

from __future__ import annotations

import os
import subprocess
from typing import Any, ClassVar

from core.logger import get_logger
from security.models import ToolCategory
from tools.base import ParameterSpec, RiskLevel, Tool, ToolResult
from tools.models import ToolMetadata, ToolSource, ToolTrust

logger = get_logger("tools.application")


def _build_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="open_application",
        name="Open Application",
        description="Launch a desktop application by name or path.",
        version="1.0.0",
        category=ToolCategory.APPLICATION,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("system.execute",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "program": {
                    "type": "string",
                    "description": "Name of the program or path to launch",
                },
            },
            "required": ["program"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "program": {"type": "string"},
            },
        },
        icon="🚀",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )

_KNOWN_APPS: dict[str, str] = {
    "computer": "explorer",
    "explorer": "explorer",
    "calculator": "calc",
    "notepad": "notepad",
    "browser": "msedge",
    "cmd": "cmd",
    "powershell": "powershell",
}


class ApplicationLauncherTool(Tool):
    """Launches a desktop application by name or path."""

    name = "open_application"
    description = "Launch a program (e.g. calculator, browser)"
    category: ToolCategory = ToolCategory.APPLICATION
    parameters: ClassVar[list[ParameterSpec]] = [ParameterSpec(name="program", description="Program name or path")]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_metadata()

    def execute(self, **params: Any) -> ToolResult:
        program = str(params.get("program", "")).strip()
        if not program:
            return ToolResult(
                success=False, message="No program specified", error="MissingProgram"
            )

        target = _KNOWN_APPS.get(program.lower(), program)

        try:
            if target.endswith(".exe") or "\\" in target or "/" in target:
                os.startfile(target)
            else:
                subprocess.Popen(target, shell=False)
            logger.info("Launched application: %s", target)
            return ToolResult(
                success=True,
                message=f"Launched program: {target}",
                data={"program": target},
            )
        except FileNotFoundError:
            return ToolResult(
                success=False, message=f"Program not found: {target}",
                error="FileNotFoundError",
            )
        except OSError as exc:
            return ToolResult(
                success=False, message=str(exc), error="OSError"
            )


def resolve_program(alias: str) -> str | None:
    """Return the executable for *alias*, or ``None`` if unknown."""
    return _KNOWN_APPS.get(alias.lower())
