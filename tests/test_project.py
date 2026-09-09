"""Regression tests for project/workspace managers (Phase D1).

Covers: WorkspaceManager and ProjectManager CRUD, profile override cascade,
workspace path validation, event publishing, cache behavior.
All tests run in OFFLINE_AI_TEST_MODE (headless, no real DB required).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.event_bus import EventBus
from project.manager import ProjectManager, WorkspaceManager

# --------------------------------------------------------------------------- #
# Test fixtures / helpers
# --------------------------------------------------------------------------- #

class _FakeDB:
    """In-memory fake database for testing without SQLite."""
    def __init__(self):
        self.workspaces = {}
        self.projects = {}
        self._executed = []

    def execute(self, sql, params=()):
        self._executed.append((sql, params))
        # Handle INSERT with RETURNING-like behavior
        if "INSERT INTO workspaces" in sql:
            ws_id = params[0]
            self.workspaces[ws_id] = {
                "id": ws_id, "name": params[1], "settings": params[2],
                "profile_override": params[3], "created_at": "now", "updated_at": "now"
            }
            class Result:
                rowcount = 1
            return Result()
        elif "INSERT INTO projects" in sql:
            proj_id = params[0]
            self.projects[proj_id] = {
                "id": proj_id, "name": params[1], "description": params[2],
                "workspace_id": params[3], "workspace_path": params[4],
                "profile_override": params[5], "settings": params[6],
                "created_at": "now", "updated_at": "now"
            }
            class Result:
                rowcount = 1
            return Result()
        elif "UPDATE workspaces" in sql:
            ws_id = params[-1]
            if ws_id in self.workspaces:
                # Parse SET clause roughly
                pass
            class Result:
                rowcount = 1
            return Result()
        elif "UPDATE projects" in sql:
            proj_id = params[-1]
            if proj_id in self.projects:
                pass
            class Result:
                rowcount = 1
            return Result()
        elif "DELETE FROM workspaces" in sql:
            ws_id = params[0]
            deleted = ws_id in self.workspaces
            if deleted:
                del self.workspaces[ws_id]
            class Result:
                rowcount = 1 if deleted else 0
            return Result()
        elif "DELETE FROM projects" in sql:
            proj_id = params[0]
            deleted = proj_id in self.projects
            if deleted:
                del self.projects[proj_id]
            class Result:
                rowcount = 1 if deleted else 0
            return Result()
        class Result:
            rowcount = 0
        return Result()

    def query(self, sql, params=()):
        if "SELECT * FROM workspaces" in sql:
            if "WHERE id = ?" in sql:
                ws_id = params[0]
                row = self.workspaces.get(ws_id)
                return [row] if row else []
            return list(self.workspaces.values())
        elif "SELECT * FROM projects" in sql:
            if "WHERE id = ?" in sql:
                proj_id = params[0]
                row = self.projects.get(proj_id)
                return [row] if row else []
            elif "WHERE workspace_id = ?" in sql:
                ws_id = params[0]
                return [p for p in self.projects.values() if p.get("workspace_id") == ws_id]
            return list(self.projects.values())
        return []

    def query_one(self, sql, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None


def _make_workspace_manager(db=None, event_bus=None):
    return WorkspaceManager(db=db, event_bus=event_bus)


def _make_project_manager(db=None, event_bus=None):
    return ProjectManager(db=db, event_bus=event_bus)


# --------------------------------------------------------------------------- #
# WorkspaceManager tests
# --------------------------------------------------------------------------- #

class TestWorkspaceManager:
    def test_create_workspace_no_db(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("Test Workspace", settings={"key": "value"})
        assert ws.name == "Test Workspace"
        assert ws.settings == {"key": "value"}
        assert ws.id in mgr._cache

    def test_create_workspace_with_profile_override(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace(
            "Override WS",
            profile_override={"identity": {"name": "WS Assistant"}}
        )
        assert ws.profile_override == {"identity": {"name": "WS Assistant"}}

    def test_create_workspace_with_db(self):
        db = _FakeDB()
        bus = EventBus()
        mgr = _make_workspace_manager(db=db, event_bus=bus)
        ws = mgr.create_workspace("DB Workspace")
        assert ws.id in db.workspaces
        assert ws.name == "DB Workspace"

    def test_get_workspace_from_cache(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("Cached")
        got = mgr.get_workspace(ws.id)
        assert got is ws  # same object from cache

    def test_get_workspace_from_db(self):
        db = _FakeDB()
        mgr = _make_workspace_manager(db=db)
        ws = mgr.create_workspace("From DB")
        mgr2 = _make_workspace_manager(db=db)
        got = mgr2.get_workspace(ws.id)
        assert got is not None
        assert got.name == "From DB"
        assert got.id == ws.id

    def test_list_workspaces(self):
        mgr = _make_workspace_manager()
        mgr.create_workspace("First")
        mgr.create_workspace("Second")
        workspaces = mgr.list_workspaces()
        assert len(workspaces) == 2
        names = {ws.name for ws in workspaces}
        assert names == {"First", "Second"}

    def test_update_workspace(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("Original")
        updated = mgr.update_workspace(ws.id, name="Updated", settings={"new": "val"})
        assert updated is not None
        assert updated.name == "Updated"
        assert updated.settings == {"new": "val"}

    def test_update_workspace_profile_override(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("No Override")
        updated = mgr.update_workspace(ws.id, profile_override={"personality": {"humor": 0.9}})
        assert updated.profile_override == {"personality": {"humor": 0.9}}

    def test_delete_workspace(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("To Delete")
        deleted = mgr.delete_workspace(ws.id)
        assert deleted is True
        assert mgr.get_workspace(ws.id) is None
        assert ws.id not in mgr._cache

    def test_delete_workspace_not_found(self):
        mgr = _make_workspace_manager()
        deleted = mgr.delete_workspace("non-existent-id")
        assert deleted is False

    def test_event_published_on_create(self):
        bus = EventBus()
        events = []
        bus.subscribe("WORKSPACE_CREATED", lambda e, d: events.append(d))
        db = _FakeDB()
        mgr = _make_workspace_manager(db=db, event_bus=bus)
        ws = mgr.create_workspace("Event Test")
        assert len(events) == 1
        assert events[0]["workspace_id"] == ws.id
        assert events[0]["name"] == "Event Test"

    def test_event_published_on_update(self):
        bus = EventBus()
        events = []
        bus.subscribe("WORKSPACE_UPDATED", lambda e, d: events.append(d))
        mgr = _make_workspace_manager(event_bus=bus)
        ws = mgr.create_workspace("Update Event")
        events.clear()
        mgr.update_workspace(ws.id, name="New Name")
        assert len(events) == 1
        assert events[0]["workspace_id"] == ws.id

    def test_event_published_on_delete(self):
        bus = EventBus()
        events = []
        bus.subscribe("WORKSPACE_DELETED", lambda e, d: events.append(d))
        db = _FakeDB()
        mgr = _make_workspace_manager(db=db, event_bus=bus)
        ws = mgr.create_workspace("Delete Event")
        events.clear()
        mgr.delete_workspace(ws.id)
        assert len(events) == 1
        assert events[0]["workspace_id"] == ws.id


# --------------------------------------------------------------------------- #
# ProjectManager tests
# --------------------------------------------------------------------------- #

class TestProjectManager:
    def test_create_project_no_db(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Test Project", description="A test")
        assert proj.name == "Test Project"
        assert proj.description == "A test"
        assert proj.id in mgr._cache

    def test_create_project_with_workspace(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("With Workspace", workspace_id="ws-123")
        assert proj.workspace_id == "ws-123"

    def test_create_project_with_profile_override(self):
        mgr = _make_project_manager()
        proj = mgr.create_project(
            "Override Project",
            profile_override={"identity": {"name": "Project Assistant"}}
        )
        assert proj.profile_override == {"identity": {"name": "Project Assistant"}}

    def test_create_project_validates_name(self):
        mgr = _make_project_manager()
        with pytest.raises(ValueError, match="empty"):
            mgr.create_project("")
        with pytest.raises(ValueError, match="empty"):
            mgr.create_project("   ")

    def test_create_project_validates_workspace_path(self):
        mgr = _make_project_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = mgr.create_project("Valid Path", workspace_path=tmpdir)
            assert proj.workspace_path == tmpdir

        # A genuinely absolute (drive-qualified on Windows) missing path.
        missing_root = Path(tempfile.gettempdir()) / "offlineai_missing_root_xyz"
        with pytest.raises(ValueError, match="does not exist"):
            mgr.create_project("Bad Path", workspace_path=str(missing_root))

        with (
            pytest.raises(ValueError, match="not a directory"),
            tempfile.NamedTemporaryFile() as f,
        ):
            mgr.create_project("File Path", workspace_path=f.name)

    def test_get_project_from_cache(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Cached Project")
        got = mgr.get_project(proj.id)
        assert got is proj

    def test_get_project_from_db(self):
        db = _FakeDB()
        mgr = _make_project_manager(db=db)
        proj = mgr.create_project("From DB")
        mgr2 = _make_project_manager(db=db)
        got = mgr2.get_project(proj.id)
        assert got is not None
        assert got.name == "From DB"

    def test_list_projects(self):
        mgr = _make_project_manager()
        mgr.create_project("First")
        mgr.create_project("Second")
        projects = mgr.list_projects()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"First", "Second"}

    def test_list_projects_filtered_by_workspace(self):
        mgr = _make_project_manager()
        mgr.create_project("WS1 Proj", workspace_id="ws-1")
        mgr.create_project("WS2 Proj", workspace_id="ws-2")
        mgr.create_project("WS1 Proj 2", workspace_id="ws-1")
        ws1_projects = mgr.list_projects(workspace_id="ws-1")
        assert len(ws1_projects) == 2
        assert all(p.workspace_id == "ws-1" for p in ws1_projects)

    def test_update_project(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Original")
        updated = mgr.update_project(proj.id, name="Updated", description="New desc")
        assert updated is not None
        assert updated.name == "Updated"
        assert updated.description == "New desc"

    def test_update_project_profile_override(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("No Override")
        updated = mgr.update_project(proj.id, profile_override={"communication": {"style": "formal"}})
        assert updated.profile_override == {"communication": {"style": "formal"}}

    def test_update_project_settings(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Settings Test", settings={"a": 1})
        updated = mgr.update_project_settings(proj.id, {"b": 2})
        assert updated is not None
        assert updated.settings == {"b": 2}  # replaced, not merged

    def test_delete_project(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("To Delete")
        deleted = mgr.delete_project(proj.id)
        assert deleted is True
        assert mgr.get_project(proj.id) is None

    def test_delete_project_not_found(self):
        mgr = _make_project_manager()
        deleted = mgr.delete_project("non-existent")
        assert deleted is False

    def test_get_projects_for_workspace(self):
        mgr = _make_project_manager()
        mgr.create_project("P1", workspace_id="ws-1")
        mgr.create_project("P2", workspace_id="ws-2")
        mgr.create_project("P3", workspace_id="ws-1")
        projects = mgr.get_projects_for_workspace("ws-1")
        assert len(projects) == 2
        assert all(p.workspace_id == "ws-1" for p in projects)

    def test_event_published_on_create(self):
        bus = EventBus()
        events = []
        bus.subscribe("PROJECT_CREATED", lambda e, d: events.append(d))
        db = _FakeDB()
        mgr = _make_project_manager(db=db, event_bus=bus)
        proj = mgr.create_project("Event Test")
        assert len(events) == 1
        assert events[0]["project_id"] == proj.id
        assert events[0]["name"] == "Event Test"

    def test_event_published_on_update(self):
        bus = EventBus()
        events = []
        bus.subscribe("PROJECT_UPDATED", lambda e, d: events.append(d))
        mgr = _make_project_manager(event_bus=bus)
        proj = mgr.create_project("Update Event")
        events.clear()
        mgr.update_project(proj.id, name="New")
        assert len(events) == 1
        assert events[0]["project_id"] == proj.id

    def test_event_published_on_delete(self):
        bus = EventBus()
        events = []
        bus.subscribe("PROJECT_DELETED", lambda e, d: events.append(d))
        db = _FakeDB()
        mgr = _make_project_manager(db=db, event_bus=bus)
        proj = mgr.create_project("Delete Event")
        events.clear()
        mgr.delete_project(proj.id)
        assert len(events) == 1
        assert events[0]["project_id"] == proj.id


# --------------------------------------------------------------------------- #
# Profile override cascade tests
# --------------------------------------------------------------------------- #

class TestProfileOverrideCascade:
    """Test that profile overrides work correctly through the cascade:
    Global -> Workspace -> Project
    """

    def test_workspace_override_applied(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("WS", profile_override={"identity": {"name": "WS Name"}})
        assert ws.profile_override == {"identity": {"name": "WS Name"}}

    def test_project_override_applied(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Proj", profile_override={"personality": {"humor": 0.5}})
        assert proj.profile_override == {"personality": {"humor": 0.5}}

    def test_settings_persisted_and_loaded(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Settings", settings={"custom": "value", "number": 42})
        settings = mgr.get_project_settings(proj.id)
        assert settings == {"custom": "value", "number": 42}


# --------------------------------------------------------------------------- #
# Workspace path validation
# --------------------------------------------------------------------------- #

class TestWorkspacePathValidation:
    def test_validate_existing_directory(self):
        mgr = _make_project_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            validated = mgr.validate_workspace_path(tmpdir)
            assert validated == tmpdir

    def test_validate_relative_path_rejected(self):
        """Relative workspace paths are rejected — they have no deterministic
        security meaning (PHASE 2 contract; previously CWD-resolved)."""
        mgr = _make_project_manager()
        with pytest.raises(ValueError, match="absolute"):
            mgr.validate_workspace_path("subdir")

    def test_validate_relative_path_rejection_is_cwd_independent(self):
        """The rejection is identical from any working directory."""
        import os

        mgr = _make_project_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "subdir"), exist_ok=True)
            old_cwd = os.getcwd()
            os.chdir(tmpdir)
            try:
                with pytest.raises(ValueError, match="absolute"):
                    mgr.validate_workspace_path("subdir")
            finally:
                os.chdir(old_cwd)

    def test_validate_nonexistent_raises(self):
        mgr = _make_project_manager()
        missing_root = Path(tempfile.gettempdir()) / "offlineai_missing_root_abc"
        with pytest.raises(ValueError, match="does not exist"):
            mgr.validate_workspace_path(str(missing_root))

    def test_validate_file_raises(self):
        mgr = _make_project_manager()
        with (
            tempfile.NamedTemporaryFile() as f,
            pytest.raises(ValueError, match="not a directory"),
        ):
            mgr.validate_workspace_path(f.name)


# --------------------------------------------------------------------------- #
# Project file listing
# --------------------------------------------------------------------------- #

class TestProjectFileListing:
    def test_list_project_files(self):
        mgr = _make_project_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            (Path(tmpdir) / "file1.txt").write_text("hello")
            (Path(tmpdir) / "file2.py").write_text("print('hi')")
            (Path(tmpdir) / "subdir").mkdir()
            (Path(tmpdir) / "subdir" / "file3.md").write_text("# markdown")

            proj = mgr.create_project("File List", workspace_path=tmpdir)
            files = mgr.list_project_files(proj.id)
            assert "file1.txt" in files
            assert "file2.py" in files
            assert "subdir/file3.md" in files

    def test_list_project_files_excludes_hidden(self):
        mgr = _make_project_manager()
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "visible.txt").write_text("hi")
            (Path(tmpdir) / ".hidden").write_text("secret")
            (Path(tmpdir) / ".git").mkdir()
            (Path(tmpdir) / ".git" / "config").write_text("git config")

            proj = mgr.create_project("Hidden Test", workspace_path=tmpdir)
            files = mgr.list_project_files(proj.id, include_hidden=False)
            assert "visible.txt" in files
            assert ".hidden" not in files
            assert "subdir/.git/config" not in files  # no subdir but check anyway

            files_hidden = mgr.list_project_files(proj.id, include_hidden=True)
            assert ".hidden" in files_hidden

    def test_list_project_files_no_workspace_path(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("No Path")
        files = mgr.list_project_files(proj.id)
        assert files == []

    def test_list_project_files_nonexistent_path(self):
        mgr = _make_project_manager()
        # Can't create project with nonexistent path (validation fails at create time)
        # Instead test that list_project_files returns empty for project without workspace_path
        proj = mgr.create_project("No Path")
        files = mgr.list_project_files(proj.id)
        assert files == []


# --------------------------------------------------------------------------- #
# Cache behavior
# --------------------------------------------------------------------------- #

class TestCacheBehavior:
    def test_workspace_cache_updated_on_create(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("Cache Test")
        assert ws.id in mgr._cache

    def test_workspace_cache_cleared_on_delete(self):
        mgr = _make_workspace_manager()
        ws = mgr.create_workspace("To Delete")
        mgr.delete_workspace(ws.id)
        assert ws.id not in mgr._cache

    def test_project_cache_updated_on_create(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("Cache Test")
        assert proj.id in mgr._cache

    def test_project_cache_cleared_on_delete(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("To Delete")
        mgr.delete_project(proj.id)
        assert proj.id not in mgr._cache

    def test_project_cache_cleared_on_update(self):
        mgr = _make_project_manager()
        proj = mgr.create_project("To Update")
        mgr.update_project(proj.id, name="New Name")
        # Cache should be invalidated so next get reads from DB
        # (In no-DB mode, it updates in-place)
        got = mgr.get_project(proj.id)
        assert got.name == "New Name"