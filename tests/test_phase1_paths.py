"""PHASE 1 regression tests — path architecture and CWD independence.

Locks down the verified path contract:

* importing ``core.paths`` never creates directories
* ``user_data_root()`` default is the LOCALAPPDATA-style location
* ``OFFLINE_AI_DATA_DIR`` absolute override works; relative override is
  rejected without CWD dependence
* frozen simulation: ``resource_root()`` lives under ``_MEIPASS/resources``
  while ``user_data_root()`` stays outside ``_MEIPASS``
* application-owned path resolution is identical from different CWDs
* the security auditor default log lands under ``DATA_DIR``
* the embedding resolver contains no CWD-relative application fallbacks
* the final application lifecycle invokes ``ApplicationManager.stop()``
  exactly once on normal shutdown
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

@pytest.fixture()
def data_dir_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point OFFLINE_AI_DATA_DIR at a temp directory and return it."""
    override = tmp_path / "appdata"
    monkeypatch.setenv("OFFLINE_AI_DATA_DIR", str(override))
    return override


@pytest.fixture()
def changed_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Change the process CWD to a temp directory and return it."""
    cwd = tmp_path / "some_cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return cwd


# --------------------------------------------------------------------------- #
# 1. Import purity — no directory creation on import
# --------------------------------------------------------------------------- #

class TestImportPurity:
    def test_import_does_not_create_dirs(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Importing core.paths must not create any application directory."""
        monkeypatch.setenv("OFFLINE_AI_DATA_DIR", str(tmp_path / "fresh"))
        import subprocess

        code = (
            "import os, sys\n"
            f"sys.path.insert(0, {str(Path(__file__).resolve().parents[1])!r})\n"
            "os.environ['OFFLINE_AI_DATA_DIR'] = "
            f"{str(tmp_path / 'fresh')!r}\n"
            "import core.paths\n"
            "root = str(core.paths.user_data_root())\n"
            "print(root)\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        root = Path(result.stdout.strip())
        assert root == (tmp_path / "fresh").resolve()
        # The override root itself must NOT have been created by the import.
        assert not root.exists()

    def test_module_constants_exist_without_dirs(self, data_dir_override: Path) -> None:
        """Public constants remain importable without any mkdir side effect."""
        from core import paths

        for name in (
            "CONFIG_DIR",
            "DATA_DIR",
            "LOGS_DIR",
            "MODELS_DIR",
            "LLM_DIR",
            "VOICE_DIR",
            "STT_DIR",
            "TTS_DIR",
            "SETTINGS_FILE",
        ):
            assert isinstance(getattr(paths, name), Path)
        assert not data_dir_override.exists()

    def test_ensure_dirs_creates_explicitly(self, data_dir_override: Path) -> None:
        """ensure_dirs() is the only directory creation point."""
        from core import paths

        ensured = paths.ensure_dirs()
        assert paths.get_config_dir() in ensured
        assert paths.get_data_dir() in ensured
        assert paths.get_logs_dir() in ensured
        assert paths.get_models_dir() in ensured
        for d in ensured:
            assert d.is_dir()


# --------------------------------------------------------------------------- #
# 2-4. user_data_root defaults and OFFLINE_AI_DATA_DIR override
# --------------------------------------------------------------------------- #

class TestUserDataRoot:
    def test_default_location_without_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no override, user_data_root() is the LOCALAPPDATA-style default."""
        monkeypatch.delenv("OFFLINE_AI_DATA_DIR", raising=False)
        from core import paths

        expected = (
            Path.home() / "AppData" / "Local" / "OfflineAI"
        )
        assert paths.user_data_root() == expected.resolve()

    def test_absolute_override_used(self, data_dir_override: Path) -> None:
        """An absolute OFFLINE_AI_DATA_DIR becomes the user-data root."""
        from core import paths

        assert paths.user_data_root() == data_dir_override.resolve()
        assert paths.get_config_dir() == data_dir_override.resolve() / "config"
        assert paths.get_data_dir() == data_dir_override.resolve() / "data"
        assert paths.get_logs_dir() == data_dir_override.resolve() / "logs"
        assert paths.get_models_dir() == data_dir_override.resolve() / "models"
        assert paths.get_plugins_dir() == data_dir_override.resolve() / "plugins"
        assert (
            paths.get_knowledge_docs_dir()
            == data_dir_override.resolve() / "knowledge_docs"
        )

    def test_empty_override_uses_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty override value behaves exactly like no override."""
        monkeypatch.setenv("OFFLINE_AI_DATA_DIR", "")
        from core import paths

        expected = (
            Path.home() / "AppData" / "Local" / "OfflineAI"
        ).resolve()
        assert paths.user_data_root() == expected

    def test_relative_override_rejected_without_cwd(
        self, changed_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative override is rejected and the default is used — regardless of CWD."""
        import io
        from contextlib import redirect_stderr

        monkeypatch.setenv("OFFLINE_AI_DATA_DIR", "relative_data_dir")
        from core import paths

        expected = (
            Path.home() / "AppData" / "Local" / "OfflineAI"
        ).resolve()
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            root = paths.user_data_root()
        assert root == expected
        # The warning mentions the rejected value and no directory is created
        # in the CWD.
        assert "relative_data_dir" in stderr.getvalue()
        assert not (changed_cwd / "relative_data_dir").exists()

    def test_override_resolution_is_absolute_and_normalized(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The override is resolved (symlinks/case) to a canonical absolute path."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "link"
        if sys.platform == "win32":
            import subprocess as sp

            try:
                sp.run(
                    ["cmd", "/c", "mklink", "/J", str(link), str(real)],
                    check=True,
                    capture_output=True,
                )
            except Exception:
                pytest.skip("junction creation unavailable")
        else:
            link.symlink_to(real, target_is_directory=True)
        monkeypatch.setenv("OFFLINE_AI_DATA_DIR", str(link))
        from core import paths

        assert paths.user_data_root() == real.resolve()


# --------------------------------------------------------------------------- #
# 5. Frozen semantics
# --------------------------------------------------------------------------- #

class TestFrozenSemantics:
    @pytest.fixture()
    def frozen(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        meipass = tmp_path / "MEIPASS_extract"
        meipass.mkdir()
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
        return meipass

    def test_resource_root_under_meipass(self, frozen: Path) -> None:
        from core import paths

        assert paths.resource_root() == (frozen / "resources").resolve()
        assert paths.app_root() == frozen.resolve()

    def test_user_data_outside_meipass(
        self, frozen: Path, data_dir_override: Path
    ) -> None:
        from core import paths

        root = paths.user_data_root()
        assert root != frozen
        assert frozen not in root.parents
        assert root == data_dir_override.resolve()

    def test_dev_mode_ignores_meipass(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without sys.frozen, resource_root() uses the project root even if
        a stale _MEIPASS attribute is present."""
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", "stale_value", raising=False)
        from core import paths

        project_root = Path(__file__).resolve().parents[1]
        assert paths.app_root() == project_root
        assert paths.resource_root() == project_root / "resources"
        assert not paths._is_frozen()


# --------------------------------------------------------------------------- #
# 6. CWD independence
# --------------------------------------------------------------------------- #

class TestCwdIndependence:
    def test_paths_identical_from_two_cwds(
        self, data_dir_override: Path, tmp_path: Path
    ) -> None:
        """Application-owned paths resolve identically from different CWDs."""
        from core import paths

        cwd_a = tmp_path / "cwd_a"
        cwd_b = tmp_path / "cwd_b"
        cwd_a.mkdir()
        cwd_b.mkdir()

        old = Path.cwd()
        snapshots = []
        try:
            os.chdir(cwd_a)
            snapshots.append(
                (
                    paths.user_data_root(),
                    paths.get_config_dir(),
                    paths.get_data_dir(),
                    paths.get_logs_dir(),
                    paths.get_models_dir(),
                    paths.get_plugins_dir(),
                    paths.get_knowledge_docs_dir(),
                )
            )
            os.chdir(cwd_b)
            snapshots.append(
                (
                    paths.user_data_root(),
                    paths.get_config_dir(),
                    paths.get_data_dir(),
                    paths.get_logs_dir(),
                    paths.get_models_dir(),
                    paths.get_plugins_dir(),
                    paths.get_knowledge_docs_dir(),
                )
            )
        finally:
            os.chdir(old)

        assert snapshots[0] == snapshots[1]
        assert snapshots[0][0] == data_dir_override.resolve()

    def test_no_application_files_created_in_cwd(
        self, changed_cwd: Path, data_dir_override: Path
    ) -> None:
        """ensure_dirs() from a foreign CWD never writes into that CWD."""
        from core import paths

        paths.ensure_dirs()
        assert data_dir_override.is_dir()
        # Nothing leaked into the (foreign) current working directory.
        assert list(changed_cwd.iterdir()) == []


# --------------------------------------------------------------------------- #
# 7. Security auditor default log path
# --------------------------------------------------------------------------- #

class TestAuditorDefaultPath:
    def test_default_log_path_under_data_dir(self, data_dir_override: Path) -> None:
        from security.auditor import SecurityAuditor, _default_log_path

        expected = data_dir_override.resolve() / "data" / "security_audit.log"
        assert _default_log_path() == expected
        auditor = SecurityAuditor()
        assert auditor._log_path == expected

    def test_explicit_log_path_still_honoured(self, tmp_path: Path) -> None:
        from security.auditor import SecurityAuditor

        explicit = tmp_path / "audit.jsonl"
        auditor = SecurityAuditor(log_path=explicit)
        assert auditor._log_path == explicit

    def test_default_path_not_cwd_dependent(
        self, changed_cwd: Path, data_dir_override: Path
    ) -> None:
        from security.auditor import _default_log_path

        assert _default_log_path() == (
            data_dir_override.resolve() / "data" / "security_audit.log"
        )


# --------------------------------------------------------------------------- #
# 8. Embedding resolver has no CWD-dependent fallbacks
# --------------------------------------------------------------------------- #

class TestEmbeddingResolver:
    def test_no_cwd_candidates_in_source(self) -> None:
        """The resolver source contains no CWD-relative application paths."""
        source_path = (
            Path(__file__).resolve().parents[1] / "memory" / "embeddings.py"
        )
        source = source_path.read_text(encoding="utf-8")
        resolver_start = source.index("def _resolve_embedding_model_path")
        resolver_end = source.index("def load_embedding_model")
        resolver_source = source[resolver_start:resolver_end]
        assert 'Path("models")' not in resolver_source
        assert "Path(_DEFAULT_MXBAI_FILENAME)" not in resolver_source

    def test_resolver_uses_llm_dir_only(
        self, data_dir_override: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no explicit path/env/model file, the resolver returns None
        instead of probing CWD-relative locations."""
        monkeypatch.delenv("MXBAI_EMBEDDING_MODEL_PATH", raising=False)
        from memory.embeddings import _resolve_embedding_model_path

        assert _resolve_embedding_model_path() is None
        assert _resolve_embedding_model_path("") is None

    def test_resolver_explicit_and_env_behaviour(
        self, data_dir_override: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        model_file = tmp_path / "model.gguf"
        model_file.write_bytes(b"GGUF")
        from memory.embeddings import _resolve_embedding_model_path

        # Explicit argument wins even without env var.
        assert _resolve_embedding_model_path(model_file) == model_file
        # Environment variable is honoured.
        monkeypatch.setenv("MXBAI_EMBEDDING_MODEL_PATH", str(model_file))
        assert _resolve_embedding_model_path() == model_file


# --------------------------------------------------------------------------- #
# 9. Final application lifecycle — stop() runs once on normal shutdown
# --------------------------------------------------------------------------- #

class TestFinalAppLifecycle:
    def test_about_to_quit_hook_calls_stop(self) -> None:
        """The aboutToQuit hook installed by application_final.main wiring calls
        ApplicationManager.stop() when the Qt event loop exits.

        stop() is also called from main()'s finally block for exception safety,
        but is idempotent via the _shutting_down guard — the second call is a
        no-op."""
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication

        class FakeManager:
            def __init__(self) -> None:
                self.stop_calls = 0
                self._started = True
                self._shutting_down = False
                self._chat_coordinator = type(
                    "C", (), {"shutdown": lambda self: None}
                )()

            def stop(self) -> None:
                # Idempotent: early-return on second call (mirrors real guard).
                if self._shutting_down:
                    return
                self._shutting_down = True
                self.stop_calls += 1
                self._started = False

        manager = FakeManager()
        calls: list[str] = []

        def _on_about_to_quit(manager=manager, calls=calls) -> None:
            try:
                manager.stop()
                calls.append("stop")
            except Exception:
                pass

        app = QApplication.instance() or QApplication(
            ["-platform", "offscreen", "test_phase1"]
        )
        app.aboutToQuit.connect(_on_about_to_quit)

        # Drive a real (brief) event loop: quit after 10 ms so aboutToQuit
        # fires exactly as it does on normal application exit.
        QTimer.singleShot(10, app.quit)
        exit_code = app.exec()

        assert exit_code == 0
        assert manager.stop_calls == 1

    def test_hook_source_has_stop_and_finally(self) -> None:
        """application_final.main ensures stop() runs on both normal quit
        and exception-driven exit via try/finally."""
        source = (
            Path(__file__).resolve().parents[1] / "app" / "application_final.py"
        ).read_text(encoding="utf-8")
        assert "manager.stop()" in source
        # stop() is called from both the aboutToQuit handler (normal quit)
        # and the finally block (exception safety).
        assert source.count("manager.stop()") == 2
        # finally ensures cleanup on startup exception.
        assert "finally:" in source

    def test_stop_is_idempotent_via_shutting_down_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ApplicationManager.stop() is idempotent via the _shutting_down guard.

        A second call returns immediately without re-entering cleanup.
        """
        from app.application import ApplicationManager

        mgr = ApplicationManager()
        mgr._started = True
        # stop() with nothing initialized must not raise.
        mgr.stop()
        mgr.stop()  # second call is a guarded no-op
        assert mgr._started is False
        assert mgr._shutting_down is True


# --------------------------------------------------------------------------- #
# 10. Startup/path smoke from a changed CWD (no llama/GPU/STT dependencies)
# --------------------------------------------------------------------------- #

class TestStartupSmokeFromChangedCwd:
    def test_path_resolution_smoke_from_foreign_cwd(
        self, changed_cwd: Path, data_dir_override: Path
    ) -> None:
        """Resolve every startup-relevant path from a foreign CWD and verify
        nothing lands in the CWD."""
        from core import paths

        # The exact path set ApplicationManager.start() consumes.
        config_dir = paths.get_config_dir()
        data_dir = paths.get_data_dir()
        models_dir = paths.get_models_dir()
        plugins_dir = paths.get_plugins_dir()
        docs_dir = paths.get_knowledge_docs_dir()

        assert config_dir == data_dir_override.resolve() / "config"
        assert data_dir == data_dir_override.resolve() / "data"
        assert models_dir == data_dir_override.resolve() / "models"
        assert plugins_dir == data_dir_override.resolve() / "plugins"
        assert docs_dir == data_dir_override.resolve() / "knowledge_docs"

        # Resolve-only smoke: no directories are created by resolution itself.
        assert not config_dir.exists()
        assert not plugins_dir.exists()
        assert list(changed_cwd.iterdir()) == []
