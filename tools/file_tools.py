"""File tools — read, write, search, list, copy, move, delete files."""

from __future__ import annotations

import shutil
from typing import Any, ClassVar

from core.logger import get_logger
from security.models import ToolCategory
from tools.base import ParameterSpec, RiskLevel, Tool, ToolResult
from tools.file_security import PathValidationError, validate_read_path, validate_write_path
from tools.models import ToolMetadata, ToolSource, ToolTrust

logger = get_logger("tools.file")
_DEFAULT_READ_LIMIT = 50_000
_DEFAULT_MAX_RESULTS = 50


def _build_file_reader_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="read_file",
        name="File Reader",
        description="Read the text content of a single file.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.READ_ONLY.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.read",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or relative path to the file",
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Maximum number of characters to read",
                },
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
                "size": {"type": "integer"},
            },
        },
        icon="read_file",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_file_searcher_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="search_files",
        name="File Searcher",
        description="Search a directory tree for files matching a glob pattern.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.READ_ONLY.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.read",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory to search in",
                },
                "pattern": {
                    "type": "string",
                    "description": "Glob pattern (e.g. *.py)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results",
                },
            },
            "required": ["directory", "pattern"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "pattern": {"type": "string"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "name": {"type": "string"},
                            "size": {"type": "integer"},
                        },
                    },
                },
            },
        },
        icon="search",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_list_directory_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="list_directory",
        name="List Directory",
        description="List files and directories in a specified directory.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.READ_ONLY.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.read",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list",
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Recurse into subdirectories",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of entries to return",
                },
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "directory": {"type": "string"},
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "path": {"type": "string"},
                            "type": {"type": "string"},
                            "size": {"type": "integer"},
                        },
                    },
                },
            },
        },
        icon="folder",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_file_metadata_tool_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="file_metadata",
        name="File Metadata",
        description="Return metadata for a file (size, timestamps, type).",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.READ_ONLY.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.read",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file or directory",
                },
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "filename": {"type": "string"},
                "extension": {"type": "string"},
                "size": {"type": "integer"},
                "created": {"type": "number"},
                "modified": {"type": "number"},
                "accessed": {"type": "number"},
                "is_file": {"type": "boolean"},
                "is_directory": {"type": "boolean"},
            },
        },
        icon="info",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_write_file_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="write_file",
        name="Write File",
        description="Create or overwrite a text file.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.write",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to write",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write",
                },
                "encoding": {
                    "type": "string",
                    "description": "Text encoding (default: utf-8)",
                },
            },
            "required": ["path", "content"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "bytes_written": {"type": "integer"},
            },
        },
        icon="write_file",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_create_directory_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="create_directory",
        name="Create Directory",
        description="Create a directory and any necessary parent directories.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.write",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to create",
                },
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
        },
        icon="folder_plus",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_copy_file_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="copy_file",
        name="Copy File",
        description="Copy a file from source to destination.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.write",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source file path"},
                "destination": {"type": "string", "description": "Destination path"},
            },
            "required": ["source", "destination"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
                "bytes_copied": {"type": "integer"},
            },
        },
        icon="copy",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_move_file_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="move_file",
        name="Move File",
        description="Move or rename a file.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.WRITE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.write",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string", "description": "Source file path"},
                "destination": {"type": "string", "description": "Destination path"},
            },
            "required": ["source", "destination"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "destination": {"type": "string"},
            },
        },
        icon="move",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


def _build_delete_file_metadata() -> ToolMetadata:
    return ToolMetadata(
        tool_id="delete_file",
        name="Delete File",
        description="Delete a file. This action is irreversible.",
        version="1.0.0",
        category=ToolCategory.FILE,
        source=ToolSource.BUILTIN,
        risk_level=RiskLevel.DESTRUCTIVE.name.lower(),
        installed=True,
        enabled=True,
        offline=True,
        requires_network=False,
        supported_platforms=("windows", "linux", "macos"),
        permissions=("filesystem.write",),
        model_requirements=(),
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to delete"},
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "deleted": {"type": "boolean"},
            },
        },
        icon="delete",
        author="Offline AI Assistant",
        trust_level=ToolTrust.TRUSTED,
        installation_source="builtin",
        supports_llm_schema=False,
    )


class FileReaderTool(Tool):
    """Reads the text content of a single file."""

    name = "read_file"
    description = "Read a file and return its contents"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Absolute or relative path"),
        ParameterSpec(name="max_chars", type="int", description="Maximum number of characters", required=False),
    ]
    risk_level = RiskLevel.READ_ONLY

    def get_metadata(self) -> ToolMetadata:
        return _build_file_reader_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", ""))
        if not path:
            return ToolResult(success=False, message="No path given", error="MissingPath")

        try:
            resolved = validate_read_path(path)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        file_path = resolved.resolved
        if not file_path.exists():
            return ToolResult(
                success=False, message=f"File does not exist: {path}", error="NotFound"
            )
        if not file_path.is_file():
            return ToolResult(
                success=False, message=f"Path is not a file: {path}", error="NotAFile"
            )

        max_chars = int(params.get("max_chars", _DEFAULT_READ_LIMIT) or _DEFAULT_READ_LIMIT)
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")

        if len(content) > max_chars:
            content = content[:max_chars] + "\n...[truncated]"

        logger.debug("Read file %s (%d chars)", file_path, len(content))
        return ToolResult(
            success=True, message=f"File read: {file_path.name}",
            data={"path": str(file_path), "content": content, "size": len(content)},
        )


class FileSearcherTool(Tool):
    """Searches a directory tree for files matching a glob pattern."""

    name = "search_files"
    description = "Search for files in a directory (e.g. *.py)"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="directory", description="Directory to search"),
        ParameterSpec(name="pattern", description="Glob pattern (e.g. *.py)"),
        ParameterSpec(name="max_results", type="int", description="Maximum number of results", required=False),
    ]
    risk_level = RiskLevel.READ_ONLY

    def get_metadata(self) -> ToolMetadata:
        return _build_file_searcher_metadata()

    def execute(self, **params: Any) -> ToolResult:
        directory = str(params.get("directory", "."))
        pattern = str(params.get("pattern", "*"))
        max_results = int(params.get("max_results", _DEFAULT_MAX_RESULTS) or _DEFAULT_MAX_RESULTS)

        try:
            resolved = validate_read_path(directory)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        dir_path = resolved.resolved
        if not dir_path.exists() or not dir_path.is_dir():
            return ToolResult(
                success=False, message=f"Directory does not exist: {directory}", error="NotFound"
            )

        try:
            matches = sorted(dir_path.rglob(pattern))[:max_results]
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")

        result_list = [
            {"path": str(m), "name": m.name, "size": m.stat().st_size if m.is_file() else 0}
            for m in matches
        ]
        logger.debug("Search %s '%s' → %d results", dir_path, pattern, len(result_list))
        return ToolResult(
            success=True, message=f"Found {len(result_list)} files",
            data={"directory": str(dir_path), "pattern": pattern, "results": result_list},
        )


class ListDirectoryTool(Tool):
    """Lists files and directories in a specified directory."""

    name = "list_directory"
    description = "List files and directories in a folder"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Directory to list"),
        ParameterSpec(name="recursive", type="boolean", description="Recursive", required=False),
        ParameterSpec(name="max_results", type="int", description="Maximum number of results", required=False),
    ]
    risk_level = RiskLevel.READ_ONLY

    def get_metadata(self) -> ToolMetadata:
        return _build_list_directory_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", "."))
        recursive = bool(params.get("recursive", False))
        max_results = int(params.get("max_results", _DEFAULT_MAX_RESULTS) or _DEFAULT_MAX_RESULTS)

        try:
            resolved = validate_read_path(path)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        dir_path = resolved.resolved
        if not dir_path.exists():
            return ToolResult(
                success=False, message=f"Directory does not exist: {path}", error="NotFound"
            )
        if not dir_path.is_dir():
            return ToolResult(
                success=False, message=f"Path is not a directory: {path}", error="NotADirectory"
            )

        try:
            if recursive:
                all_entries = sorted(dir_path.rglob("*"))
            else:
                all_entries = sorted(dir_path.iterdir())
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")

        entries: list[dict[str, Any]] = []
        for entry in all_entries[:max_results]:
            try:
                is_file = entry.is_file()
                entries.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "type": "file" if is_file else "directory",
                        "size": entry.stat().st_size if is_file else 0,
                    }
                )
            except OSError:
                entries.append(
                    {"name": entry.name, "path": str(entry), "type": "unknown", "size": 0}
                )

        logger.debug("Listed %s → %d entries", dir_path, len(entries))
        return ToolResult(
            success=True,
            message=f"Listed {len(entries)} entries" + (" (recursive)" if recursive else ""),
            data={"directory": str(dir_path), "entries": entries},
        )


class FileMetadataTool(Tool):
    """Returns metadata for a file or directory."""

    name = "file_metadata"
    description = "Metadata for a file (size, timestamps, type)"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Path to the file or directory"),
    ]
    risk_level = RiskLevel.READ_ONLY

    def get_metadata(self) -> ToolMetadata:
        return _build_file_metadata_tool_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", ""))
        if not path:
            return ToolResult(success=False, message="No path given", error="MissingPath")

        try:
            resolved = validate_read_path(path)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        file_path = resolved.resolved
        if not file_path.exists():
            return ToolResult(
                success=False, message=f"File does not exist: {path}", error="NotFound"
            )

        try:
            stat = file_path.stat()
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")

        data = {
            "path": str(file_path),
            "filename": file_path.name,
            "extension": file_path.suffix,
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "accessed": stat.st_atime,
            "is_file": file_path.is_file(),
            "is_directory": file_path.is_dir(),
        }
        logger.debug("File metadata: %s", path)
        return ToolResult(
            success=True, message=f"Metadata for: {file_path.name}",
            data=data,
        )


class WriteFileTool(Tool):
    """Creates or overwrites a text file."""

    name = "write_file"
    description = "Create or overwrite a text file"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Path to the file"),
        ParameterSpec(name="content", description="Content to write"),
        ParameterSpec(name="encoding", description="Encoding (default: utf-8)", required=False),
    ]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_write_file_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", ""))
        content = params.get("content", "")
        if not path:
            return ToolResult(success=False, message="No path given", error="MissingPath")
        if content is None:
            content = ""

        encoding = str(params.get("encoding") or "utf-8")

        try:
            resolved = validate_write_path(path, create_parent=True)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        file_path = resolved.resolved
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding=encoding)
            bytes_written = len(content.encode(encoding))
            logger.info("Wrote file %s (%d bytes)", file_path, bytes_written)
            return ToolResult(
                success=True,
                message=f"Written to file: {file_path.name}",
                data={"path": str(file_path), "bytes_written": bytes_written},
            )
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")
        except (LookupError, UnicodeEncodeError) as exc:
            return ToolResult(success=False, message=f"Encoding error: {exc}", error="EncodingError")


class CreateDirectoryTool(Tool):
    """Creates a directory and any necessary parent directories."""

    name = "create_directory"
    description = "Create a directory"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Path to the directory"),
    ]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_create_directory_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", ""))
        if not path:
            return ToolResult(success=False, message="No path given", error="MissingPath")

        try:
            resolved = validate_write_path(path, create_parent=True)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        dir_path = resolved.resolved
        try:
            dir_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created directory: %s", dir_path)
            return ToolResult(
                success=True,
                message=f"Created directory: {dir_path.name}",
                data={"path": str(dir_path)},
            )
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")


class CopyFileTool(Tool):
    """Copies a file from source to destination."""

    name = "copy_file"
    description = "Copy a file"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="source", description="Source path"),
        ParameterSpec(name="destination", description="Destination path"),
    ]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_copy_file_metadata()

    def execute(self, **params: Any) -> ToolResult:
        source = str(params.get("source", ""))
        destination = str(params.get("destination", ""))
        if not source:
            return ToolResult(success=False, message="No source path given", error="MissingSource")
        if not destination:
            return ToolResult(success=False, message="No destination path given", error="MissingDestination")

        try:
            src_resolved = validate_read_path(source)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")
        try:
            dst_resolved = validate_write_path(destination, create_parent=True)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        src_path = src_resolved.resolved
        dst_path = dst_resolved.resolved

        if not src_path.exists():
            return ToolResult(
                success=False, message=f"Source file does not exist: {source}", error="NotFound"
            )
        if src_path.is_dir():
            return ToolResult(
                success=False, message=f"Source is a directory, not a file: {source}", error="NotAFile"
            )

        try:
            bytes_copied = shutil.copyfile(src_path, dst_path)
            logger.info("Copied %s → %s", src_path, dst_path)
            return ToolResult(
                success=True,
                message=f"Copied to: {dst_path.name}",
                data={
                    "source": str(src_path),
                    "destination": str(dst_path),
                    "bytes_copied": bytes_copied,
                },
            )
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")


class MoveFileTool(Tool):
    """Moves or renames a file."""

    name = "move_file"
    description = "Move or rename a file"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="source", description="Source path"),
        ParameterSpec(name="destination", description="Destination path"),
    ]
    risk_level = RiskLevel.WRITE

    def get_metadata(self) -> ToolMetadata:
        return _build_move_file_metadata()

    def execute(self, **params: Any) -> ToolResult:
        source = str(params.get("source", ""))
        destination = str(params.get("destination", ""))
        if not source:
            return ToolResult(success=False, message="No source path given", error="MissingSource")
        if not destination:
            return ToolResult(success=False, message="No destination path given", error="MissingDestination")

        try:
            src_resolved = validate_read_path(source)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")
        try:
            dst_resolved = validate_write_path(destination, create_parent=True)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        src_path = src_resolved.resolved
        dst_path = dst_resolved.resolved

        if not src_path.exists():
            return ToolResult(
                success=False, message=f"Source file does not exist: {source}", error="NotFound"
            )

        try:
            shutil.move(str(src_path), str(dst_path))
            logger.info("Moved %s → %s", src_path, dst_path)
            return ToolResult(
                success=True,
                message=f"Moved to: {dst_path.name}",
                data={"source": str(src_path), "destination": str(dst_path)},
            )
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")


class DeleteFileTool(Tool):
    """Deletes a file. Irreversible action."""

    name = "delete_file"
    description = "Delete a file (irreversible)"
    category: ToolCategory = ToolCategory.FILE
    parameters: ClassVar[list[ParameterSpec]] = [
        ParameterSpec(name="path", description="Path to the file to delete"),
    ]
    risk_level = RiskLevel.DESTRUCTIVE

    def get_metadata(self) -> ToolMetadata:
        return _build_delete_file_metadata()

    def execute(self, **params: Any) -> ToolResult:
        path = str(params.get("path", ""))
        if not path:
            return ToolResult(success=False, message="No path given", error="MissingPath")

        try:
            resolved = validate_write_path(path)
        except PathValidationError as exc:
            return ToolResult(success=False, message=str(exc), error="PathValidation")

        file_path = resolved.resolved

        # Never allow deletion of directories through this tool
        if file_path.is_dir():
            return ToolResult(
                success=False,
                message=f"Path is a directory, not a file: {path}",
                error="IsADirectory",
            )

        if not file_path.exists():
            return ToolResult(
                success=False, message=f"File does not exist: {path}", error="NotFound"
            )

        try:
            file_path.unlink()
            logger.info("Deleted file: %s", file_path)
            return ToolResult(
                success=True,
                message=f"Deleted file: {file_path.name}",
                data={"path": str(file_path), "deleted": True},
            )
        except OSError as exc:
            return ToolResult(success=False, message=str(exc), error="OSError")
