"""Tool system package — register and execute AI action tools.

Public API:
    Tool, ToolResult, ToolRegistry, RiskLevel, ParameterSpec
    SystemMonitorTool, ApplicationLauncherTool, FileReaderTool, FileSearcherTool
    ProcessInfoTool, ListDirectoryTool, FileMetadataTool
    WriteFileTool, CreateDirectoryTool, CopyFileTool, MoveFileTool, DeleteFileTool
    CalculateTool, DateTimeTool, ClipboardReadTool, ClipboardWriteTool
    KnowledgeSearchTool
    create_registry — factory that registers all default tools
    ToolMetadata, ToolSource, ToolStatus, ToolTrust — arsenal models
    ToolCompatibilityEvaluator — model↔tool compatibility evaluation

Phase 2D additions:
    ToolManifest, validate_manifest, ManifestValidationError, ToolState
    ToolDiscoveryService — discovers & validates external tool manifests
    ToolInstaller, InstallResult — explicit installation lifecycle
    ToolCatalog — persistent catalog of discovered/installed/external tools
"""

from __future__ import annotations

from typing import Any

from tools.application_tools import ApplicationLauncherTool
from tools.base import (
    ParameterSpec,
    RiskLevel,
    Tool,
    ToolRegistry,
    ToolResult,
)
from tools.catalog import ToolCatalog
from tools.compatibility import ToolCompatibilityEvaluator
from tools.discovery import ToolDiscoveryService
from tools.file_tools import (
    CopyFileTool,
    CreateDirectoryTool,
    DeleteFileTool,
    FileMetadataTool,
    FileReaderTool,
    FileSearcherTool,
    ListDirectoryTool,
    MoveFileTool,
    WriteFileTool,
)
from tools.installer import InstallResult, ToolInstaller
from tools.knowledge_tools import KnowledgeSearchTool
from tools.manifest import (
    MANIFEST_FORMAT_VERSION,
    ManifestValidationError,
    ToolManifest,
    ToolState,
    validate_manifest,
)
from tools.models import ToolMetadata, ToolSource, ToolStatus, ToolTrust
from tools.system_tools import ProcessInfoTool, SystemMonitorTool
from tools.utility_tools import (
    CalculateTool,
    ClipboardReadTool,
    ClipboardWriteTool,
    DateTimeTool,
)


def create_registry(
    event_bus=None,
    knowledge_base: Any | None = None,
) -> ToolRegistry:
    """Create a ToolRegistry with all default tools registered.

    Parameters
    ----------
    event_bus
        Optional EventBus instance (falls back to singleton).
    knowledge_base
        Optional :class:`KnowledgeBase` / :class:`RAGPipeline` instance.
        When provided, ``KnowledgeSearchTool`` is registered so agents can
        search the RAG knowledge base.  When ``None`` (the default),
        ``search_knowledge`` is **not** registered — the tool has no
        dependency-free fallback and is simply absent from the registry.
        This preserves full backward compatibility for callers that do
        not supply a knowledge base.
    """
    from core.event_bus import EventBus

    bus = event_bus or EventBus.get_instance()
    registry = ToolRegistry(event_bus=bus)
    # System tools
    registry.register(SystemMonitorTool())
    registry.register(ProcessInfoTool())
    # Application tools
    registry.register(ApplicationLauncherTool())
    # File tools
    registry.register(FileReaderTool())
    registry.register(FileSearcherTool())
    registry.register(ListDirectoryTool())
    registry.register(FileMetadataTool())
    registry.register(WriteFileTool())
    registry.register(CreateDirectoryTool())
    registry.register(CopyFileTool())
    registry.register(MoveFileTool())
    registry.register(DeleteFileTool())
    # Utility tools
    registry.register(CalculateTool())
    registry.register(DateTimeTool())
    registry.register(ClipboardReadTool())
    registry.register(ClipboardWriteTool())
    # Knowledge search tool (only when a KB/RAG pipeline is available)
    if knowledge_base is not None:
        registry.register(KnowledgeSearchTool(rag_pipeline=knowledge_base))
    return registry


__all__ = [
    "MANIFEST_FORMAT_VERSION",
    "ApplicationLauncherTool",
    "CalculateTool",
    "ClipboardReadTool",
    "ClipboardWriteTool",
    "CopyFileTool",
    "CreateDirectoryTool",
    "DateTimeTool",
    "DeleteFileTool",
    "FileMetadataTool",
    "FileReaderTool",
    "FileSearcherTool",
    "InstallResult",
    "KnowledgeSearchTool",
    "ListDirectoryTool",
    "ManifestValidationError",
    "MoveFileTool",
    "ParameterSpec",
    "ProcessInfoTool",
    "RiskLevel",
    "SystemMonitorTool",
    "Tool",
    "ToolCatalog",
    "ToolCompatibilityEvaluator",
    "ToolDiscoveryService",
    "ToolInstaller",
    "ToolManifest",
    "ToolMetadata",
    "ToolRegistry",
    "ToolResult",
    "ToolSource",
    "ToolState",
    "ToolStatus",
    "ToolTrust",
    "WriteFileTool",
    "create_registry",
    "validate_manifest",
]