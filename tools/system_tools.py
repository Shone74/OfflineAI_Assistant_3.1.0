"""System monitoring tools — CPU, RAM, disk, and GPU info.

Read-only information (risk level = INFO), so no confirmation is needed.
"""

from __future__ import annotations

from typing import Any, ClassVar

import psutil

from core.logger import get_logger
from security.models import ToolCategory
from tools.base import ParameterSpec, RiskLevel, Tool, ToolResult
from tools.models import (
    ToolMetadata,
    ToolSource,
    ToolTrust,
)

logger = get_logger("tools.system")

_GPU_QUERY_ATTEMPTED = False


def _build_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="system_info",
        name="System Information",
        description="Display CPU, RAM, disk, and GPU utilisation of the system.",
        version="1.0.0",
        category=ToolCategory.SYSTEM,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.INFO.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("system.read",),
        model_requirements=(),
        input_schema={"type": "object", "properties": {}, "required": []},
        output_schema={
            "type": "object",
            "properties": {
                "cpu_percent": {"type": "number"},
                "ram_total_gb": {"type": "number"},
                "ram_used_percent": {"type": "number"},
                "disk_total_gb": {"type": "number"},
                "disk_used_percent": {"type": "number"},
                "gpu": {"type": "string"},
            },
        },
        icon="💻",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _query_gpu() -> str:
    """Best-effort GPU label through the PHASE 7 hardware abstraction.

    Consumes :class:`ai.hardware.HardwareSnapshot` (which sources VRAM
    from the Phase 4 NVML probe — WMI ``AdapterRAM`` is never trusted
    for sizing).  Returns a short label or 'N/A'; never raises and
    never blocks on optional dependencies.
    """
    global _GPU_QUERY_ATTEMPTED
    if _GPU_QUERY_ATTEMPTED:
        return "N/A"
    try:
        from ai.hardware import detect_hardware_snapshot

        snapshot = detect_hardware_snapshot()
        if snapshot.gpu_name:
            if snapshot.vram_known:
                return f"{snapshot.gpu_name} ({snapshot.vram_bytes / (1024**2):.0f} MB)"
            return snapshot.gpu_name
        return "N/A"
    except Exception:
        return "N/A"
    finally:
        _GPU_QUERY_ATTEMPTED = True


class SystemMonitorTool(Tool):
    """Provides CPU, memory, disk, and GPU utilisation."""

    name = "system_info"
    description = "Show computer information (CPU, RAM, disk, GPU)"
    category: ToolCategory = ToolCategory.SYSTEM
    parameters: ClassVar[list[ParameterSpec]] = []
    risk_level = RiskLevel.INFO

    def get_metadata(self) -> ToolMetadata:
        return _build_metadata()

    def execute(self, **_params: Any) -> ToolResult:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        gpu = _query_gpu()

        data = {
            "cpu_percent": round(cpu, 1),
            "ram_total_gb": round(ram.total / (1024**3), 2),
            "ram_used_percent": round(ram.percent, 1),
            "disk_total_gb": round(disk.total / (1024**3), 1),
            "disk_used_percent": round(disk.percent, 1),
            "gpu": gpu,
        }
        logger.debug("System metrics: %s", data)
        return ToolResult(success=True, message="System information", data=data)


def _build_process_info_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="process_info",
        name="Process Information",
        description="Return information about running processes (PID, name, CPU, memory).",
        version="1.0.0",
        category=ToolCategory.SYSTEM,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.INFO.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("system.read",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of processes to return (default 20)",
                },
            },
            "required": [],
        },
        output_schema={
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pid": {"type": "integer"},
                    "name": {"type": "string"},
                    "cpu_percent": {"type": "number"},
                    "memory_percent": {"type": "number"},
                    "memory_mb": {"type": "number"},
                    "exe": {"type": "string"},
                    "status": {"type": "string"},
                },
            },
        },
        icon="📊",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


class ProcessInfoTool(Tool):
    """Provides information about running processes."""

    name = "process_info"
    description = "Show information about running processes"
    category: ToolCategory = ToolCategory.SYSTEM
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(
            name="limit", type="int", description="Maximum processes (default 20)",
            required=False,
        ),
    ]
    risk_level = RiskLevel.INFO

    def get_metadata(self) -> ToolMetadata:
        return _build_process_info_metadata()

    def execute(self, **params: Any) -> ToolResult:
        limit = int(params.get("limit", 20) or 20)
        try:
            procs = []
            for proc in psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_percent", "memory_info", "exe", "status"]
            ):
                try:
                    info = proc.info
                    mem_info = info.get("memory_info")
                    mem_mb = (
                        round(getattr(mem_info, "rss", 0) / (1024 * 1024), 2)
                        if mem_info else 0.0
                    )
                    procs.append(
                        {
                            "pid": info.get("pid", 0),
                            "name": info.get("name", "unknown"),
                            "cpu_percent": round(info.get("cpu_percent", 0.0) or 0.0, 1),
                            "memory_percent": round(info.get("memory_percent", 0.0) or 0.0, 1),
                            "memory_mb": mem_mb,
                            "exe": info.get("exe") or "N/A",
                            "status": info.get("status", "unknown"),
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                if len(procs) >= limit:
                    break
            procs.sort(key=lambda p: p.get("cpu_percent", 0), reverse=True)
            logger.debug("Process info: %d processes", len(procs))
            return ToolResult(
                success=True,
                message=f"Information about {len(procs)} processes",
                data={"processes": procs},
            )
        except psutil.AccessDenied as exc:
            return ToolResult(
                success=False, message=str(exc), error="AccessDenied"
            )
        except Exception as exc:
            return ToolResult(
                success=False, message=str(exc), error="ProcessError"
            )
