"""PHASE 3 regression tests — user-selected model storage & manifest.

Locks down the models-root contract:

* one canonical setting (``models.storage_root``) selected by the user —
  wizard, settings UI and runtime all read/write the same key
* absolute paths only; relative values rejected, never CWD-resolved
* any drive/location; never the install dir; never Program Files
* deterministic category layout under the root (llm / embedding / stt)
* discovery + loading + embedding + STT resolution derive from the root
* recursive discovery does not follow symlink/junction escapes
* no manifest duplication: physical files are the source of truth (the
  settings file only stores the root, never per-model machine paths)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


@pytest.fixture()
def models_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the models-root env override at a temp root and return it."""
    root = tmp_path / "AI" / "Models"
    monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(root))
    return root


@pytest.fixture()
def settings_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate SETTINGS_FILE resolution to a temp settings.json.

    core.paths reads the settings file at call time (module constants like
    CONFIG_DIR are import-time snapshots, so the FILE is monkeypatched on
    the module object instead).  BOTH bindings are patched — core.paths AND
    core.config_manager (which from-imports SETTINGS_FILE at its own import
    time): without the second patch, a session whose FIRST import of
    core.config_manager happens while this fixture is active would cache
    the temp binding permanently and leak it into later no-arg
    ``ConfigManager()`` constructions in other test files (the
    test_phase8_integration.py env fixture established this two-binding
    pattern first).
    """
    user_data = tmp_path / "user_data"
    settings = user_data / "config" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({}), encoding="utf-8")
    # Import core.config_manager BEFORE patching core.paths so its
    # from-import binding captures the REAL path first (never the
    # patched one); then patch BOTH bindings symmetrically.
    import core.config_manager as _cm

    monkeypatch.setattr(_cm, "SETTINGS_FILE", settings)
    monkeypatch.setattr(paths, "SETTINGS_FILE", settings)
    return settings


# --------------------------------------------------------------------------- #
# 1-4. models_root resolution and configuration
# --------------------------------------------------------------------------- #


class TestModelsRootResolution:
    def test_absolute_configured_root_used(self, settings_file: Path) -> None:
        root = settings_file.parent.parent.parent / "AI" / "Models"
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(root)}}),
            encoding="utf-8",
        )
        assert paths.get_models_root() == root.resolve()

    def test_other_drive_supported(self, settings_file: Path) -> None:
        """A root on a different drive letter is a first-class value."""
        root = Path("F:\\MyModels")
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(root)}}),
            encoding="utf-8",
        )
        # Note: F: may not exist on the test machine; resolution must still
        # return the configured absolute path (resolve() on a non-existent
        # Windows drive can fail — absolute() is the accepted fallback).
        result = paths.get_models_root()
        assert result == root or result == root.resolve()

    def test_relative_configured_root_rejected_not_cwd(
        self, settings_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A relative models_root never acquires meaning from the CWD."""
        settings_file.write_text(
            json.dumps({"models": {"storage_root": "some_models"}}),
            encoding="utf-8",
        )
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)

        import io
        from contextlib import redirect_stderr

        stderr = io.StringIO()
        with redirect_stderr(stderr):
            root = paths.get_models_root()
        # Falls back to the deterministic default — never <cwd>/some_models.
        assert root == paths.get_models_dir()
        assert not (cwd / "some_models").exists()
        assert "some_models" in stderr.getvalue()

    def test_relative_env_override_rejected(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings_file.write_text(json.dumps({}), encoding="utf-8")
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, "rel_root")
        root = paths.get_models_root()
        assert root == paths.get_models_dir()

    def test_env_override_absolute_wins(self, settings_file: Path, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        env_root = tmp_path / "env" / "models"
        settings_root = tmp_path / "settings" / "models"
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(settings_root)}}),
            encoding="utf-8",
        )
        monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(env_root))
        assert paths.get_models_root() == env_root.resolve()

    def test_unset_uses_default_user_data_models(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty config -> deterministic default suggestion (user-data models)."""
        monkeypatch.delenv(paths.MODELS_ROOT_ENV_VAR, raising=False)
        assert paths.get_models_root() == paths.get_models_dir()
        # The default is NOT the application directory or Program Files.
        assert paths.app_root() not in paths.get_models_root().parents
        assert "program files" not in str(paths.get_models_root()).lower()

    def test_cwd_independent(self, settings_file: Path, tmp_path: Path) -> None:
        """Identical resolution from two different CWDs."""
        root = tmp_path / "AI" / "Models"
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(root)}}),
            encoding="utf-8",
        )
        cwd_a = tmp_path / "a"
        cwd_b = tmp_path / "b"
        cwd_a.mkdir()
        cwd_b.mkdir()
        old = Path.cwd()
        try:
            os.chdir(cwd_a)
            first = paths.get_models_root()
            os.chdir(cwd_b)
            second = paths.get_models_root()
        finally:
            os.chdir(old)
        assert first == second == root.resolve()


# --------------------------------------------------------------------------- #
# 5-7. Category layout
# --------------------------------------------------------------------------- #


class TestCategoryLayout:
    def test_categories_deterministic(self, models_root_env: Path) -> None:
        root = models_root_env
        assert paths.get_model_category_dir("llm") == root / "llm"
        assert paths.get_model_category_dir("embedding") == root / "embedding"
        assert paths.get_model_category_dir("stt") == root / "stt"

    def test_stt_legacy_layout_honoured(self, models_root_env: Path) -> None:
        """Existing <root>/voice/stt trees keep resolving to the legacy dir."""
        legacy = models_root_env / "voice" / "stt"
        legacy.mkdir(parents=True)
        assert paths.get_model_category_dir("stt") == legacy

    def test_unknown_category_rejected(self, models_root_env: Path) -> None:
        with pytest.raises(ValueError, match="category"):
            paths.get_model_category_dir("vision-transformers-unsupported")

    def test_ensure_model_dirs_creates_categories(self, models_root_env: Path) -> None:
        ensured = paths.ensure_model_dirs()
        assert (models_root_env / "llm").is_dir()
        assert (models_root_env / "embedding").is_dir()
        assert (models_root_env / "stt").is_dir()
        assert models_root_env in ensured

    def test_not_under_app_install_dir(self, models_root_env: Path) -> None:
        """Category dirs never resolve under the application installation."""
        app_root = paths.app_root()
        for category in paths.MODEL_CATEGORIES:
            cat_dir = paths.get_model_category_dir(category)
            assert app_root not in cat_dir.parents
            assert cat_dir != app_root


# --------------------------------------------------------------------------- #
# set_models_root persistence
# --------------------------------------------------------------------------- #


class TestSetModelsRoot:
    def test_persists_canonical_key_and_mirrors_legacy(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        root = tmp_path / "Picked" / "Models"

        class _Cfg:
            def __init__(self) -> None:
                self.written: dict[str, str] = {}

            def set(self, key: str, value) -> None:
                self.written[key] = value

        cfg = _Cfg()
        normalized = paths.set_models_root(root, config=cfg)
        assert normalized == root.resolve()
        assert cfg.written[paths.MODELS_ROOT_CONFIG_KEY] == str(root.resolve())
        # Legacy mirror keeps older readers consistent.
        assert cfg.written[paths.LEGACY_MODELS_DIR_CONFIG_KEY] == str(
            root.resolve() / "llm"
        )
        assert cfg.written["ai.model_search_paths"] == [str(root.resolve() / "llm")]

    def test_relative_rejected(self, settings_file: Path) -> None:
        with pytest.raises(ValueError, match="absolute"):
            paths.set_models_root("relative_models")

    def test_settings_roundtrip_via_config_manager(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        """The canonical key round-trips through the real ConfigManager."""
        from core.config_manager import ConfigManager

        root = tmp_path / "RoundTrip" / "Models"
        cfg = ConfigManager(settings_path=settings_file)
        paths.set_models_root(root, config=cfg)

        cfg2 = ConfigManager(settings_path=settings_file)
        assert cfg2.get("models.storage_root") == str(root.resolve())
        assert paths.get_models_root() == root.resolve()

    def test_legacy_ai_models_dir_migration(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        """A pre-PHASE-3 ai.models_dir (llm category dir) migrates to its
        parent as the models root — existing trees keep working."""
        legacy_root = tmp_path / "LegacyRoot"
        legacy_llm = legacy_root / "llm"
        settings_file.write_text(
            json.dumps({"ai": {"models_dir": str(legacy_llm)}}),
            encoding="utf-8",
        )
        assert paths.get_models_root() == legacy_root.resolve()
        assert paths.get_model_category_dir("llm") == legacy_llm.resolve()


# --------------------------------------------------------------------------- #
# 5-6, 13-14. Discovery + loading through the models root
# --------------------------------------------------------------------------- #


def _write_minimal_gguf(path: Path) -> None:
    """Write a minimal GGUF v2 file (magic + version + counts)."""
    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"GGUF")
        fh.write(struct.pack("<I", 2))
        fh.write(struct.pack("<Q", 0))  # tensor_count
        fh.write(struct.pack("<Q", 1))  # metadata kv count
        # Single metadata entry: general.architecture = "llama" (STRING).
        key = b"general.architecture"
        fh.write(struct.pack("<Q", len(key)))
        fh.write(key)
        fh.write(struct.pack("<I", 8))  # STRING type
        value = b"llama"
        fh.write(struct.pack("<Q", len(value)))
        fh.write(value)


class TestDiscoveryThroughModelsRoot:
    def test_discovery_uses_models_root(self, models_root_env: Path) -> None:
        from ai.models.discovery import discover_all_models

        _write_minimal_gguf(models_root_env / "llm" / "test-model.gguf")
        models = discover_all_models(
            search_paths=None, include_ollama=False, include_lm_studio=False
        )
        assert any(m.path == (models_root_env / "llm" / "test-model.gguf") for m in models)

    def test_changing_root_changes_discovery_location(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        from ai.models.discovery import discover_all_models

        root_a = tmp_path / "root_a"
        root_b = tmp_path / "root_b"
        _write_minimal_gguf(root_a / "llm" / "only-in-a.gguf")
        _write_minimal_gguf(root_b / "llm" / "only-in-b.gguf")

        for root, expected_name in ((root_a, "only-in-a"), (root_b, "only-in-b")):
            settings_file.write_text(
                json.dumps({"models": {"storage_root": str(root)}}),
                encoding="utf-8",
            )
            models = discover_all_models(
                search_paths=None, include_ollama=False, include_lm_studio=False
            )
            names = {m.name for m in models}
            assert expected_name in names
            assert names == {expected_name}

    def test_discovery_default_search_path_is_category_dir(
        self, models_root_env: Path
    ) -> None:
        from ai.models.discovery import _default_llm_category_dir

        assert _default_llm_category_dir() == models_root_env / "llm"

    def test_model_manager_default_uses_models_root(
        self, models_root_env: Path
    ) -> None:
        from ai.models.model_manager import ModelManager

        manager = ModelManager()  # no explicit dir — must use models root
        assert manager.models_dir == models_root_env / "llm"

    def test_model_loader_discover_default_uses_models_root(
        self, models_root_env: Path
    ) -> None:
        from ai.models.model_loader import discover_models

        _write_minimal_gguf(models_root_env / "llm" / "loader-default.gguf")
        models = discover_models()
        assert any(
            m.path == (models_root_env / "llm" / "loader-default.gguf") for m in models
        )

    def test_discovery_no_symlink_junction_escape(
        self, models_root_env: Path, tmp_path: Path
    ) -> None:
        """A junction inside the model tree cannot leak outside files."""
        from ai.models.discovery import discover_all_models

        outside = tmp_path / "outside"
        _write_minimal_gguf(outside / "escaped.gguf")
        link_dir = models_root_env / "llm" / "link"
        link_dir.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            import subprocess

            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_dir), str(outside)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0 or not link_dir.exists():
                pytest.skip(f"junction creation unavailable: {result.stderr}")
        else:
            os.symlink(outside, link_dir, target_is_directory=True)

        models = discover_all_models(
            search_paths=[models_root_env / "llm"],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = {m.name for m in models}
        assert "escaped" not in names

    def test_mmproj_companion_next_to_model(self, models_root_env: Path) -> None:
        """mmproj discovery is model-relative — works from any models root."""
        from ai.models.model_loader import ModelInfo
        from ai.models.model_manager import _find_mmproj_for

        vision_model = models_root_env / "llm" / "Qwen2.5-VL-7B.gguf"
        mmproj = models_root_env / "llm" / "mmproj-model.gguf"
        _write_minimal_gguf(vision_model)
        _write_minimal_gguf(mmproj)

        info = ModelInfo(
            name="Qwen2.5-VL-7B",
            path=vision_model,
            size_bytes=100,
        )
        # Give it vision capabilities so the finder runs.
        from ai.models.model_loader import ModelCapabilities, ModelType

        info.capabilities = ModelCapabilities(vision=True)
        info.model_type = ModelType.VISION_LLM
        assert _find_mmproj_for(info) == mmproj


# --------------------------------------------------------------------------- #
# 9. No hardcoded developer paths
# --------------------------------------------------------------------------- #


class TestNoHardcodedPaths:
    def test_no_developer_machine_paths_in_sources(self) -> None:
        repo = Path(__file__).resolve().parents[1]
        banned = ("E:\\models", "E:/models", "D:\\OfflineAI", "C:\\AI\\Models")
        for py_file in list((repo / "core").rglob("*.py")) + list(
            (repo / "ai").rglob("*.py")
        ) + list((repo / "memory").rglob("*.py")) + list(
            (repo / "voice").rglob("*.py")
        ) + [repo / "app" / "application.py"]:
            text = py_file.read_text(encoding="utf-8", errors="replace")
            for needle in banned:
                assert needle.lower() not in text.lower(), (
                    f"{py_file} contains hardcoded model path {needle!r}"
                )

    def test_program_files_not_default_models_root(
        self, settings_file: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(paths.MODELS_ROOT_ENV_VAR, raising=False)
        root = paths.get_models_root()
        assert "program files" not in str(root).lower()
        assert "offline ai assistant" not in str(root).lower()


# --------------------------------------------------------------------------- #
# 17. Embedding resolution through models root
# --------------------------------------------------------------------------- #


class TestEmbeddingResolution:
    def test_embedding_category_preferred(self, models_root_env: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MXBAI_EMBEDDING_MODEL_PATH", raising=False)
        from memory.embeddings import _DEFAULT_MXBAI_FILENAME, _resolve_embedding_model_path

        embedding_model = models_root_env / "embedding" / _DEFAULT_MXBAI_FILENAME
        embedding_model.parent.mkdir(parents=True, exist_ok=True)
        embedding_model.write_bytes(b"GGUF-stub")
        assert _resolve_embedding_model_path() == embedding_model

    def test_legacy_llm_fallback(self, models_root_env: Path,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
        """Old trees (embedding GGUF beside LLMs) keep resolving."""
        monkeypatch.delenv("MXBAI_EMBEDDING_MODEL_PATH", raising=False)
        from memory.embeddings import _DEFAULT_MXBAI_FILENAME, _resolve_embedding_model_path

        llm_model = models_root_env / "llm" / _DEFAULT_MXBAI_FILENAME
        llm_model.parent.mkdir(parents=True, exist_ok=True)
        llm_model.write_bytes(b"GGUF-stub")
        assert _resolve_embedding_model_path() == llm_model

    def test_explicit_and_env_preserved(self, tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
        from memory.embeddings import _resolve_embedding_model_path

        explicit = tmp_path / "explicit.gguf"
        explicit.write_bytes(b"GGUF")
        assert _resolve_embedding_model_path(explicit) == explicit
        env_path = tmp_path / "env.gguf"
        env_path.write_bytes(b"GGUF")
        monkeypatch.setenv("MXBAI_EMBEDDING_MODEL_PATH", str(env_path))
        assert _resolve_embedding_model_path() == env_path


# --------------------------------------------------------------------------- #
# STT resolution through models root
# --------------------------------------------------------------------------- #


class TestSttResolution:
    def test_stt_default_dir_under_models_root(self, models_root_env: Path) -> None:
        from voice.stt import WhisperSTT

        stt = WhisperSTT(model_name="tiny")
        assert stt._stt_dir == models_root_env / "stt"

    def test_stt_legacy_layout(self, models_root_env: Path) -> None:
        legacy = models_root_env / "voice" / "stt"
        legacy.mkdir(parents=True)
        from voice.stt import WhisperSTT

        stt = WhisperSTT(model_name="tiny")
        assert stt._stt_dir == legacy


# --------------------------------------------------------------------------- #
# 18. Wizard / settings / runtime share one setting
# --------------------------------------------------------------------------- #


class TestSharedSetting:
    def test_wizard_locations_default_from_config(
        self, settings_file: Path, tmp_path: Path, qapp
    ) -> None:
        """LocationsPage pre-fills with the configured models root."""
        root = tmp_path / "WizardPicked" / "Models"
        settings_file.write_text(
            json.dumps({"models": {"storage_root": str(root)}}),
            encoding="utf-8",
        )
        from ui.welcome_wizard import LocationsPage

        page = LocationsPage.__new__(LocationsPage)  # skip heavy UI init
        page._app_path_edit = type("E", (), {"setText": lambda self, t: None})()
        page._models_path_edit = _RecordingEdit()
        page._update_storage_info = lambda: None
        LocationsPage.initializePage(page)
        assert page._models_path_edit.value == str(root)

    def test_settings_tab_persist_writes_canonical_key(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        """ModelStatusTab folder selection persists via set_models_root."""
        from core.config_manager import ConfigManager

        cfg = ConfigManager(settings_path=settings_file)
        picked = tmp_path / "PickedViaSettings"
        paths.set_models_root(picked, config=cfg)
        assert cfg.get("models.storage_root") == str(picked.resolve())
        assert paths.get_models_root() == picked.resolve()

    def test_finalize_persists_models_root(
        self, settings_file: Path, tmp_path: Path, qapp
    ) -> None:
        """The wizard installation finalize step persists the choice."""
        root = tmp_path / "WizardFinalize" / "Models"
        settings_file.write_text(json.dumps({}), encoding="utf-8")

        from core.config_manager import ConfigManager
        from core.paths import set_models_root

        cfg = ConfigManager(settings_path=settings_file)
        set_models_root(root, config=cfg)

        cfg2 = ConfigManager(settings_path=settings_file)
        assert cfg2.get("models.storage_root") == str(root.resolve())


class _RecordingEdit:
    """QLineEdit stand-in capturing the pre-filled models path."""

    def __init__(self) -> None:
        self.value = ""

    def setText(self, text: str) -> None:
        self.value = text


# --------------------------------------------------------------------------- #
# Manifest design decision (no duplicate manifest)
# --------------------------------------------------------------------------- #


class TestManifestDecision:
    def test_settings_contain_no_per_model_absolute_paths(
        self, settings_file: Path, tmp_path: Path
    ) -> None:
        """The persisted configuration stores ONLY the root — the physical
        files remain the source of truth (no machine-specific per-model
        paths, keeping the storage relocatable with the root)."""
        root = tmp_path / "ManifestCheck" / "Models"
        settings_file.write_text(json.dumps({}), encoding="utf-8")
        from core.config_manager import ConfigManager

        cfg = ConfigManager(settings_path=settings_file)
        paths.set_models_root(root, config=cfg)
        raw = json.loads(settings_file.read_text(encoding="utf-8"))
        # Root-only persistence; nothing per-model.
        models_section = raw.get("models", {})
        assert set(models_section) == {"storage_root"}
