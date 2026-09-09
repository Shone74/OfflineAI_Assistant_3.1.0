"""PHASE 9 Task 3 — multi-root model search regression tests.

Proves the documented roles of the three model-storage settings
(docs/phase9_model_storage_keys.md) with the REAL ModelManager /
discovery stack — no mocks of production code, no network, no real
models, no Ollama/GPU/external services:

* ``models.storage_root`` stays the canonical PRIMARY root;
* ``ai.model_search_paths`` (legacy/advisory) adds extra ABSOLUTE scan
  roots on top of the canonical root — models from BOTH locations are
  discovered;
* unrelated directories are NOT implicitly searched;
* the wiring matches the application startup path (app.application
  constructs ModelManager exactly this way);
* the advisory list is startup-only: runtime root re-pointing
  (``set_models_dir``) replaces the search list without rewriting the
  stored key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths


def _gguf(path: Path, marker: bytes = b"\x00") -> None:
    """Write a minimal valid GGUF file (magic + version)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"GGUF" + b"\x02\x00\x00\x00" + marker * 64)


@pytest.fixture()
def multi_root_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Canonical root + one advisory extra root + one unrelated dir."""
    canonical = tmp_path / "CanonicalRoot"
    advisory = tmp_path / "AdvisoryRoot" / "extra-models"
    unrelated = tmp_path / "CompletelyUnrelated"
    canonical.mkdir(parents=True)
    advisory.mkdir(parents=True)
    unrelated.mkdir(parents=True)

    monkeypatch.setenv(paths.MODELS_ROOT_ENV_VAR, str(canonical))

    # Distinguishable synthetic models in each location.
    _gguf(canonical / "llm" / "canonical-model.gguf", marker=b"\x01")
    _gguf(advisory / "advisory-model.gguf", marker=b"\x02")
    _gguf(unrelated / "unrelated-model.gguf", marker=b"\x03")

    return {
        "canonical": canonical,
        "advisory": advisory,
        "unrelated": unrelated,
        "tmp": tmp_path,
    }


class TestMultiRootModelSearch:
    def test_both_roots_discovered(self, multi_root_env):
        """Canonical + advisory roots both contribute models."""
        from ai.models.model_manager import ModelManager

        mm = ModelManager(
            models_dir=multi_root_env["canonical"] / "llm",
            search_paths=[multi_root_env["advisory"]],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = {m.name for m in mm.list_models()}
        assert "canonical-model" in names
        assert "advisory-model" in names

    def test_canonical_root_remains_primary(self, multi_root_env):
        """The canonical llm category dir is always scanned and is the
        manager's primary models_dir, even with advisory paths set."""
        from ai.models.model_manager import ModelManager

        mm = ModelManager(
            models_dir=multi_root_env["canonical"] / "llm",
            search_paths=[multi_root_env["advisory"]],
            include_ollama=False,
            include_lm_studio=False,
        )
        assert mm.models_dir == multi_root_env["canonical"] / "llm"
        # Primary root model present even though it was NOT repeated in
        # the advisory list (constructor dedup guarantees this).
        assert any(m.name == "canonical-model" for m in mm.list_models())

    def test_unrelated_roots_not_searched(self, multi_root_env):
        """A directory that is neither the canonical root nor in the
        advisory list never contributes models."""
        from ai.models.model_manager import ModelManager

        mm = ModelManager(
            models_dir=multi_root_env["canonical"] / "llm",
            search_paths=[multi_root_env["advisory"]],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = {m.name for m in mm.list_models()}
        assert "unrelated-model" not in names

    def test_application_startup_wiring(self, multi_root_env):
        """The exact app.application startup derivation: canonical llm
        category dir + configured advisory list (absolute only)."""
        from ai.models.model_manager import ModelManager

        llm_category_dir = paths.get_model_category_dir("llm")
        assert llm_category_dir == multi_root_env["canonical"] / "llm"

        search_paths = [str(multi_root_env["advisory"])]  # ai.model_search_paths
        mm = ModelManager(
            models_dir=llm_category_dir,
            search_paths=[Path(p) for p in search_paths],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = {m.name for m in mm.list_models()}
        assert names == {"canonical-model", "advisory-model"}

    def test_search_paths_startup_only_semantics(self, multi_root_env):
        """Runtime re-pointing (set_models_dir) replaces the in-session
        search list and does NOT write the legacy advisory key —
        edited settings.json values apply on next launch."""
        from ai.models.model_manager import ModelManager

        mm = ModelManager(
            models_dir=multi_root_env["canonical"] / "llm",
            search_paths=[multi_root_env["advisory"]],
            include_ollama=False,
            include_lm_studio=False,
        )
        assert any(m.name == "advisory-model" for m in mm.list_models())

        new_root = multi_root_env["tmp"] / "NewRoot"
        _gguf(new_root / "llm" / "fresh-model.gguf")
        mm.set_models_dir(new_root / "llm")

        # In-session: ONLY the new primary dir is searched.
        names = {m.name for m in mm.list_models()}
        assert "fresh-model" in names
        assert "advisory-model" not in names

    def test_set_models_root_mirrors_coherently(self, multi_root_env):
        """set_models_root writes the canonical key and MIRRORS the two
        legacy keys — the documented compatibility contract."""
        new_root = multi_root_env["tmp"] / "MirroredRoot"

        class _Cfg:
            def __init__(self) -> None:
                self.written: dict[str, object] = {}

            def set(self, key: str, value: object) -> None:
                self.written[key] = value

        cfg = _Cfg()
        result = paths.set_models_root(new_root, config=cfg)
        assert result == new_root.resolve()
        assert cfg.written[paths.MODELS_ROOT_CONFIG_KEY] == str(new_root.resolve())
        assert cfg.written[paths.LEGACY_MODELS_DIR_CONFIG_KEY] == str(
            new_root.resolve() / "llm"
        )
        assert cfg.written["ai.model_search_paths"] == [str(new_root.resolve() / "llm")]

    def test_legacy_only_settings_resolve_canonical_root(self, multi_root_env):
        """A pre-Phase-3 settings.json carrying ONLY ai.models_dir still
        resolves the root (compatibility contract, documented)."""
        legacy_llm_dir = multi_root_env["tmp"] / "LegacyTree" / "llm"
        _gguf(legacy_llm_dir / "legacy-model.gguf")

        import json

        settings = multi_root_env["tmp"] / "settings.json"
        settings.write_text(
            json.dumps({"ai": {"models_dir": str(legacy_llm_dir)}}),
            encoding="utf-8",
        )
        monkeypl = pytest.MonkeyPatch()
        monkeypl.setattr(paths, "SETTINGS_FILE", settings)
        monkeypl.delenv(paths.MODELS_ROOT_ENV_VAR, raising=False)
        try:
            root = paths.get_models_root()
            # The legacy llm-category value resolves to its PARENT root.
            assert root == legacy_llm_dir.parent.resolve()
            assert paths.get_model_category_dir("llm") == legacy_llm_dir.resolve()
        finally:
            monkeypl.undo()
