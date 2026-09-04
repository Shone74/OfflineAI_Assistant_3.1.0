"""Project and Workspace managers for FAZA 13.4.

These managers provide CRUD operations for project and workspace entities,
with persistence through the existing database layer.

Profile Override Support:
    Each workspace and project can have an optional profile_override dict
    that modifies the assistant profile when that context is active.

Profile Override Format:
    {
        "identity": {"name": "Project-Specific Assistant"},
        "personality": {"humor": 0.8},
        ...
    }

    Stored as JSON in the database, loaded on workspace/project access.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus
from core.logger import get_logger
from project.models import Project, Workspace

if TYPE_CHECKING:
    from database.database_manager import DatabaseManager

logger = get_logger("project")


class WorkspaceManager:
    """Manages workspace entities with CRUD operations.

    Workpaces are collections of related projects. Each workspace can have
    its own profile override that applies to all projects within it.

    Profile Override Cascade:
        Global Profile → Workspace Override → Project Override

    When a workspace is set as active, its profile_override is applied on
    top of the global profile. Project overrides then apply on top of that.
    """

    def __init__(self, db: DatabaseManager | None = None, event_bus: EventBus | None = None) -> None:
        """Initialize workspace manager.

        Args:
            db: Optional database manager for persistence.
            event_bus: Optional event bus for publishing events.
        """
        self._db = db
        self._event_bus = event_bus
        self._cache: dict[str, Workspace] = {}

    def create_workspace(
        self, name: str, settings: dict | None = None, profile_override: dict | None = None
    ) -> Workspace:
        """Create a new workspace.

        Args:
            name: Workspace display name.
            settings: Optional workspace settings dict.
            profile_override: Optional profile override dict. Applied on top of
                global profile when this workspace becomes active.

        Returns:
            The created Workspace instance.
        """
        if self._db is None:
            ws = Workspace(name=name, settings=settings or {}, profile_override=profile_override)
            self._cache[ws.id] = ws
            logger.info("Workspace created (no DB): %s", ws.id)
            return ws

        self._db.execute(
            "INSERT INTO workspaces (id, name, settings, profile_override, created_at, updated_at) VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
            (ws_id := str(__import__("uuid").uuid4()), name, json.dumps(settings or {}), json.dumps(profile_override) if profile_override is not None else None),
        )
        ws = Workspace(
            id=ws_id,
            name=name,
            settings=settings or {},
            profile_override=profile_override,
        )
        self._cache[ws.id] = ws
        self._event_bus and self._event_bus.publish(
            "WORKSPACE_CREATED", data={"workspace_id": ws.id, "name": name}
        )
        logger.info("Workspace created: %s", ws.id)
        return ws

    def get_workspace(self, workspace_id: str) -> Workspace | None:
        """Get a workspace by ID.

        Args:
            workspace_id: The workspace UUID to look up.

        Returns:
            Workspace instance or None if not found.
        """
        if workspace_id in self._cache:
            return self._cache[workspace_id]
        if self._db is None:
            return None
        row = self._db.query_one("SELECT * FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            return None
        ws = Workspace.from_dict(dict(row))
        self._cache[ws.id] = ws
        return ws

    def list_workspaces(self) -> list[Workspace]:
        """List all workspaces in creation order (newest first).

        Returns:
            List of all workspace instances.
        """
        if self._db is None:
            return list(self._cache.values())
        rows = self._db.query("SELECT * FROM workspaces ORDER BY created_at DESC")
        workspaces = [Workspace.from_dict(dict(row)) for row in rows]
        for ws in workspaces:
            self._cache[ws.id] = ws
        return workspaces

    def update_workspace(self, workspace_id: str, **kwargs) -> Workspace | None:
        """Update a workspace with provided fields.

        Args:
            workspace_id: The workspace to update.
            **kwargs: Fields to update (name, settings, profile_override).

        Returns:
            Updated workspace or None if not found.
        """
        if self._db is None:
            ws = self._cache.get(workspace_id)
            if ws is None:
                return None
            for key, value in kwargs.items():
                if hasattr(ws, key):
                    setattr(ws, key, value)
            ws.updated_at = str(__import__("datetime", fromlist=["UTC"]).datetime.now(__import__("datetime", fromlist=["UTC"]).UTC).isoformat())
            self._event_bus and self._event_bus.publish(
                "WORKSPACE_UPDATED", data={"workspace_id": workspace_id}
            )
            return ws
        allowed = {"name", "settings", "profile_override"}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed}
        if not update_fields:
            return self.get_workspace(workspace_id)
        set_clause = ", ".join(f"{k} = ?" for k in update_fields)
        params = list(update_fields.values()) + [workspace_id]
        self._db.execute(f"UPDATE workspaces SET {set_clause}, updated_at = datetime('now') WHERE id = ?", params)
        ws = self.get_workspace(workspace_id)
        if ws:
            self._event_bus and self._event_bus.publish(
                "WORKSPACE_UPDATED", data={"workspace_id": workspace_id}
            )
        return ws

    def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace by ID.

        Args:
            workspace_id: The workspace to delete.

        Returns:
            True if deleted, False if not found.
        """
        if self._db is None:
            return self._cache.pop(workspace_id, None) is not None
        result = self._db.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
        deleted = result.rowcount > 0
        if deleted:
            self._cache.pop(workspace_id, None)
            self._event_bus and self._event_bus.publish(
                "WORKSPACE_DELETED", data={"workspace_id": workspace_id}
            )
        return deleted


class ProjectManager:
    """Manages project entities with CRUD operations.

    Projects are work contexts within a workspace. Each project can have
    its own profile override that applies on top of the workspace's profile.

    Profile Override Cascade:
        Global Profile → Workspace Override → Project Override

    Profile overrides are stored as JSON in the database and are loaded
    when the project is accessed.
    """

    def __init__(self, db: DatabaseManager | None = None, event_bus: EventBus | None = None) -> None:
        """Initialize project manager.

        Args:
            db: Optional database manager for persistence.
            event_bus: Optional event bus for publishing events.
        """
        self._db = db
        self._event_bus = event_bus
        self._cache: dict[str, Project] = {}

    def create_project(
        self,
        name: str,
        description: str = "",
        workspace_id: str | None = None,
        workspace_path: str | None = None,
        profile_override: dict | None = None,
        settings: dict | None = None,
    ) -> Project:
        """Create a new project.

        Args:
            name: Project display name (required, must be non-empty).
            description: Optional project description.
            workspace_id: Optional parent workspace ID.
            workspace_path: Optional filesystem path to the project workspace.
                When provided, the path is validated for existence and
                directory-ness.
            profile_override: Optional profile override dict.
            settings: Optional project-specific settings dict.

        Returns:
            The created Project instance.

        Raises:
            ValueError: If *name* is empty or *workspace_path* is invalid.
        """
        if not name or not name.strip():
            raise ValueError("Project name must not be empty")

        validated_path: str | None = None
        if workspace_path is not None:
            validated_path = self.validate_workspace_path(workspace_path)

        if self._db is None:
            proj = Project(
                name=name,
                description=description,
                workspace_id=workspace_id,
                workspace_path=validated_path,
                profile_override=profile_override,
                settings=settings or {},
            )
            self._cache[proj.id] = proj
            logger.info("Project created (no DB): %s", proj.id)
            return proj

        proj_id = str(__import__("uuid").uuid4())
        self._db.execute(
            "INSERT INTO projects (id, name, description, workspace_id, workspace_path, profile_override, settings, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
            (
                proj_id,
                name,
                description,
                workspace_id,
                validated_path,
                json.dumps(profile_override) if profile_override is not None else None,
                json.dumps(settings or {}),
            ),
        )
        proj = Project(
            id=proj_id,
            name=name,
            description=description,
            workspace_id=workspace_id,
            workspace_path=validated_path,
            profile_override=profile_override,
            settings=settings or {},
        )
        self._cache[proj.id] = proj
        self._event_bus and self._event_bus.publish(
            "PROJECT_CREATED", data={"project_id": proj.id, "name": name}
        )
        logger.info("Project created: %s", proj.id)
        return proj

    def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID.

        Args:
            project_id: The project UUID to look up.

        Returns:
            Project instance or None if not found.
        """
        if project_id in self._cache:
            return self._cache[project_id]
        if self._db is None:
            return None
        row = self._db.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None:
            return None
        proj = Project.from_dict(dict(row))
        self._cache[proj.id] = proj
        return proj

    def list_projects(self, workspace_id: str | None = None) -> list[Project]:
        """List all projects, optionally filtered by workspace.

        Args:
            workspace_id: Optional workspace ID to filter by.

        Returns:
            List of Project instances, newest first.
        """
        if self._db is None:
            return [p for p in self._cache.values() if workspace_id is None or p.workspace_id == workspace_id]
        if workspace_id:
            rows = self._db.query("SELECT * FROM projects WHERE workspace_id = ? ORDER BY created_at DESC", (workspace_id,))
        else:
            rows = self._db.query("SELECT * FROM projects ORDER BY created_at DESC")
        projects = [Project.from_dict(dict(row)) for row in rows]
        for proj in projects:
            self._cache[proj.id] = proj
        return projects

    def update_project(self, project_id: str, **kwargs) -> Project | None:
        """Update a project with provided fields.

        Args:
            project_id: The project to update.
            **kwargs: Fields to update (name, description, workspace_id, profile_override).

        Returns:
            Updated project or None if not found.
        """
        if self._db is None:
            proj = self._cache.get(project_id)
            if proj is None:
                return None
            for key, value in kwargs.items():
                if hasattr(proj, key):
                    setattr(proj, key, value)
            proj.updated_at = str(__import__("datetime", fromlist=["UTC"]).datetime.now(__import__("datetime", fromlist=["UTC"]).UTC).isoformat())
            self._event_bus and self._event_bus.publish(
                "PROJECT_UPDATED", data={"project_id": project_id}
            )
            return proj
        allowed_fields = {"name", "description", "workspace_id", "workspace_path", "profile_override", "settings"}

        if "workspace_path" in kwargs and kwargs["workspace_path"] is not None:
            kwargs["workspace_path"] = self.validate_workspace_path(kwargs["workspace_path"])

        if "profile_override" in kwargs and isinstance(kwargs["profile_override"], dict):
            kwargs["profile_override"] = json.dumps(kwargs["profile_override"])

        if "settings" in kwargs and isinstance(kwargs["settings"], dict):
            kwargs["settings"] = json.dumps(kwargs["settings"])

        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}
        if not update_fields:
            return self.get_project(project_id)
        set_clause = ", ".join(f"{k} = ?" for k in update_fields)
        params = list(update_fields.values()) + [project_id]
        self._db.execute(f"UPDATE projects SET {set_clause}, updated_at = datetime('now') WHERE id = ?", params)
        self._cache.pop(project_id, None)
        proj = self.get_project(project_id)
        if proj:
            self._event_bus and self._event_bus.publish(
                "PROJECT_UPDATED", data={"project_id": project_id}
            )
        return proj

    def delete_project(self, project_id: str) -> bool:
        """Delete a project by ID.

        Args:
            project_id: The project to delete.

        Returns:
            True if deleted, False if not found.
        """
        if self._db is None:
            return self._cache.pop(project_id, None) is not None
        result = self._db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        deleted = result.rowcount > 0
        if deleted:
            self._cache.pop(project_id, None)
            self._event_bus and self._event_bus.publish(
                "PROJECT_DELETED", data={"project_id": project_id}
            )
        return deleted

    def get_projects_for_workspace(self, workspace_id: str) -> list[Project]:
        """Get all projects belonging to a workspace.

        Args:
            workspace_id: The workspace to get projects for.

        Returns:
            List of Project instances.
        """
        return self.list_projects(workspace_id=workspace_id)

    def validate_workspace_path(self, path: str) -> str:
        """Validate that *path* is a usable workspace directory.

        The path must exist and be a directory. Symlinks are resolved.

        Args:
            path: Filesystem path to validate.

        Returns:
            Resolved absolute path string.

        Raises:
            ValueError: If the path does not exist or is not a directory.
        """
        if not path or not path.strip():
            raise ValueError("Workspace path must not be empty")
        resolved = Path(path).resolve()
        if not resolved.exists():
            raise ValueError(f"Workspace path does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"Workspace path is not a directory: {resolved}")
        return str(resolved)

    def get_project_settings(self, project_id: str) -> dict[str, Any]:
        """Return the settings dict for a project.

        Args:
            project_id: The project to read settings from.

        Returns:
            Settings dict (empty if no settings or project not found).
        """
        proj = self.get_project(project_id)
        if proj is None or not proj.settings:
            return {}
        return proj.settings

    def update_project_settings(self, project_id: str, settings: dict[str, Any]) -> Project | None:
        """Replace the entire settings dict for a project.

        Args:
            project_id: The project to update.
            settings: New settings dict.

        Returns:
            Updated project or None if not found.
        """
        return self.update_project(project_id, settings=settings)

    def list_project_files(self, project_id: str, include_hidden: bool = False) -> list[str]:
        """List actual files in the project's workspace directory.

        Args:
            project_id: The project whose files to list.
            include_hidden: Whether to include hidden files (starting with '.').

        Returns:
            List of relative file paths within the workspace.
        """
        proj = self.get_project(project_id)
        if proj is None or not proj.workspace_path:
            return []
        ws = Path(proj.workspace_path)
        if not ws.exists() or not ws.is_dir():
            return []
        files: list[str] = []
        for p in ws.rglob("*"):
            if p.is_file():
                rel = p.relative_to(ws).as_posix()
                if not include_hidden and any(part.startswith(".") for part in p.relative_to(ws).parts):
                    continue
                files.append(rel)
        return sorted(files)