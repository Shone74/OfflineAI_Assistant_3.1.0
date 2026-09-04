"""Database models — dataclass definitions mirroring the SQLite schema.

These are plain dataclasses used by the DatabaseManager and the various
memory backends.  They are intentionally ORM-free to avoid extra
dependencies (SQLAlchemy is not needed for a single-file SQLite database).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class MemoryType(str, Enum):
    USER_PREFERENCE = "user_preference"
    FACT = "fact"
    PROJECT_INFO = "project_info"
    INSTRUCTION = "instruction"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


@dataclass
class User:
    id: int | None = None
    username: str = "default"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_login: str | None = None


@dataclass
class Setting:
    key: str
    value: str
    category: str = "general"


@dataclass
class Conversation:
    id: int | None = None
    title: str = ""
    summary: str = ""
    workspace_id: str | None = None
    project_id: str | None = None
    profile_snapshot: dict[str, Any] | None = None
    pinned: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Message:
    id: int | None = None
    conversation_id: int = 0
    role: str = "user"
    content: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MemoryEntry:
    id: int | None = None
    type: str = MemoryType.FACT.value
    content: str = ""
    importance: float = 0.5
    agent_id: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    last_used: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Document:
    id: int | None = None
    filename: str = ""
    path: str = ""
    doc_type: str = "txt"
    size: int = 0
    hash: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class Embedding:
    id: int | None = None
    document_id: int = 0
    chunk_text: str = ""
    vector: list[float] = field(default_factory=list)


@dataclass
class Task:
    id: int | None = None
    name: str = ""
    description: str = ""
    schedule: str = ""
    status: str = "pending"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class PluginRecord:
    id: int | None = None
    name: str = ""
    version: str = ""
    path: str = ""
    enabled: bool = True


@dataclass
class PermissionRecord:
    id: int | None = None
    plugin_id: int = 0
    permission: str = ""
    allowed: bool = True


@dataclass
class ModelRecord:
    id: int | None = None
    name: str = ""
    model_type: str = "llm"
    path: str = ""
    size: int = 0
    active: bool = False


@dataclass
class Agent:
    id: int | None = None
    name: str = ""
    description: str = ""
    system_prompt: str = ""
    model_name: str = ""
    enabled: bool = True
    tool_whitelist: list[str] | None = None
    permission_profile: str = "default"
    profile_snapshot: dict[str, Any] | None = None
    status: str = "active"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class LogEntry:
    id: int | None = None
    level: str = "INFO"
    module: str = ""
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class MigrationInfo:
    version: int
    name: str
    applied_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def serialize(obj: Any) -> Any:
    """Convert an enum / datetime for SQLite storage."""
    if isinstance(obj, Enum):
        return obj.value
    return obj
