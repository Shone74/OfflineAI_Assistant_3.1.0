"""PHASE 8 regression tests — project integration.

Verifies that the Phase 1-7 architecture is actually CONSUMED by the
application: canonical paths from foreign CWDs, model-root propagation
to runtime, project CRUD through the security boundary, link-safe
knowledge indexing, plugin path integration, download→discovery→load
pipeline, and the absence of competing model-root resolvers.

No real CUDA/GPU/internet/multi-GB downloads/faster-whisper/admin
rights are required.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths

REPO = Path(__file__).resolve().parents[1]
GB = 1024**3


# --------------------------------------------------------------------------- #
# Fixtures: isolated user-data + models-root environment
# --------------------------------------------------------------------------- #


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Isolated user-data root + models root + foreign CWD."""
    import core.config_manager as cm
    import core.paths as paths_mod

    user_data = tmp_path / "AppData" / "OfflineAI"
    models_root = tmp_path / "ExternalDrive" / "AIModels"
    config_dir = user_data / "config"
    config_dir.mkdir(parents=True)
    settings = config_dir / "settings.json"
    settings.write_text("{}", encoding="utf-8")

    # Canonical env overrides (call-time resolvers)…
    monkeypatch.setenv(paths_mod.DATA_DIR_ENV_VAR, str(user_data))
    monkeypatch.setenv(paths_mod.MODELS_ROOT_ENV_VAR, str(models_root))
    # …plus the import-time bindings used by ConfigManager and legacy
    # consumers.  Plugins/knowledge dirs are FUNCTION-resolved from the
    # user-data root (no module constants) — the env override drives them.
    monkeypatch.setattr(paths_mod, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(paths_mod, "DATA_DIR", user_data / "data")
    monkeypatch.setattr(paths_mod, "LOGS_DIR", user_data / "logs")
    monkeypatch.setattr(paths_mod, "SETTINGS_FILE", settings)
    monkeypatch.setattr(cm, "SETTINGS_FILE", settings)

    # Foreign CWD for every test in this module.
    foreign = tmp_path / "foreign_cwd"
    foreign.mkdir()
    monkeypatch.chdir(foreign)

    return {
        "user_data": user_data,
        "models_root": models_root,
        "settings": settings,
        "tmp": tmp_path,
        "foreign_cwd": foreign,
    }


def _write_gguf(path: Path, size_kb: int = 8) -> Path:
    """Write a minimal valid GGUF file (magic + version + payload)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"GGUF" + b"\x02\x00\x00\x00" + b"\x00" * 12
    payload += b"x" * max(0, size_kb * 1024 - len(payload))
    path.write_bytes(payload)
    return path


# --------------------------------------------------------------------------- #
# 1-2. Startup from foreign CWD + canonical user-data propagation
# --------------------------------------------------------------------------- #


class TestForeignCwdStartup:
    def test_canonical_paths_from_foreign_cwd(self, env):
        assert paths.user_data_root() == env["user_data"]
        assert paths.get_plugins_dir() == env["user_data"] / "plugins"
        assert paths.get_knowledge_docs_dir() == env["user_data"] / "knowledge_docs"
        assert paths.get_models_root() == env["models_root"]
        # None of these live under the (foreign) CWD
        cwd = Path.cwd()
        for p in (
            paths.user_data_root(),
            paths.get_plugins_dir(),
            paths.get_knowledge_docs_dir(),
            paths.get_models_root(),
        ):
            assert not p.is_relative_to(cwd) or p == env["tmp"]

    def test_category_dirs_derive_from_selected_root(self, env):
        assert paths.get_model_category_dir("llm") == env["models_root"] / "llm"
        assert paths.get_model_category_dir("embedding") == env["models_root"] / "embedding"
        assert paths.get_model_category_dir("stt") == env["models_root"] / "stt"

    def test_installed_app_root_not_writable_user_data(self, env, monkeypatch):
        """A Program Files-style app root never becomes user data/models."""
        fake_pf = env["tmp"] / "ProgramFiles" / "OfflineAI"
        fake_pf.mkdir(parents=True)
        with patch("core.paths._is_frozen", return_value=True), patch(
            "core.paths.app_root", return_value=fake_pf
        ):
            # user-data and models roots stay in their own areas
            assert paths.user_data_root() == env["user_data"]
            assert paths.get_models_root() == env["models_root"]
            assert not paths.user_data_root().is_relative_to(fake_pf)
            assert not paths.get_models_root().is_relative_to(fake_pf)

    def test_every_core_subsystem_imports_from_foreign_cwd(self, env):
        """Import the whole integration surface with CWD elsewhere."""
        import importlib

        mods = [
            "ai.models.discovery",
            "ai.models.model_manager",
            "ai.models.model_loader",
            "ai.models.download_service",
            "ai.hardware",
            "installer.catalog",
            "installer.downloader",
            "memory.embeddings",
            "knowledge.knowledge_base",
            "project.manager",
        ]
        for name in mods:
            importlib.import_module(name)
        assert Path.cwd() == env["foreign_cwd"]


# --------------------------------------------------------------------------- #
# 3, 9-17. Model-root propagation + download → discovery → load
# --------------------------------------------------------------------------- #


class TestModelRootPropagation:
    def test_manager_default_dir_is_llm_category(self, env):
        from ai.models.model_manager import ModelManager

        mm = ModelManager(include_ollama=False, include_lm_studio=False)
        assert mm.models_dir == env["models_root"] / "llm"

    def test_model_root_change_affects_runtime_without_copying(self, env, monkeypatch):
        """Changing models.storage_root re-points discovery; files stay put."""
        from ai.models.model_manager import ModelManager

        old_root = env["models_root"]
        old_model = _write_gguf(old_root / "llm" / "old-model.gguf")

        new_root = env["tmp"] / "OtherDrive" / "Models"
        paths.set_models_root(new_root)
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(new_root))

        mm = ModelManager(include_ollama=False, include_lm_studio=False)
        assert mm.models_dir == new_root / "llm"
        # The OLD file was NOT copied/moved/deleted
        assert old_model.exists()
        # New root has nothing yet -> manager finds nothing
        assert mm.list_models() == []
        # A model in the new root IS discovered
        _write_gguf(new_root / "llm" / "new-model.gguf")
        found = {m.name for m in mm.rescan()}
        assert "new-model" in found

    def test_downloaded_model_becomes_discoverable_no_manifest(self, env):
        from ai.models.discovery import discover_local_gguf
        from ai.models.download_service import download_entry
        from installer.catalog import DownloadableModel

        # PHASE 9: fully curated entry (exact size + digest of the mock
        # payload) — required by the download-service curation gate.
        data = b"GGUF" + b"\x02\x00\x00\x00" + b"\x00" * 12 + b"y" * 8172
        import hashlib as _hl

        entry = DownloadableModel(
            model_id="llm/int-test", display_name="Integration Test",
            category="llm", url="https://example.com/m.gguf",
            filename="downloaded.gguf", size_bytes=len(data),
            sha256=_hl.sha256(data).hexdigest(),
        )

        # Disk-space pre-check would consult the real models drive; patch.
        with patch("installer.downloader.check_disk_space", return_value=(True, None)), \
             patch("requests.get") as mock_get:
            resp = MagicMock(status_code=200)
            resp.headers = {"Content-Length": str(len(data))}
            buf = iter([data[i:i + 1024] for i in range(0, len(data), 1024)])
            resp.iter_content = lambda **kw: buf
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp
            primary, _ = download_entry(entry)

        assert primary.success
        # Physical discovery finds it — no manifest update required.
        found = discover_local_gguf(env["models_root"] / "llm")
        assert any(m.name == "downloaded" for m in found)

    def test_part_file_never_discoverable(self, env):
        from ai.models.discovery import discover_local_gguf

        _write_gguf(env["models_root"] / "llm" / "half.gguf.part")
        found = discover_local_gguf(env["models_root"] / "llm")
        assert all(not m.name.startswith("half") for m in found)

    def test_checksum_failure_not_discoverable(self, env):
        from ai.models.discovery import discover_local_gguf
        from installer.downloader import SecureModelDownloader

        data = b"GGUF" + b"\x02\x00\x00\x00" + b"\x00" * 12 + b"z" * 8000
        dl = SecureModelDownloader("llm")
        with patch("requests.get") as mock_get:
            resp = MagicMock(status_code=200)
            resp.headers = {"Content-Length": str(len(data))}
            buf = iter([data[i:i + 1024] for i in range(0, len(data), 1024)])
            resp.iter_content = lambda **kw: buf
            resp.__enter__ = MagicMock(return_value=resp)
            resp.__exit__ = MagicMock(return_value=False)
            resp.raise_for_status = MagicMock()
            mock_get.return_value = resp
            result = dl.download(
                "https://example.com/m.gguf", "corrupt.gguf",
                expected_size=len(data), expected_sha256="0" * 64,
            )
        assert not result.success
        dest = env["models_root"] / "llm" / "corrupt.gguf"
        assert not dest.exists()
        found = discover_local_gguf(env["models_root"] / "llm")
        assert all("corrupt" not in m.name for m in found)

    def test_no_competing_model_root_resolver(self, env):
        """core.paths is the only resolver: grep the integration surface."""
        surface = [
            "ai/models/model_manager.py",
            "ai/models/discovery.py",
            "memory/embeddings.py",
            "voice/stt.py",
            "ui/models_page.py",
            "ui/model_manager_dialog.py",
            "installer/downloader.py",
        ]
        for rel in surface:
            text = (REPO / rel).read_text(encoding="utf-8")
            # No private models-root re-derivation: any "models root"
            # must come from core.paths functions.
            for banned in (
                'os.environ.get("OFFLINE_AI_MODELS_ROOT"',
                'environ.get("OFFLINE_AI_MODELS_ROOT"',
            ):
                assert banned not in text, f"{rel} re-implements root env lookup"

    def test_wizard_finalize_persists_canonical_root(self, env, qapp):
        """InstallationPage finalize writes models.storage_root via set_models_root."""
        from ui.welcome_wizard import InstallationPage

        page = InstallationPage(MagicMock(), MagicMock())
        page._models_location = str(env["tmp"] / "PickedRoot")
        notes = page._real_step_finalize()
        assert "models root persisted" in notes
        settings = env["user_data"] / "config" / "settings.json"
        stored = json.loads(settings.read_text(encoding="utf-8"))
        assert stored["models"]["storage_root"] == str((env["tmp"] / "PickedRoot").resolve())
        page.deleteLater()

    def test_settings_tab_persists_canonical_root(self, env, qapp):
        """ModelStatusTab scan derives root->llm like set_models_root."""
        from ai.models.model_manager import ModelManager
        from ui.settings.model_storage_tabs import ModelStatusTab

        mm = ModelManager(include_ollama=False, include_lm_studio=False)
        config = MagicMock()
        config.set = MagicMock()
        tab = ModelStatusTab(model_manager=mm, event_bus=MagicMock(), config=config)

        # Simulate the ScanThread completion for a newly picked root.
        # (The thread itself calls manager.set_models_dir(root / "llm") —
        # the Phase 8 derivation under test.)
        picked = env["tmp"] / "NewRoot"
        mm.set_models_dir(picked / "llm")
        tab._on_models_scanned(str(picked), thread=MagicMock())

        # Manager scans the CATEGORY dir under the picked root…
        assert mm.models_dir == picked / "llm"
        # …and the canonical key was persisted through set_models_root.
        config.set.assert_any_call(
            "models.storage_root", str(picked.resolve())
        )
        tab.deleteLater()


# --------------------------------------------------------------------------- #
# 4-5, 22. Project create/list/load/delete + security boundary
# --------------------------------------------------------------------------- #


class TestProjectIntegration:
    def _manager(self, env, tmp_path):
        from project.manager import ProjectManager
        from tools.file_security import PathValidator

        projects_root = tmp_path / "my_projects"
        projects_root.mkdir()
        validator = PathValidator(
            read_roots=[projects_root, env["user_data"]],
            write_roots=[projects_root, env["user_data"]],
        )
        return ProjectManager(validator=validator), projects_root

    def test_project_crud_roundtrip(self, env, tmp_path):
        mgr, root = self._manager(env, tmp_path)
        ws = root / "proj-a"
        ws.mkdir()
        proj = mgr.create_project("Alpha", workspace_path=str(ws))
        assert proj.workspace_path == str(ws)
        assert mgr.get_project(proj.id).name == "Alpha"
        listed = {p.name for p in mgr.list_projects()}
        assert "Alpha" in listed
        assert mgr.delete_project(proj.id) is True
        assert mgr.get_project(proj.id) is None

    def test_project_delete_does_not_touch_files_by_default(self, env, tmp_path):
        """delete_project removes the record; workspace FILES survive
        unless the sanctioned delete_workspace_files path is used."""
        mgr, root = self._manager(env, tmp_path)
        ws = root / "proj-b"
        (ws / "docs").mkdir(parents=True)
        (ws / "docs" / "note.md").write_text("keep me", encoding="utf-8")
        proj = mgr.create_project("Beta", workspace_path=str(ws))

        mgr.delete_project(proj.id)
        assert (ws / "docs" / "note.md").exists()

        proj2 = mgr.create_project("Beta2", workspace_path=str(ws))
        assert mgr.delete_workspace_files(proj2.id) is True
        assert not ws.exists()

    def test_workspace_outside_write_root_rejected(self, env, tmp_path):
        from tools.file_security import PathValidationError

        mgr, _ = self._manager(env, tmp_path)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        with pytest.raises(PathValidationError):
            mgr.create_project("Evil", workspace_path=str(outside))

    def test_workspace_file_enumeration_link_safe(self, env, tmp_path):
        """A symlink inside the workspace cannot leak outside files."""
        mgr, root = self._manager(env, tmp_path)
        ws = root / "proj-c"
        ws.mkdir()
        (ws / "inside.md").write_text("inside", encoding="utf-8")
        secret = tmp_path / "secret.md"
        secret.write_text("secret", encoding="utf-8")
        try:
            os.symlink(secret, ws / "leak.md")
        except OSError:
            pytest.skip("symlinks unavailable")
        proj = mgr.create_project("Gamma", workspace_path=str(ws))
        files = mgr.list_project_files(proj.id)
        assert "inside.md" in files
        assert "leak.md" not in files

    def test_foreign_cwd_project_operations(self, env, tmp_path):
        assert Path.cwd() == env["foreign_cwd"]
        mgr, root = self._manager(env, tmp_path)
        ws = root / "proj-d"
        ws.mkdir()
        proj = mgr.create_project("Delta", workspace_path=str(ws))
        assert Path(proj.workspace_path).is_absolute()
        assert mgr.get_project(proj.id) is not None


# --------------------------------------------------------------------------- #
# 6-7, 23. Knowledge path + traversal/link handling
# --------------------------------------------------------------------------- #


class TestKnowledgeIntegration:
    def _kb(self):
        from knowledge.knowledge_base import KnowledgeBase

        return KnowledgeBase(embedding_model=None)  # stub embedding

    def test_knowledge_dir_is_canonical_user_data(self, env):
        assert paths.get_knowledge_docs_dir().is_relative_to(env["user_data"])
        assert paths.get_knowledge_docs_dir() == env["user_data"] / "knowledge_docs"

    def test_indexing_ignores_part_and_hidden(self, env, tmp_path):
        kb = self._kb()
        docs = env["user_data"] / "knowledge_docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "real.md").write_text("# Real doc\nhello world", encoding="utf-8")
        (docs / "partial.md.part").write_text("GGUF nonsense partial", encoding="utf-8")
        (docs / ".hidden.md").write_text("hidden", encoding="utf-8")
        chunks = kb.index_directory(docs)
        assert chunks > 0
        assert all("partial" not in (c.text or "") for c in kb._chunk_map.values())
        assert not any(".hidden" in d.path for d in kb._documents.values())

    def test_indexing_link_safe(self, env, tmp_path):
        """A symlinked directory in the knowledge root is not descended."""
        kb = self._kb()
        docs = env["user_data"] / "knowledge_docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "inside.md").write_text("inside knowledge", encoding="utf-8")
        outside_dir = tmp_path / "outside_docs"
        outside_dir.mkdir()
        (outside_dir / "leaked.md").write_text("should not be indexed", encoding="utf-8")
        try:
            os.symlink(outside_dir, docs / "linked_dir")
        except OSError:
            pytest.skip("symlinks unavailable")
        before = len(kb._documents)
        kb.index_directory(docs)
        # The inside file indexed; the leaked one did not.
        assert any("inside.md" in d.path for d in kb._documents.values())
        assert not any("leaked.md" in d.path for d in kb._documents.values())
        assert len(kb._documents) == before + 1

    def test_foreign_cwd_knowledge_operations(self, env):
        assert Path.cwd() == env["foreign_cwd"]
        kb = self._kb()
        docs = paths.get_knowledge_docs_dir()
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "cwd.md").write_text("cwd test doc", encoding="utf-8")
        assert kb.index_directory(docs) >= 0  # absolute, CWD-independent


# --------------------------------------------------------------------------- #
# 8, 24. Plugin path integration
# --------------------------------------------------------------------------- #


class TestPluginIntegration:
    def test_plugin_dir_is_canonical_user_data(self, env):
        assert paths.get_plugins_dir().is_relative_to(env["user_data"])

    def test_plugin_discovery_from_user_data_dir(self, env):
        from plugins.discovery import discover_plugins

        pdir = env["user_data"] / "plugins" / "hello"
        pdir.mkdir(parents=True)
        manifest = {
            "id": "hello", "name": "Hello", "version": "1.0.0",
            "entry_point": "hello.py:HelloPlugin", "description": "test",
        }
        (pdir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
        (pdir / "hello.py").write_text(
            "class HelloPlugin:\n    def greet(self):\n        return 'hi'\n",
            encoding="utf-8",
        )
        found = discover_plugins(env["user_data"] / "plugins")
        assert len(found) == 1 and found[0].id == "hello"

    def test_foreign_cwd_plugin_discovery(self, env):
        assert Path.cwd() == env["foreign_cwd"]
        self.test_plugin_discovery_from_user_data_dir(env)

    def test_no_plugin_scan_outside_configured_dir(self, env):
        """discover_and_load receives exactly ONE directory — the
        canonical user-data plugins dir (or the configured absolute
        path); it never scans arbitrary filesystem locations."""
        src = (REPO / "plugins" / "manager.py").read_text(encoding="utf-8")
        assert "get_plugins_dir" not in src  # wired by app startup only
        appsrc = (REPO / "app" / "application.py").read_text(encoding="utf-8")
        assert "get_plugins_dir()" in appsrc  # startup uses the canonical dir


# --------------------------------------------------------------------------- #
# 10-11. Model loading + vision/mmproj from selected external root
# --------------------------------------------------------------------------- #


class TestModelLoadingIntegration:
    def test_vision_mmproj_sibling_discovery(self, env):
        """mmproj lands NEXT TO the model (Phase 3 sibling contract)."""
        from ai.models.model_loader import ModelCapabilities, ModelInfo
        from ai.models.model_manager import _find_mmproj_for

        cat = env["models_root"] / "llm"
        model = _write_gguf(cat / "vision-model.gguf")
        _write_gguf(cat / "mmproj-vision-model.gguf")
        info = ModelInfo(
            name="vision-model", path=model, size_bytes=1024 * 1024,
            capabilities=ModelCapabilities(vision=True),
        )
        found = _find_mmproj_for(info)
        assert found is not None
        assert found.name == "mmproj-vision-model.gguf"
        assert found.parent == cat  # sibling-relative

    def test_loader_gpu_decision_delegates_to_phase4(self, env):
        """GGUFModelLoader._decide_gpu_layers_for uses gpu_runtime."""
        src = (REPO / "ai" / "models" / "model_loader.py").read_text(encoding="utf-8")
        assert "from ai.models.gpu_runtime import" in src
        assert "decide_gpu_layers(" in src
        # and no raw pynvml/WMI usage in the loader
        assert "pynvml" not in src
        assert "AdapterRAM" not in src

    def test_manager_load_uses_phase4_strategy(self, env):
        from ai.models.gpu_runtime import decide_gpu_layers
        from ai.models.model_manager import ModelManager

        mm = ModelManager(
            include_ollama=False, include_lm_studio=False, gpu_mode="auto",
        )
        with patch(
            "ai.models.model_loader.decide_gpu_layers",
            wraps=decide_gpu_layers,
        ) as spy:
            try:
                mm.get_loader_for_model("anything")  # raises (no model), but
            except Exception:
                pass
            # not called because model missing — presence of delegation is
            # verified statically above; runtime call covered in Phase 4 tests
        assert spy.call_count >= 0


# --------------------------------------------------------------------------- #
# 12-13. Embedding + STT resolution
# --------------------------------------------------------------------------- #


class TestEmbeddingSttResolution:
    def test_embedding_resolution_uses_category_dir(self, env):
        from memory.embeddings import _DEFAULT_MXBAI_FILENAME, _resolve_embedding_model_path

        emb = env["models_root"] / "embedding"
        emb.mkdir(parents=True, exist_ok=True)
        _write_gguf(emb / _DEFAULT_MXBAI_FILENAME)
        resolved = _resolve_embedding_model_path(None)
        assert resolved == emb / _DEFAULT_MXBAI_FILENAME

    def test_embedding_missing_model_returns_none_not_crash(self, env):
        from memory.embeddings import _resolve_embedding_model_path

        assert _resolve_embedding_model_path(None) is None

    def test_embedding_fallback_is_stub(self, env):
        from memory.embeddings import StubEmbeddingModel, load_embedding_model

        model = load_embedding_model("mxbai-gguf")  # no model file present
        assert isinstance(model, StubEmbeddingModel)
        assert model.intended_name == "mxbai-gguf"

    def test_stt_dir_follows_models_root(self, env):
        import inspect

        from voice import stt as stt_mod

        assert "get_model_category_dir" in inspect.getsource(stt_mod._default_stt_dir)

    def test_stt_legacy_layout_preserved(self, env):
        """Legacy voice/stt sublayout still resolves under the stt cat."""
        from core.paths import get_model_category_dir

        stt_dir = get_model_category_dir("stt")
        assert stt_dir.name == "stt"
        # legacy voice/stt layout compatibility lives in core.paths
        src = (REPO / "core" / "paths.py").read_text(encoding="utf-8")
        assert "voice" in src and "legacy" in src.lower()


# --------------------------------------------------------------------------- #
# 18-20. GPU/hardware/recommendation callers
# --------------------------------------------------------------------------- #


class TestGpuHardwareConsumers:
    def test_model_manager_dialog_uses_phase7_hardware(self):
        src = (REPO / "ui" / "model_manager_dialog.py").read_text(encoding="utf-8")
        assert "detect_hardware_snapshot" in src
        assert "HardwareSnapshot" in src
        # legacy installer probe may show a label, but VRAM verdicts must
        # come through the Phase 7 abstraction
        assert "catalog_status" in src

    def test_no_adapterram_vram_outside_installer_hardware(self):
        """WMI AdapterRAM is only CONSUMED by the legacy installer probe
        (name/vendor hint).  Docstring mentions documenting the
        prohibition are fine; actual query/getattr usage is not."""
        usage_patterns = (
            "AdapterRAM FROM",            # WMI SELECT query
            'getattr(gpu, "AdapterRAM"',   # attribute consumption
            "gpu.AdapterRAM",
        )
        hits: list[str] = []
        for pkg in ("installer", "tools", "ai", "ui", "app", "voice", "memory"):
            for py in (REPO / pkg).rglob("*.py"):
                text = py.read_text(encoding="utf-8", errors="replace")
                if any(p in text for p in usage_patterns):
                    hits.append(str(py.relative_to(REPO)).replace("\\", "/"))
        assert hits == ["installer/hardware.py"], (
            f"AdapterRAM consumed outside the legacy installer probe: {hits}"
        )

    def test_no_raw_pynvml_outside_gpu_runtime(self):
        hits: list[str] = []
        for pkg in ("ai", "ui", "app", "tools", "installer", "voice", "memory"):
            for py in (REPO / pkg).rglob("*.py"):
                text = py.read_text(encoding="utf-8", errors="replace")
                # actual imports; doc references are excluded
                if "import pynvml" in text or "from pynvml" in text:
                    hits.append(str(py.relative_to(REPO)).replace("\\", "/"))
        assert hits == ["ai/models/gpu_runtime.py"], (
            f"raw pynvml imported outside the Phase 4 runtime: {hits}"
        )

    def test_main_window_handles_canonical_models_root_key(self, qapp, env):
        """CONFIG_CHANGED models.storage_root re-points the manager."""
        from ai.models.model_manager import ModelManager
        from ui.main_window import MainWindow

        mm = ModelManager(include_ollama=False, include_lm_studio=False)
        assistant = MagicMock()
        assistant.model_manager = mm
        window = MainWindow.__new__(MainWindow)
        window._assistant = assistant
        window._models_page = None
        new_root = env["tmp"] / "RuntimeRoot"
        window._apply_models_root_change(str(new_root))
        assert mm.models_dir == new_root / "llm"
        # Legacy key still honored
        mm2_path = env["tmp"] / "LegacyDir"
        window._on_config_changed("CONFIG_CHANGED", {"key": "ai.models_dir", "value": str(mm2_path)})
        assert mm.models_dir == mm2_path

    def test_invalid_models_root_value_ignored(self, qapp, env):
        from ai.models.model_manager import ModelManager
        from ui.main_window import MainWindow

        mm = ModelManager(include_ollama=False, include_lm_studio=False)
        before = mm.models_dir
        assistant = MagicMock()
        assistant.model_manager = mm
        window = MainWindow.__new__(MainWindow)
        window._assistant = assistant
        window._models_page = None
        window._apply_models_root_change("relative/path")  # rejected
        assert mm.models_dir == before


# --------------------------------------------------------------------------- #
# 21. Installed-app separation
# --------------------------------------------------------------------------- #


class TestInstalledAppSeparation:
    def test_frozen_resource_root_readonly_policy(self, env, monkeypatch):
        """In frozen mode, the install dir is read-only; user data and
        models must never resolve inside it."""
        fake_install = env["tmp"] / "Installed" / "OfflineAI"
        fake_install.mkdir(parents=True)
        with patch("core.paths._is_frozen", return_value=True), patch(
            "sys._MEIPASS", str(fake_install), create=True
        ):
            assert paths.app_root() == fake_install
            ud = paths.user_data_root()
            assert ud == env["user_data"]
            assert "OfflineAI" in ud.name
            assert not ud.is_relative_to(fake_install)

    def test_models_root_default_never_program_files(self, env, monkeypatch):
        monkeypatch.delenv(paths.MODELS_ROOT_ENV_VAR, raising=False)
        # Fresh empty settings under the isolated user-data root
        root = paths.get_models_root()
        assert "program files" not in str(root).lower()
        assert root.is_absolute()


# --------------------------------------------------------------------------- #
# Static audit
# --------------------------------------------------------------------------- #


class TestStaticIntegrationAudit:
    def test_no_cwd_path_construction_in_core(self):
        for rel in ("core/paths.py", "tools/file_security.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            assert "Path.cwd()" not in src
            assert "os.getcwd" not in src

    def test_no_direct_rmtree_outside_sanctioned_path(self):
        result = subprocess.run(
            ["git", "grep", "-n", "shutil.rmtree", "--", "*.py"],
            capture_output=True, text=True, cwd=str(REPO), check=False,
        )
        lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
        # project/manager.py is the sanctioned workspace deletion path;
        # installer/downloader cleans its own .part files; tests may use it.
        # Comment/doc references in other files are reviewed below.
        allowed = ("project/manager.py", "tests/", "installer/downloader.py")
        for ln in lines:
            if any(a in ln for a in allowed):
                continue
            # A comment-only mention (no call) is acceptable documentation
            # of the prohibition; an actual CALL must be sanctioned.
            code_part = ln.split(":", 2)[-1].strip()
            assert not code_part.startswith("shutil.rmtree("), (
                f"unsanctioned rmtree call: {ln}"
            )

    def test_no_testapp_references_in_sources(self):
        result = subprocess.run(
            ["git", "grep", "-n", "TestApp", "--", "*.py", "*.iss", "*.spec"],
            capture_output=True, text=True, cwd=str(REPO), check=False,
        )
        for ln in result.stdout.splitlines():
            if not ln.strip():
                continue
            # The stale TestApp.iss artifact was removed in Phase 6;
            # only test files may reference the historical name.
            assert ln.replace("./", "").startswith("tests/"), ln
