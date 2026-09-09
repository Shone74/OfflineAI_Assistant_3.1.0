"""Project and Workspace managers for Phase 13.4.

These managers provide CRUD operations for project and workspace entities,
with persistence through the existing database layer.

Filesystem Security (Phase 2):
    Every operation that touches user/project files goes through the shared
    :class:`tools.file_security.PathValidator` (the same security boundary
    used by the file tools and configured from ``filesystem.*`` settings):

    * ``create_project`` — workspace path must pass WRITE authorization
      before anything is persisted or created on disk.
    * ``validate_workspace_path`` — enforces the security boundary in
      addition to basic existence checks, distinguishing an unauthorized
      path (:class:`PathValidationError`) from an invalid/nonexistent one
      (:class:`ValueError`).
    * ``list_project_files`` — recursive enumeration enforces READ
      authorization on the workspace root AND on every enumerated entry,
      never descending into symlink/reparse-point directories, so a
      symlinked escape cannot leak paths outside the allowed read roots.
    * ``delete_workspace_files`` — the ONLY sanctioned workspace deletion
      path; requires WRITE authorization before the destructive
      ``shutil.rmtree`` runs (note: rmtree does not follow junction
      targets, but the authorization decision is still enforced first).

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
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus
from core.logger import get_logger
from project.models import Project, Workspace
from tools.file_security import (
    PathValidationError,
    PathValidator,
    get_default_validator,
)

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

    def __init__(self, db: DatabaseManager | None = None, event_bus: EventBus | None = None, validator: PathValidator | None = None) -> None:
        """Initialize project manager.

        Args:
            db: Optional database manager for persistence.
            event_bus: Optional event bus for publishing events.
            validator: Optional filesystem security validator.  Defaults to
                the shared module-level validator (``get_default_validator``)
                resolved lazily on each use, so configuration changes made
                after manager construction are always honoured.  The manager
                must never implement its own filesystem policy.
        """
        self._db = db
        self._event_bus = event_bus
        self._validator_override = validator
        self._cache: dict[str, Project] = {}

    @property
    def _security(self) -> PathValidator:
        """The filesystem security boundary (shared validator by default)."""
        return self._validator_override or get_default_validator()

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
        """Validate that *path* is a usable, authorized workspace directory.

        Enforces the shared filesystem security boundary in addition to
        basic filesystem checks.  Relative paths are rejected: they have no
        deterministic security meaning (resolving them against the process
        CWD would make authorization CWD-dependent).

        Args:
            path: Filesystem path to validate.

        Returns:
            Resolved absolute path string.

        Raises:
            PathValidationError: If the path fails filesystem-security
                authorization (outside allowed write roots, policy
                fail-closed, traversal, symlink escape, ...).  This is
                raised BEFORE any existence check so an unauthorized path
                is never accepted even if it happens to exist.
            ValueError: If the path is empty, relative, does not exist,
                or is not a directory (invalid input, not a security
                decision).
        """
        if not path or not path.strip():
            raise ValueError("Workspace path must not be empty")
        raw = Path(path)
        if not raw.is_absolute():
            raise ValueError(
                f"Workspace path must be absolute; relative paths are not "
                f"deterministic and are rejected: {path}"
            )
        # Security boundary first — an unauthorized path must be reported
        # as an authorization failure even when the target exists.
        self._security.validate_write(path)
        resolved = raw.resolve()
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

        Security (Phase 2): the workspace root must pass READ authorization
        and every enumerated entry is containment-checked against the same
        boundary.  The walk is manual (not ``rglob``) and NEVER descends
        into symlink/reparse-point directories — a link inside the tree
        cannot leak paths outside the allowed read roots.  Broken symlinks
        and permission errors are skipped safely; a failing entry never
        crashes the whole listing nor silently broadens access.

        Args:
            project_id: The project whose files to list.
            include_hidden: Whether to include hidden files (starting with '.').

        Returns:
            List of relative file paths within the workspace.  Empty when the
            project has no workspace, the workspace is unauthorized, or the
            root is missing.
        """
        proj = self.get_project(project_id)
        if proj is None or not proj.workspace_path:
            return []
        ws = Path(proj.workspace_path)
        if not ws.exists() or not ws.is_dir():
            return []

        # Read authorization on the workspace root itself.  A failure here
        # means the workspace location is outside the allowed read boundary
        # (or the policy is fail-closed): return nothing rather than leak.
        try:
            self._security.validate_read(str(ws))
        except PathValidationError as exc:
            logger.warning(
                "Refused to enumerate workspace of project %s — read "
                "authorization failed for %s: %s", project_id, ws, exc,
            )
            return []

        files: list[str] = []
        # Explicit stack-based walk.  os.scandir-based iteration keeps
        # is_symlink() decisions cheap; directory symlinks are recorded but
        # never entered.
        stack: list[Path] = [ws]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError as exc:
                logger.debug("Cannot list %s: %s", current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        # Never descend into a symlinked directory and never
                        # report files reached through it.  If the target is
                        # an authorized location the user can add it as its
                        # own root; links must not broaden access.
                        continue
                    if entry.is_dir():
                        stack.append(entry)
                        continue
                    if not entry.is_file():
                        continue
                    resolved = entry.resolve(strict=False)
                    if not self._security.is_path_authorized(str(resolved), action="read"):
                        logger.debug(
                            "Skipping unauthorized file during enumeration: %s", resolved
                        )
                        continue
                    rel = entry.relative_to(ws).as_posix()
                    if not include_hidden and any(
                        part.startswith(".") for part in entry.relative_to(ws).parts
                    ):
                        continue
                    files.append(rel)
                except OSError as exc:
                    logger.debug("Skipping %s during enumeration: %s", entry, exc)
                    continue
        return sorted(files)

    def delete_workspace_files(self, project_id: str) -> bool:
        """Recursively delete the project's workspace directory contents.

        The ONLY sanctioned workspace deletion path (the UI must route
        "also delete files" here instead of calling ``shutil.rmtree``
        itself).  The workspace root must pass WRITE authorization before
        any destructive operation runs.  ``shutil.rmtree`` itself does not
        follow junction/symlink targets, so the authorized tree cannot
        delete content through a link into another location — but the
        authorization decision is still enforced first.

        Args:
            project_id: The project whose workspace files to delete.

        Returns:
            True if the workspace directory was removed, False when there
            is nothing to remove.  Raises :class:`PathValidationError` when
            the workspace location is not write-authorized — BEFORE any
            deletion is attempted.
        """
        proj = self.get_project(project_id)
        if proj is None or not proj.workspace_path:
            return False
        ws = Path(proj.workspace_path)
        if not ws.exists():
            return False
        if not ws.is_dir():
            raise ValueError(f"Workspace path is not a directory: {ws}")

        # WRITE authorization before any destructive operation.
        self._security.validate_write(str(ws))

        # Defense in depth: the resolved workspace must still be inside an
        # authorized write root even if it was reached via a symlink.
        if not self._security.is_path_authorized(str(ws.resolve(strict=False)), action="write"):
            raise PathValidationError(
                f"Workspace path resolves outside allowed write roots: {ws}"
            )

        try:
            shutil.rmtree(ws)
        except OSError as exc:
            logger.error("Failed to delete workspace %s: %s", ws, exc)
            raise
        logger.info("Deleted project workspace files: %s", ws)
        return True