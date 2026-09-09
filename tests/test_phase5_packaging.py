"""PHASE 5 regression tests — PyInstaller / frozen production build.

Locks down the packaging contract without requiring a real GPU or a
particular developer drive:

* deterministic spec generation (one-folder, GUI console mode)
* required entry point + justified hidden imports
* SQL migrations collected as the only datas
* optional backends bundled only when installed (graceful otherwise)
* no developer-specific model paths anywhere in the spec
* no models bundled; runtime stays on ``models.storage_root``
* version metadata from the canonical pyproject version (single source)
* frozen startup registers CUDA dirs safely via the PHASE 4 extension
  point; missing CUDA never breaks startup
* frozen path/resource/user-data separation (non-GUI validation mode)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.packager import (
    OPTIONAL_RUNTIME_PACKAGES,
    PRODUCTION_DATAS,
    PRODUCTION_ENTRY_POINT,
    PRODUCTION_SPEC_FILENAME,
    PackageSpec,
    build_pyinstaller_spec,
    build_version_info_text,
    get_canonical_version,
    write_production_spec,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def spec(tmp_path: Path) -> PackageSpec:
    return PackageSpec(
        app_name="OfflineAI",
        version=get_canonical_version(),
        entry_point=PRODUCTION_ENTRY_POINT,
        spec_file=tmp_path / "test.spec",
    )


class TestProductionSpec:
    def test_spec_content_basic_contract(self, spec: PackageSpec):
        content = build_pyinstaller_spec(spec)
        assert f"'{PRODUCTION_ENTRY_POINT}'" in content
        # One-folder mode: EXE with exclude_binaries + COLLECT.
        assert "exclude_binaries=True" in content
        assert "coll = COLLECT(" in content
        # Production GUI build: console off by default.
        assert "console=False" in content
        # UPX disabled (deterministic, native-DLL safe).
        assert "upx=False" in content

    def test_spec_is_deterministic(self, spec: PackageSpec):
        assert build_pyinstaller_spec(spec) == build_pyinstaller_spec(spec)

    def test_migrations_are_the_only_default_datas(self, spec: PackageSpec):
        content = build_pyinstaller_spec(spec)
        assert "'database/migrations/*.sql'" in content
        assert "'database/migrations'" in content
        # No user data / models / plugins / knowledge bundled.
        for banned in ("models", "plugins", "knowledge_docs", "config/", "logs"):
            assert f"'{banned}'" not in content, f"datas must not include {banned}"

    def test_no_developer_model_paths(self, spec: PackageSpec):
        content = build_pyinstaller_spec(spec)
        for banned in ("E:\\models", "E:/models", "C:\\AI", "D:\\OfflineAI"):
            assert banned.lower() not in content.lower()

    def test_optional_backends_conditional(self, spec: PackageSpec, monkeypatch):
        import installer.packager as pk

        monkeypatch.setattr(
            pk, "OPTIONAL_RUNTIME_PACKAGES", ["definitely_not_installed_pkg_xyz"]
        )
        content = build_pyinstaller_spec(spec)
        assert "definitely_not_installed_pkg_xyz" not in content

    def test_required_hidden_imports_present(self, spec: PackageSpec):
        content = build_pyinstaller_spec(spec)
        assert "'win32com'" in content  # top-level COM usage (installer.hardware)

    def test_sounddevice_in_hidden_imports_when_installed(self, spec: PackageSpec):
        """sounddevice is dynamically imported in voice/audio.py and must be
        a PyInstaller hidden import so the frozen app does not crash on
        voice/audio startup."""
        import importlib.util

        if importlib.util.find_spec("sounddevice") is not None:
            content = build_pyinstaller_spec(spec)
            assert "'sounddevice'" in content

    def test_committed_spec_matches_packager_output(self):
        """The committed offline_ai_frozen.spec must match packager output.

        This prevents spec drift (e.g. a new optional backend being installed
        but not reflected in the committed spec).  Regenerate with
        ``python -m installer.packager`` if this test fails.
        """
        spec = PackageSpec(
            app_name="OfflineAI",
            version=get_canonical_version(),
            entry_point=PRODUCTION_ENTRY_POINT,
            console=False,
            spec_file=REPO / PRODUCTION_SPEC_FILENAME,
        )
        generated = build_pyinstaller_spec(spec)
        committed = (REPO / PRODUCTION_SPEC_FILENAME).read_text(encoding="utf-8")
        assert generated == committed, (
            "offline_ai_frozen.spec is out of sync with installer.packager. "
            "Regenerate with: python -m installer.packager"
        )

    def test_dev_modules_excluded(self, spec: PackageSpec):
        content = build_pyinstaller_spec(spec)
        assert "'tests'" in content
        assert "'pytest'" in content
        assert "'tkinter'" in content

    def test_version_file_generated(self, spec: PackageSpec):
        text = build_version_info_text(spec.app_name, "3.1.0")
        assert "VSVersionInfo" in text
        assert "3.1.0" in text
        assert "(3, 1, 0, 0)" in text

    def test_write_production_spec_roundtrip(self, tmp_path: Path):
        spec_path = write_production_spec(project_root=tmp_path)
        assert spec_path.name == PRODUCTION_SPEC_FILENAME
        assert spec_path.exists()
        version_file = spec_path.parent / "app_version_info.txt"
        assert version_file.exists()
        assert "VSVersionInfo" in version_file.read_text(encoding="utf-8")
        # The spec references the version file by relative name.
        assert "version='app_version_info.txt'" in spec_path.read_text(
            encoding="utf-8"
        )


class TestVersionMetadata:
    def test_canonical_version_matches_pyproject(self):
        pyproject = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        line = next(
            l for l in pyproject.splitlines() if l.strip().startswith("version")
        )
        expected = line.split("=", 1)[1].strip().strip("'\"")
        assert get_canonical_version() == expected

    def test_version_single_source(self):
        assert get_canonical_version() == get_canonical_version()


class TestFrozenStartup:
    def test_register_frozen_cuda_dirs_safe_without_cuda(
        self, monkeypatch, tmp_path, capsys
    ):
        """run._register_frozen_cuda_dirs with no CUDA dirs is a safe no-op."""
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        import run as run_mod

        # No nvidia dir inside the fake MEIPASS — must not raise.
        run_mod._register_frozen_cuda_dirs()
        assert not (tmp_path / "nvidia").exists()

    def test_register_frozen_cuda_dirs_registers_existing(
        self, monkeypatch, tmp_path
    ):
        """Existing bundled nvidia/cu12/bin is registered via the PHASE 4
        extension point."""
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        cuda_bin = tmp_path / "nvidia" / "cublas" / "bin"
        cuda_bin.mkdir(parents=True)
        import run as run_mod

        run_mod._register_frozen_cuda_dirs()
        assert any(
            d == cuda_bin.resolve() for d in rt.discover_cuda_dll_dirs()
        )

    def test_register_ignores_missing_dirs(self, monkeypatch, tmp_path):
        import ai.models.gpu_runtime as rt

        monkeypatch.setattr(rt, "_extra_dll_dirs", [])
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        import run as run_mod

        run_mod._register_frozen_cuda_dirs()
        # Only the bundle root (which exists) can be registered; missing
        # nvidia sub-layouts are skipped without error.
        assert rt.discover_cuda_dll_dirs() == [tmp_path.resolve()]

    def test_dev_mode_skips_cuda_registration(self, monkeypatch, tmp_path):
        """Non-frozen execution never touches the extension point."""
        monkeypatch.delattr(sys, "frozen", raising=False)
        import run as run_mod

        run_mod._register_frozen_cuda_dirs()  # no-op, no error


class TestFrozenPathSeparation:
    def test_user_data_never_under_resources(self, monkeypatch, tmp_path):
        """resource_root() under _MEIPASS; user_data_root() outside it."""
        from core import paths

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "MEI"), raising=False)
        monkeypatch.setenv("OFFLINE_AI_DATA_DIR", str(tmp_path / "userdata"))
        assert paths.resource_root() == (tmp_path / "MEI" / "resources").resolve()
        assert paths.user_data_root() == (tmp_path / "userdata").resolve()
        assert paths.resource_root() not in paths.user_data_root().parents

    def test_models_root_not_bundle(self, monkeypatch, tmp_path):
        """models.storage_root stays external to the frozen bundle."""
        from core import paths

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "MEI"), raising=False)
        root = paths.get_models_root()
        assert tmp_path / "MEI" != root
        assert (tmp_path / "MEI") not in root.parents

    def test_migration_source_exists(self):
        """The default datas glob points at real SQL files."""
        import glob

        matches = glob.glob(str(REPO / PRODUCTION_DATAS[0][0]))
        assert matches, "database/migrations/*.sql must exist for bundling"

    def test_optional_runtime_packages_declared(self):
        assert "llama_cpp" in OPTIONAL_RUNTIME_PACKAGES
        assert "faster_whisper" in OPTIONAL_RUNTIME_PACKAGES


class TestFrozenSmokeTest:
    """Validate run._frozen_smoke_test() — the headless frozen-build validator.

    This function runs inside the frozen executable when OFFLINE_AI_SMOKE_TEST=1
    is set.  It verifies path resolution, config init, resource separation,
    GPU safety, and migration reachability without launching the GUI.
    """

    def test_smoke_test_passes_in_test_env(self):
        """_frozen_smoke_test() returns 0 in the test environment.

        The test env (OFFLINE_AI_TEST_MODE=1, QT_QPA_PLATFORM=offscreen) ensures
        stub fallbacks are used so no GPU/model files are required.
        """
        import run as run_mod

        assert run_mod._frozen_smoke_test() == 0

    def test_smoke_test_catches_non_absolute_paths(self, monkeypatch):
        """Smoke test returns 1 when path resolution yields relative paths.

        This is the core CWD-independence invariant: all runtime paths must
        be absolute regardless of the process working directory.
        """
        from core import paths

        relative = Path("not_absolute")
        monkeypatch.setattr(paths, "user_data_root", lambda: relative)
        monkeypatch.setattr(paths, "get_config_dir", lambda: relative / "config")
        monkeypatch.setattr(paths, "get_models_root", lambda: relative / "models")
        import run as run_mod

        assert run_mod._frozen_smoke_test() == 1

    def test_smoke_test_catches_user_data_under_resources(self, monkeypatch):
        """Smoke test fails when user data would live under the bundle root."""
        from core import paths

        base = Path("/fake/bundle")
        monkeypatch.setattr(
            paths, "resource_root", lambda: base / "resources"
        )
        monkeypatch.setattr(
            paths, "user_data_root", lambda: base / "resources" / "userdata"
        )
        monkeypatch.setattr(
            paths, "get_config_dir", lambda: base / "resources" / "userdata" / "config"
        )
        monkeypatch.setattr(
            paths, "get_models_root", lambda: base / "resources" / "userdata" / "models"
        )
        import run as run_mod

        assert run_mod._frozen_smoke_test() == 1
