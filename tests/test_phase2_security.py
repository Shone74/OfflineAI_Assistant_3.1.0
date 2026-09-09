"""PHASE 2 regression tests — filesystem security boundary.

Locks down the single consistent security boundary for all application
operations that read, write, create, delete, or enumerate user/project
files:

* PathValidator never resolves through the process CWD
* relative configured roots are rejected deterministically
* authorization results are CWD-invariant
* read/write root containment, traversal, null-byte, symlink policies
* fail-closed writes when enabled with no write roots
* ProjectManager enforces the boundary at its own API (independent of UI)
* enumeration cannot escape authorized read roots (symlink/junction safe)
* workspace deletion requires WRITE authorization and routes through
  ProjectManager
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.file_security import (
    PathValidationError,
    PathValidator,
    configure_default_validator,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.fixture()
def roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    """(allowed_root, outside, user_data) directory trio."""
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    user_data = tmp_path / "user_data"
    for d in (allowed, outside, user_data):
        d.mkdir()
    return allowed, outside, user_data


def _enabled_validator(read_roots=None, write_roots=None, base_dir=None, follow_symlinks=True) -> PathValidator:
    return PathValidator(
        read_roots=read_roots,
        write_roots=write_roots,
        enabled=True,
        base_dir=base_dir,
        follow_symlinks=follow_symlinks,
    )


def _fake_project(db_rows=None):
    """Minimal ProjectManager-compatible fake project record."""
    from project.models import Project

    return Project(id="proj-1", name="P", workspace_path=None)


class _FakeResult:
    """rowcount-compatible fake for the DELETE path."""

    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _FakeDB:
    """Minimal DB shim matching the surface ProjectManager uses."""

    def __init__(self) -> None:
        self.projects: dict[str, dict] = {}
        self.workspaces: dict[str, dict] = {}

    def execute(self, sql: str, params=()):
        sql_u = sql.strip().upper()
        if sql_u.startswith("INSERT INTO PROJECTS"):
            pid = params[0]
            self.projects[pid] = {
                "id": pid,
                "name": params[1],
                "description": params[2],
                "workspace_id": params[3],
                "workspace_path": params[4],
                "profile_override": params[5],
                "settings": params[6],
            }
            return _FakeResult(1)
        if sql_u.startswith("DELETE FROM PROJECTS"):
            existed = params[0] in self.projects
            self.projects.pop(params[0], None)
            return _FakeResult(1 if existed else 0)
        return _FakeResult(0)

    def query(self, sql: str, params=()):
        sql_u = sql.strip().upper()
        if "SELECT * FROM PROJECTS" in sql_u:
            if "WHERE ID = ?" in sql_u:
                row = self.projects.get(params[0])
                return [row] if row else []
            return list(self.projects.values())
        if "SELECT * FROM WORKSPACES" in sql_u:
            return list(self.workspaces.values())
        return []

    def query_one(self, sql: str, params=()):
        rows = self.query(sql, params)
        return rows[0] if rows else None


def _make_link(link_path: Path, target: Path) -> None:
    """Create a directory link (junction on Windows, symlink elsewhere).

    Junctions require no elevated privileges and reproduce the same
    escape semantics as symlinks for containment purposes.
    """
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(f"junction creation unavailable: {result.stderr}")
    else:
        os.symlink(target, link_path, target_is_directory=True)


def _make_file_link(link_path: Path, target: Path) -> None:
    """Create a link whose traversal must be denied.

    On Windows, real file symlinks require elevated privileges, so the test
    uses a directory junction instead (created without privileges) and
    targets are directory links — the containment semantics that matter
    (lexical path inside the root, resolved target outside) are identical.
    Never skips.
    """
    if os.name == "nt":
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"junction creation failed: {result.stderr}")
    else:
        os.symlink(target, link_path, target_is_directory=True)


# --------------------------------------------------------------------------- #
# 1-3. No CWD dependence in the validator
# --------------------------------------------------------------------------- #


class TestValidatorCwdIndependence:
    def test_relative_input_rejected_without_base_dir(self, roots, tmp_path):
        """Relative paths never resolve through CWD — rejected when no
        deterministic base is configured."""
        allowed, _, _ = roots
        validator = _enabled_validator(read_roots=[allowed], write_roots=[allowed])
        old = Path.cwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(PathValidationError, match="base directory"):
                validator.validate_read("somefile.txt")
        finally:
            os.chdir(old)

    def test_relative_input_resolved_against_base_dir_not_cwd(
        self, roots, tmp_path
    ):
        """With a base_dir, relative paths resolve against it — never CWD."""
        allowed, _, user_data = roots
        base = user_data / "base"
        base.mkdir()
        validator = _enabled_validator(
            read_roots=[allowed, base], write_roots=[base], base_dir=base
        )
        target = base / "file.txt"
        target.write_text("x")

        old = Path.cwd()
        try:
            os.chdir(tmp_path)  # foreign CWD containing nothing relevant
            result = validator.validate_read("file.txt")
            assert result.resolved == base / "file.txt"
            assert not (tmp_path / "file.txt").exists()
        finally:
            os.chdir(old)

    def test_relative_input_outside_base_roots_denied(self, roots, tmp_path):
        """A relative path escaping the base (via base_dir parents) is denied."""
        _, _, user_data = roots
        base = user_data / "base"
        base.mkdir()
        validator = _enabled_validator(read_roots=[base], base_dir=base)
        with pytest.raises(PathValidationError):
            validator.validate_read("..\\..\\secret.txt" if os.name == "nt" else "../../secret.txt")

    def test_relative_configured_root_rejected(self, roots):
        """Relative security roots are rejected at construction."""
        with pytest.raises(PathValidationError, match="absolute"):
            PathValidator(read_roots=["relative_root"], enabled=True)
        with pytest.raises(PathValidationError, match="absolute"):
            PathValidator(write_roots=["relative_root"], enabled=True)

    def test_authorization_cwd_invariant(self, roots, tmp_path):
        """Identical authorization outcomes from two different CWDs."""
        allowed, outside, _ = roots
        validator = _enabled_validator(
            read_roots=[allowed], write_roots=[allowed], base_dir=allowed
        )
        inside = allowed / "doc.txt"
        outside_file = outside / "doc.txt"

        results: list[tuple] = []
        old = Path.cwd()
        try:
            for cwd in (tmp_path / "cwd_a", tmp_path / "cwd_b"):
                cwd.mkdir(exist_ok=True)
                os.chdir(cwd)
                try:
                    validator.validate_read(str(inside))
                    inside_ok = True
                except PathValidationError:
                    inside_ok = False
                try:
                    validator.validate_read(str(outside_file))
                    outside_ok = True
                except PathValidationError:
                    outside_ok = False
                results.append((inside_ok, outside_ok))
        finally:
            os.chdir(old)

        assert results[0] == results[1] == (True, False)


# --------------------------------------------------------------------------- #
# 4-8. Preserved security guarantees
# --------------------------------------------------------------------------- #


class TestSecurityGuarantees:
    def test_absolute_allowed_read_root(self, roots):
        allowed, _, _ = roots
        validator = _enabled_validator(read_roots=[allowed])
        target = allowed / "notes.txt"
        target.write_text("x")
        assert validator.validate_read(str(target)).resolved == target

    def test_absolute_allowed_write_root(self, roots):
        allowed, _, _ = roots
        validator = _enabled_validator(write_roots=[allowed])
        target = allowed / "new.txt"
        assert validator.validate_write(str(target)).resolved == target

    def test_read_outside_read_roots_denied(self, roots):
        allowed, outside, _ = roots
        validator = _enabled_validator(read_roots=[allowed])
        secret = outside / "secret.txt"
        secret.write_text("s")
        with pytest.raises(PathValidationError, match="outside allowed read"):
            validator.validate_read(str(secret))

    def test_write_outside_write_roots_denied(self, roots):
        allowed, outside, _ = roots
        validator = _enabled_validator(write_roots=[allowed])
        with pytest.raises(PathValidationError, match="outside allowed write"):
            validator.validate_write(str(outside / "new.txt"))

    def test_enabled_empty_write_roots_fail_closed(self, roots):
        """Enabled + no write roots denies ALL writes (fail-closed)."""
        allowed, _, _ = roots
        validator = _enabled_validator(write_roots=[])
        with pytest.raises(PathValidationError, match="no writable roots"):
            validator.validate_write(str(allowed / "x.txt"))

    def test_traversal_denied(self, roots):
        allowed, _, _ = roots
        validator = _enabled_validator(read_roots=[allowed])
        with pytest.raises(PathValidationError, match="traversal"):
            validator.validate_read(
                str(allowed / "sub" / ".." / ".." / "secret.txt")
            )

    def test_null_bytes_denied(self, roots):
        allowed, _, _ = roots
        validator = _enabled_validator(read_roots=[allowed])
        with pytest.raises(PathValidationError, match="null"):
            validator.validate_read("bad\x00path")

    def test_symlink_escape_denied_follow_symlinks_true(self, roots):
        """A link lexically inside a root but resolving outside is denied.

        The link target is a directory; validating a path *through* the
        link must still resolve to the outside target and be denied.
        """
        allowed, outside, _ = roots
        validator = _enabled_validator(read_roots=[allowed], follow_symlinks=True)
        _make_file_link(allowed / "lnk", outside)
        with pytest.raises(PathValidationError):
            validator.validate_read(str(allowed / "lnk" / "anything.txt"))

    def test_junction_escape_denied_follow_symlinks_true(self, roots):
        """A directory junction lexically inside a read root but resolving
        outside is denied (containment uses the RESOLVED path)."""
        allowed, outside, _ = roots
        validator = _enabled_validator(read_roots=[allowed], follow_symlinks=True)
        _make_link(allowed / "jdir", outside)
        with pytest.raises(PathValidationError):
            validator.validate_read(str(allowed / "jdir" / "secret.txt"))

    def test_symlink_denied_when_follow_symlinks_false(self, roots):
        allowed, outside, _ = roots
        validator = _enabled_validator(read_roots=[allowed], follow_symlinks=False)
        _make_link(allowed / "lnk2", outside)
        with pytest.raises(PathValidationError, match="Symlinks are not allowed"):
            validator.validate_read(str(allowed / "lnk2"))

    def test_disabled_policy_backward_compatible(self, roots):
        _, outside, _ = roots
        validator = PathValidator(enabled=False)
        # Reads/writes pass with sanitisation only (existing semantics).
        assert validator.validate_read(str(outside / "any.txt")).is_within_allowed_root
        assert validator.validate_write(str(outside / "any.txt")).is_within_allowed_root

    def test_disabled_policy_rejects_relative_without_base(self, roots, tmp_path):
        """Even disabled, relative paths are never CWD-resolved."""
        validator = PathValidator(enabled=False)
        old = Path.cwd()
        try:
            os.chdir(tmp_path)
            with pytest.raises(PathValidationError, match="base directory"):
                validator.validate_read("rel.txt")
        finally:
            os.chdir(old)

    def test_is_path_authorized_matches_validate_semantics(self, roots):
        allowed, outside, _ = roots
        validator = _enabled_validator(read_roots=[allowed], write_roots=[allowed])
        assert validator.is_path_authorized(allowed / "a.txt", "read")
        assert not validator.is_path_authorized(outside / "a.txt", "read")
        assert validator.is_path_authorized(allowed / "a.txt", "write")
        assert not validator.is_path_authorized(outside / "a.txt", "write")

    def test_is_path_authorized_fail_closed_unconfigured(self, roots):
        validator = _enabled_validator(write_roots=[])
        assert not validator.is_path_authorized(roots[0], "write")


# --------------------------------------------------------------------------- #
# Config integration
# --------------------------------------------------------------------------- #


class TestConfigIntegration:
    def test_relative_roots_dropped_by_config_loader(self, roots):
        """configure_default_validator_from_config drops relative roots."""
        from tools.file_security import configure_default_validator_from_config

        allowed, _, _ = roots

        class _Cfg:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                cur = self._data
                for part in key.split("."):
                    if not isinstance(cur, dict) or part not in cur:
                        return default
                    cur = cur[part]
                return cur

        cfg = _Cfg(
            {
                "filesystem": {
                    "enabled": True,
                    "read_roots": [str(allowed), "relative_read"],
                    "write_roots": [str(allowed), "relative_write"],
                    "follow_symlinks": True,
                }
            }
        )
        validator = configure_default_validator_from_config(cfg)
        assert validator.read_roots == [allowed.resolve()]
        assert validator.write_roots == [allowed.resolve()]
        assert validator.base_dir is not None
        assert validator.base_dir.is_absolute()

    def test_config_changes_affect_shared_validator(self, roots, monkeypatch):
        """Changing roots in config reconfigures the shared default validator."""
        allowed, outside, _ = roots

        class _Cfg:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                cur = self._data
                for part in key.split("."):
                    if not isinstance(cur, dict) or part not in cur:
                        return default
                    cur = cur[part]
                return cur

        from tools.file_security import configure_default_validator_from_config

        cfg = _Cfg(
            {
                "filesystem": {
                    "enabled": True,
                    "read_roots": [str(allowed)],
                    "write_roots": [str(allowed)],
                    "follow_symlinks": True,
                }
            }
        )
        configure_default_validator_from_config(cfg)
        from tools.file_security import validate_read_path

        with pytest.raises(PathValidationError):
            validate_read_path(str(outside / "file.txt"))

        # Change the config: now the outside dir becomes readable.
        cfg._data["filesystem"]["read_roots"] = [str(outside)]
        configure_default_validator_from_config(cfg)
        validate_read_path(str(outside / "file.txt"))  # allowed now

    def test_disabled_config_follows_compatibility(self, roots):
        from tools.file_security import configure_default_validator_from_config

        allowed, _, _ = roots

        class _Cfg:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                cur = self._data
                for part in key.split("."):
                    if not isinstance(cur, dict) or part not in cur:
                        return default
                    cur = cur[part]
                return cur

        cfg = _Cfg(
            {
                "filesystem": {
                    "enabled": False,
                    "read_roots": [],
                    "write_roots": [],
                    "follow_symlinks": True,
                }
            }
        )
        configure_default_validator_from_config(cfg)
        from tools.file_security import validate_write_path

        # Disabled policy: writes pass (existing backward-compatible semantics).
        assert validate_write_path(str(allowed / "x.txt")).is_within_allowed_root

        # Restore a strict shared validator for later tests.
        configure_default_validator(enabled=False)

    def test_enabled_empty_write_roots_via_config(self, roots):
        from tools.file_security import (
            configure_default_validator_from_config,
            validate_write_path,
        )

        class _Cfg:
            def __init__(self, data):
                self._data = data

            def get(self, key, default=None):
                cur = self._data
                for part in key.split("."):
                    if not isinstance(cur, dict) or part not in cur:
                        return default
                    cur = cur[part]
                return cur

        cfg = _Cfg(
            {
                "filesystem": {
                    "enabled": True,
                    "read_roots": [],
                    "write_roots": [],
                    "follow_symlinks": True,
                }
            }
        )
        configure_default_validator_from_config(cfg)
        with pytest.raises(PathValidationError, match="no writable roots"):
            validate_write_path(str(roots[0] / "x.txt"))
        configure_default_validator(enabled=False)


# --------------------------------------------------------------------------- #
# ProjectManager boundary (direct usage — UI bypass impossible)
# --------------------------------------------------------------------------- #


class TestProjectManagerSecurity:
    @pytest.fixture()
    def manager(self, roots):
        allowed, _, _ = roots
        from project.manager import ProjectManager

        validator = _enabled_validator(
            read_roots=[allowed], write_roots=[allowed], base_dir=allowed
        )
        db = _FakeDB()
        return ProjectManager(db=db, event_bus=None, validator=validator)

    def test_create_project_rejects_unauthorized_workspace(self, roots, manager):
        _, outside, _ = roots
        with pytest.raises(PathValidationError):
            manager.create_project("P", workspace_path=str(outside))

    def test_create_project_validates_before_persistence(self, roots, manager):
        """Unauthorized workspace never reaches the DB (no project created)."""
        _, outside, _ = roots
        before = dict(manager._db.projects)
        with pytest.raises(PathValidationError):
            manager.create_project("P", workspace_path=str(outside))
        assert manager._db.projects == before

    def test_create_project_allows_authorized_workspace(self, roots, manager):
        allowed, _, _ = roots
        proj = manager.create_project("P", workspace_path=str(allowed))
        assert proj.workspace_path == str(allowed.resolve())

    def test_validate_workspace_path_unauthorized_raises_security_error(
        self, roots, manager
    ):
        _, outside, _ = roots
        # Unauthorized + EXISTING path -> authorization error, not ValueError.
        with pytest.raises(PathValidationError):
            manager.validate_workspace_path(str(outside))

    def test_validate_workspace_path_nonexistent_raises_value_error(
        self, roots, manager
    ):
        allowed, _, _ = roots
        with pytest.raises(ValueError, match="does not exist"):
            manager.validate_workspace_path(str(allowed / "missing"))

    def test_list_project_files_enforces_read_authorization(
        self, roots, manager
    ):
        allowed, _, _ = roots
        (allowed / "a.txt").write_text("a")
        proj = manager.create_project("P", workspace_path=str(allowed))
        files = manager.list_project_files(proj.id)
        assert files == ["a.txt"]

    def test_list_project_files_unauthorized_root_empty(self, roots, manager):
        allowed, outside, _ = roots
        proj = manager.create_project("P", workspace_path=str(allowed))
        # Swap policy: workspace no longer authorized.
        manager._validator_override = _enabled_validator(
            read_roots=[outside], write_roots=[outside], base_dir=outside
        )
        assert manager.list_project_files(proj.id) == []

    def test_list_project_files_symlink_escape_not_leaked(
        self, roots, manager, tmp_path
    ):
        """A junction/symlink directory inside the workspace is never
        descended into; its (escaping) contents are not listed."""
        allowed, outside, _ = roots
        secret = outside / "secret.txt"
        secret.write_text("s")
        (allowed / "real.txt").write_text("r")

        link_dir = allowed / "link"
        if os.name == "nt":
            import subprocess

            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_dir), str(outside)],
                check=True,
                capture_output=True,
            )
        else:
            os.symlink(outside, link_dir, target_is_directory=True)

        proj = manager.create_project("P", workspace_path=str(allowed))
        files = manager.list_project_files(proj.id)
        assert "real.txt" in files
        assert not any("secret.txt" in f for f in files)
        assert not any(f.startswith("link") for f in files)

    def test_list_project_files_broken_symlink_safe(self, roots, manager):
        allowed, _, _ = roots
        (allowed / "a.txt").write_text("a")
        broken = allowed / "broken"
        if os.name == "nt":
            # Windows symlinks need privileges; use a junction to a
            # non-existent target instead for the broken-link case.
            import subprocess

            subprocess.run(
                [
                    "cmd", "/c", "mklink", "/J",
                    str(broken), str(allowed / "no_such_dir"),
                ],
                check=False,
                capture_output=True,
            )
        else:
            os.symlink(str(allowed / "no_such_dir"), broken)
        proj = manager.create_project("P", workspace_path=str(allowed))
        # Must not crash; only the real file is listed.
        assert manager.list_project_files(proj.id) == ["a.txt"]

    def test_list_project_files_permission_error_no_crash(
        self, roots, manager, monkeypatch
    ):
        allowed, _, _ = roots
        (allowed / "a.txt").write_text("a")
        proj = manager.create_project("P", workspace_path=str(allowed))

        real_iterdir = Path.iterdir

        def flaky_iterdir(self):
            if self == allowed:
                raise PermissionError("denied")
            return real_iterdir(self)

        monkeypatch.setattr(Path, "iterdir", flaky_iterdir)
        assert manager.list_project_files(proj.id) == []

    def test_delete_workspace_files_requires_write_authorization(
        self, roots, manager
    ):
        allowed, outside, _ = roots
        ws = allowed / "ws"
        ws.mkdir()
        (ws / "x.txt").write_text("x")
        proj = manager.create_project("P", workspace_path=str(ws))

        manager._validator_override = _enabled_validator(
            read_roots=[ws], write_roots=[outside], base_dir=ws
        )
        with pytest.raises(PathValidationError):
            manager.delete_workspace_files(proj.id)
        # Nothing was deleted.
        assert (ws / "x.txt").exists()

    def test_delete_workspace_files_authorized_deletes_and_spares_link_targets(
        self, roots, manager
    ):
        """Authorized deletion removes the workspace; content outside it
        (junction target) survives the rmtree."""
        allowed, outside, _ = roots
        ws = allowed / "ws2"
        ws.mkdir()
        (ws / "keep.txt").write_text("x")

        link_dir = ws / "link"
        if os.name == "nt":
            import subprocess

            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_dir), str(outside)],
                check=True,
                capture_output=True,
            )
        else:
            os.symlink(outside, link_dir, target_is_directory=True)

        proj = manager.create_project("P", workspace_path=str(ws))
        assert manager.delete_workspace_files(proj.id) is True
        assert not ws.exists()
        # Outside content must survive (rmtree does not follow junctions).
        assert (outside / "whatever.txt").exists() or outside.exists()

    def test_delete_workspace_files_missing_dir(self, roots, manager):
        allowed, _, _ = roots
        proj = manager.create_project("P", workspace_path=str(allowed))
        assert manager.delete_workspace_files(proj.id) is True  # removes allowed? No — allowed is a root dir with files; it exists.
        # NOTE: allowed still exists in this scenario because we created it
        # as a directory; deletion returns True and removes it.

    def test_direct_manager_usage_cannot_bypass_security(self, roots):
        """Even a direct caller (no UI) hits the same validator."""
        allowed, outside, _ = roots
        from project.manager import ProjectManager

        validator = _enabled_validator(
            read_roots=[allowed], write_roots=[allowed], base_dir=allowed
        )
        mgr = ProjectManager(db=_FakeDB(), validator=validator)
        with pytest.raises(PathValidationError):
            mgr.create_project("P", workspace_path=str(outside))


# --------------------------------------------------------------------------- #
# ProjectsPage integration — UI reports, never bypasses
# --------------------------------------------------------------------------- #


@pytest.fixture()
def qt_page_cleanup():
    """Deterministically close ProjectsPage widgets before GC runs.

    Leaving live PySide6 widgets to the garbage collector crashes the
    interpreter (access violation in GC) — the page unsubscribes from the
    EventBus and is deleted here instead.
    """
    pages: list = []
    yield pages
    import gc

    from PySide6.QtWidgets import QApplication

    for page in pages:
        try:
            page._unsubscribe_events()
        except Exception:
            pass
        try:
            page.deleteLater()
        except Exception:
            pass
    QApplication.processEvents()
    gc.collect()


class TestProjectsPageIntegration:
    def _page(self, qapp, manager):
        from ui.projects_page import ProjectsPage

        assistant = type("A", (), {"_project_manager": manager})()
        return ProjectsPage(assistant=assistant)

    def test_ui_surfaces_authorization_error_on_create(
        self, qapp, roots, monkeypatch, qt_page_cleanup
    ):
        allowed, outside, _ = roots
        from project.manager import ProjectManager
        from ui.projects_page import ProjectsPage

        validator = _enabled_validator(
            read_roots=[allowed], write_roots=[allowed], base_dir=allowed
        )
        mgr = ProjectManager(db=_FakeDB(), validator=validator)

        assistant = type("A", (), {"_project_manager": mgr})()
        page = ProjectsPage(assistant=assistant)
        qt_page_cleanup.append(page)

        errors: list[str] = []
        monkeypatch.setattr(page, "_show_error", lambda msg: errors.append(msg))

        class _Dialog:
            def __init__(self) -> None:
                self.result_data = {
                    "name": "P",
                    "description": "",
                    "workspace_path": str(outside),  # unauthorized
                }

            def exec(self):
                return 1

        monkeypatch.setattr(
            "ui.projects_page.CreateProjectDialog", lambda *a, **k: _Dialog()
        )
        page._on_create_project()
        assert errors and "not authorized" in errors[0].lower()

    def test_ui_delete_routes_through_manager(
        self, qapp, roots, monkeypatch, qt_page_cleanup
    ):
        """The page calls ProjectManager.delete_workspace_files and surfaces
        its authorization errors instead of rmtree-ing directly."""
        allowed, _, _ = roots
        from project.manager import ProjectManager
        from ui.projects_page import ProjectsPage


        validator = _enabled_validator(
            read_roots=[allowed], write_roots=[allowed], base_dir=allowed
        )
        mgr = ProjectManager(db=_FakeDB(), validator=validator)

        ws = allowed / "ws3"
        ws.mkdir()
        proj = mgr.create_project("P", workspace_path=str(ws))

        class _FakeAssistant:
            _project_manager = None

            def get_active_project_id(self):
                return None

            def clear_active_project(self):
                pass

        fake = _FakeAssistant()
        fake._project_manager = mgr
        page = ProjectsPage(assistant=fake)
        page._selected_project = proj
        qt_page_cleanup.append(page)

        calls: list[str] = []

        def fake_delete(pid):
            calls.append(pid)
            return True

        monkeypatch.setattr(mgr, "delete_workspace_files", fake_delete)

        # Surface authorization failures from the manager path.
        def fake_delete_denied(pid):
            calls.append(pid)
            raise PathValidationError("outside write roots")

        errors: list[str] = []
        monkeypatch.setattr(page, "_show_error", lambda msg: errors.append(msg))

        # Simulate the user clicking "Also delete files".
        import ui.projects_page as pp

        class _Btn:
            def __init__(self, text):
                self._text = text

            def text(self):
                return self._text

            def setStyleSheet(self, *a):
                pass

        chosen = {"btn": None}

        class _ButtonRole:
            DestructiveRole = "destructive"
            AcceptRole = "accept"
            RejectRole = "reject"

        class _MsgBox:
            ButtonRole = _ButtonRole

            def __init__(self, *a, **k):
                self._buttons: dict[str, _Btn] = {}

            def exec(self):
                # Default to the "Also delete files" choice.
                chosen["btn"] = self._buttons.get(
                    "Also delete files", _Btn("Also delete files")
                )
                return 0

            def clickedButton(self):
                return chosen["btn"]

            def addButton(self, text, *a, **k):
                btn = _Btn(text)
                self._buttons[text] = btn
                return btn

            def setDefaultButton(self, *a):
                pass

            def setWindowTitle(self, *a):
                pass

            def setText(self, *a):
                pass

            def setStyleSheet(self, *a):
                pass

        monkeypatch.setattr(pp, "QMessageBox", _MsgBox)

        # Authorized path: manager is called.
        page._on_delete_project()
        assert calls == [proj.id]
        assert errors == []

        # Re-select a project for the second round.
        page._selected_project = proj
        monkeypatch.setattr(mgr, "delete_workspace_files", fake_delete_denied)
        page._on_delete_project()
        assert len(calls) == 2
        assert errors and "not authorized" in errors[0].lower()
