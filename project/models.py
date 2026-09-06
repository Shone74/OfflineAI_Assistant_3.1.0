"""Project and Workspace models for Phase 13.4."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class Workspace:
    """A workspace represents a collection of related projects.

    Each workspace can have its own profile override that applies
    to all projects within it.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    profile_override: dict[str, Any] | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "settings": self.settings,
            "profile_override": self.profile_override,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Workspace:
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            settings=data.get("settings", {}),
            profile_override=data.get("profile_override"),
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
        )


@dataclass
class Project:
    """A project represents a specific work context within a workspace.

    Projects can have profile overrides that apply on top of the workspace
    profile, allowing for fine-grained persona control per project.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    workspace_id: str | None = None
    workspace_path: str | None = None
    profile_override: dict[str, Any] | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    def to_dict(self) -> dict[str, Any]:
        result = {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "workspace_id": self.workspace_id,
            "workspace_path": self.workspace_path,
            "profile_override": self.profile_override,
            "settings": self.settings,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Project:
        profile_override = data.get("profile_override")
        if isinstance(profile_override, str):
            profile_override = json.loads(profile_override) if profile_override else None

        settings = data.get("settings", {})
        if isinstance(settings, str):
            settings = json.loads(settings) if settings else {}

        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            workspace_id=data.get("workspace_id"),
            workspace_path=data.get("workspace_path"),
            profile_override=profile_override,
            settings=settings or {},
            created_at=data.get("created_at", datetime.now(UTC).isoformat()),
            updated_at=data.get("updated_at", datetime.now(UTC).isoformat()),
        )