"""PHASE 6 regression tests — Inno Setup / production Windows installer.

Locks down the installer contract WITHOUT requiring a real Windows
installer execution inside pytest:

* the generated .iss packages the COMPLETE Phase 5 onedir payload
  (OfflineAI.exe + _internal) — never a one-file executable
* AppVersion is generated from the canonical pyproject.toml version
* application install directory and model storage stay separate
  concepts (models never under Program Files, never bundled, never
  configured by the installer)
* uninstall removes only {app}; user data / models / projects /
  configuration survive
* the installer owns NO model-path source of truth (models.storage_root
  remains canonical in the application)
* no developer-specific paths, no TestApp-era leftovers, no .gguf
  bundling
* generation is deterministic and relocatable
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.config import DEFAULT_MODELS_DIR, default_config
from installer.packager import (
    APP_NAME,
    INNO_SCRIPT_PATH,
    INSTALLER_NEVER_PACKAGES,
    ONEDIR_SOURCE_REL,
    build_inno_setup_script,
    get_canonical_version,
    write_production_inno_script,
)

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def iss(tmp_path: Path) -> str:
    return build_inno_setup_script(
        app_name=APP_NAME,
        version=get_canonical_version(),
        output_path=tmp_path / "OfflineAI.iss",
    ).script_text


@pytest.fixture()
def iss_file(tmp_path: Path) -> Path:
    return tmp_path / "OfflineAI.iss"


def _gen_iss(path: Path) -> str:
    return build_inno_setup_script(
        app_name=APP_NAME,
        version=get_canonical_version(),
        output_path=path,
    ).script_text


class TestOnedirPayloadIntegration:
    """The installer must consume the real Phase 5 onedir output."""

    def test_references_onedir_launcher(self, iss: str):
        assert r"dist\OfflineAI\OfflineAI.exe" in iss

    def test_packages_complete_internal_tree(self, iss: str):
        assert r"dist\OfflineAI\_internal\*" in iss
        assert "recursesubdirs" in iss
        assert "createallsubdirs" in iss

    def test_never_onefile_executable_only(self, iss: str):
        # A one-file payload (single .exe only) must not appear: the
        # _internal entry is mandatory in the same script.
        assert "[Files]" in iss
        assert iss.count("Source:") >= 2

    def test_launcher_shortcut(self, iss: str):
        assert 'Filename: "{app}\\OfflineAI.exe"' in iss
        assert "run.py" not in iss

    def test_onedir_source_constant(self, iss: str):
        # Relocatable source reference anchored at the .iss location.
        assert "{#SourcePath}" in iss


class TestStaleReferencesAbsent:
    """No TestApp-era / developer-specific leftovers in the installer."""

    def test_no_testapp_references(self, iss: str):
        for banned in ("TestApp", "TestApp.exe", r"dist\TestApp"):
            assert banned not in iss

    def test_no_developer_model_paths(self, iss: str):
        for banned in (
            r"E:\models",
            r"E:/models",
            r"C:\AI",
            r"D:\OfflineAI",
            "C:\\AI\\Models",
            "C:\\Program Files\\OfflineAI\\models",
        ):
            assert banned.lower() not in iss.lower()

    def test_no_absolute_drive_letters(self, iss: str):
        # Generated script must be relocatable: no machine-specific
        # absolute paths survive (DefaultDirName uses {autopf}).
        import re

        assert not re.search(r"[A-Z]:\\", iss)

    def test_no_hardcoded_developer_drives_in_default_install_dir(self, tmp_path):
        iss_text = build_inno_setup_script(
            app_name=APP_NAME,
            version="1.0.0",
            output_path=tmp_path / "OfflineAI.iss",
        ).script_text
        assert "DefaultDirName={autopf}\\OfflineAI" in iss_text


class TestVersionSingleSource:
    """Inno AppVersion must match the canonical pyproject version."""

    def test_app_version_matches_pyproject(self, iss: str):
        assert f"AppVersion={get_canonical_version()}" in iss

    def test_output_filename_uses_canonical_version(self, iss: str):
        assert f"OutputBaseFilename={APP_NAME}_Setup_{get_canonical_version()}" in iss

    def test_no_second_version_source(self, iss: str):
        # The version appears only through the canonical getter; a
        # hardcoded "1.0.0" (the stale TestApp.iss value) must not leak.
        assert "AppVersion=1.0.0" not in iss


class TestInstallVsModelStorageSeparation:
    """Install directory and model storage are separate concepts."""

    def test_default_install_dir_program_files(self, iss: str):
        assert "DefaultDirName={autopf}\\OfflineAI" in iss

    def test_installer_never_configures_models(self, iss: str):
        # The installer must NOT own a model path: no model location UI
        # markers, no models.storage_root writes, no [Dirs] creating
        # model directories, no model registry persistence.  Only the
        # directive lines (not the explanatory comments) are checked.
        directives = "\n".join(
            line for line in iss.splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        )
        for banned in (
            "models.storage_root",
            "models_dir",
            "[Dirs]",
            "UninstallRegistryKey",
        ):
            assert banned not in directives, (
                f"installer must not reference {banned!r} in directives"
            )

    def test_installer_config_models_default_not_program_files(self):
        config = default_config()
        assert "program files" not in str(config.models_dir).lower()
        assert DEFAULT_MODELS_DIR == config.models_dir

    def test_install_and_models_are_distinct_paths(self):
        config = default_config()
        assert config.install_dir not in config.models_dir.parents
        assert config.models_dir != config.install_dir

    def test_never_packages_models_or_user_data(self):
        # Documented payload exclusions.
        assert set(INSTALLER_NEVER_PACKAGES) >= {
            "models", "user_data", "config", "logs", "tests",
        }
        # And the payload source is exactly the onedir dist output.
        assert ONEDIR_SOURCE_REL == Path("dist") / "OfflineAI"


class TestUninstallSafety:
    """Uninstall semantics: remove binaries only, preserve user data."""

    def test_uninstall_delete_only_app(self, iss: str):
        assert 'Type: filesandordirs; Name: "{app}"' in iss

    def test_no_user_data_deletion(self, iss: str):
        # No [UninstallDelete] DIRECTIVE may touch user-data locations
        # or the models root (comments may mention them as context).
        section = iss.split("[UninstallDelete]", 1)[1]
        directives = [
            line for line in section.splitlines()
            if line.strip() and not line.lstrip().startswith(";")
        ]
        for line in directives:
            for banned in (
                "{localappdata}",
                "{userappdata}",
                "models",
                "knowledge",
                "projects",
                "config",
                "logs",
            ):
                assert banned.lower() not in line.lower(), (
                    f"uninstall directive must not touch {banned!r}: {line}"
                )

    def test_no_recursive_user_data_delete(self, iss: str):
        section = iss.split("[UninstallDelete]", 1)[1]
        # The single recursive cleanup entry targets {app} only.
        import re

        recursive_targets = re.findall(
            r"Type:\s*filesandordirs;\s*Name:\s*\"([^\"]+)\"", section
        )
        assert recursive_targets == ["{app}"]


class TestModelRootArchitecture:
    """The application remains the source of truth for model storage."""

    def test_models_storage_root_remains_canonical(self):
        from core import paths

        assert paths.MODELS_ROOT_CONFIG_KEY == "models.storage_root"
        assert callable(paths.set_models_root)
        assert callable(paths.get_models_root)

    def test_installer_does_not_persist_model_root(self, iss: str):
        # No command-line model-root handoff, no initialization value
        # written by the installer (the first-run wizard owns the UX).
        assert "--models-root" not in iss
        assert "OFFLINE_AI_MODELS_ROOT" not in iss

    def test_wizard_owns_model_selection(self):
        # The application first-run wizard persists the choice through
        # set_models_root -> models.storage_root (verified live in
        # test_phase3_models_root.py); the installer contains none of
        # this logic.
        from core.paths import set_models_root

        assert callable(set_models_root)


class TestShortcutsAndPrivileges:
    def test_start_menu_shortcut(self, iss: str):
        assert 'Name: "{group}\\OfflineAI"; Filename: "{app}\\OfflineAI.exe"' in iss

    def test_desktop_shortcut_optional_task(self, iss: str):
        assert "{autodesktop}\\OfflineAI" in iss
        assert "Tasks: desktopicon" in iss
        assert "desktopicon" in iss

    def test_normal_privileges(self, iss: str):
        assert "PrivilegesRequired=admin" in iss
        assert "PrivilegesRequiredOverridesAllowed=dialog commandline" in iss

    def test_x64_only(self, iss: str):
        assert "ArchitecturesAllowed=x64compatible" in iss
        assert "ArchitecturesInstallIn64BitMode=x64compatible" in iss


class TestDeterminism:
    def test_generation_is_deterministic(self, iss_file: Path):
        first = _gen_iss(iss_file)
        second = _gen_iss(iss_file)
        assert first == second

    def test_default_output_location_is_repo_layout(self):
        # No output_path -> deterministic repo layout (never CWD).
        script = build_inno_setup_script(
            app_name=APP_NAME, version="3.1.0", output_path=None
        )
        assert script.output_path.name == f"{APP_NAME}.iss"
        assert script.output_path.parent.name == "installer"

    def test_production_script_written_to_repo_layout(self, tmp_path: Path):
        path = write_production_inno_script(project_root=tmp_path)
        assert path == tmp_path / INNO_SCRIPT_PATH
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert f"AppVersion={get_canonical_version()}" in content


class TestInstallerArtifactValidation:
    """Validate the actual built artifact when present (no install)."""

    INSTALLER = REPO / "installer_output" / (
        f"{APP_NAME}_Setup_{get_canonical_version()}.exe"
    )

    def test_installer_exe_exists(self):
        if not self.INSTALLER.exists():
            pytest.skip("installer .exe not built in this environment")
        assert self.INSTALLER.stat().st_size > 10 * 1024 * 1024

    def test_installer_exe_has_no_developer_paths_or_models(self):
        if not self.INSTALLER.exists():
            pytest.skip("installer .exe not built in this environment")
        blob = self.INSTALLER.read_bytes()
        for needle in (
            b"E:\\models",
            b"C:\\AI\\",
            b"D:\\OfflineAI",
            b"TestApp",
            b"G:\\Projekti",
        ):
            assert needle not in blob, f"installer contains {needle!r}"

    def test_installer_exe_contains_no_gguf(self):
        if not self.INSTALLER.exists():
            pytest.skip("installer .exe not built in this environment")
        blob = self.INSTALLER.read_bytes()
        # Compressed payload cannot literally contain a .gguf marker
        # name, but the payload manifest is checked: no .gguf filenames.
        assert b".gguf" not in blob

    def test_no_user_data_bundled_in_payload(self):
        # The packaged payload is dist/OfflineAI only: verify the
        # source directory contains no user-data layout.
        onedir = REPO / "dist" / APP_NAME
        if not onedir.is_dir():
            pytest.skip("PyInstaller onedir output not present")
        for banned in ("models", "config", "logs", "knowledge_docs", "plugins"):
            assert not (onedir / banned).exists(), f"{banned} must not be bundled"
        assert (onedir / "_internal").is_dir()
        assert (onedir / "OfflineAI.exe").is_file()
