"""Regression tests for installer modules (Phase D1).

Covers: packager (PyInstaller spec + Inno Setup script generation),
hardware detection, downloader, config.
All tests run in OFFLINE_AI_TEST_MODE (headless).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from installer.config import InstallProfile, default_config, load_config, save_config
from installer.downloader import (
    DownloadProgress,
    ModelDownloader,
)
from installer.hardware import (
    GPUBrand,
    HardwareProfile,
    ModelRecommendation,
    detect_hardware,
    recommend_model,
)
from installer.packager import (
    InnoSetupScript,
    PackageSpec,
    build_inno_setup_script,
    build_pyinstaller_spec,
    generate_installer_package,
    write_pyinstaller_spec,
)

# --------------------------------------------------------------------------- #
# Packager tests
# --------------------------------------------------------------------------- #

class TestPackageSpec:
    def test_package_spec_defaults(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="main.py",
        )
        assert spec.app_name == "TestApp"
        assert spec.version == "1.0.0"
        assert spec.entry_point == "main.py"
        assert spec.target_dir == Path("dist")
        assert spec.work_dir == Path("build")
        assert spec.spec_file == Path("installer.spec")

    def test_package_spec_custom_paths(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="main.py",
            target_dir=Path("/custom/dist"),
            work_dir=Path("/custom/build"),
            spec_file=Path("/custom/spec.spec"),
        )
        assert spec.target_dir == Path("/custom/dist")
        assert spec.work_dir == Path("/custom/build")
        assert spec.spec_file == Path("/custom/spec.spec")


class TestPyInstallerSpecGeneration:
    def test_build_pyinstaller_spec_basic(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
        )
        content = build_pyinstaller_spec(spec)

        # Check key sections exist
        assert "block_cipher = None" in content
        assert "a = Analysis(" in content
        assert "'run.py'" in content
        assert "pyz = PYZ(" in content
        assert "exe = EXE(" in content
        assert "coll = COLLECT(" in content
        assert "TestApp" in content
        # PHASE 5 contract: UPX disabled for deterministic native builds.
        assert "upx=False" in content

    def test_build_pyinstaller_spec_includes_additional_files(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
            additional_files=[("config.json", "config"), ("data/", "data")],
        )
        content = build_pyinstaller_spec(spec)
        assert "('config.json', 'config')" in content
        assert "('data/', 'data')" in content

    def test_build_pyinstaller_spec_includes_hiddenimports(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
        )
        content = build_pyinstaller_spec(spec)
        # PHASE 5 contract: static analysis discovers project modules; the
        # spec adds only imports static analysis cannot see (win32com via
        # dynamic COM support) and installed optional backends.
        assert "'win32com'" in content

    def test_build_pyinstaller_spec_excludes_test_modules(self):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
        )
        content = build_pyinstaller_spec(spec)
        assert "'tkinter'" in content  # in excludes
        assert "'unittest'" in content
        assert "'tests'" in content
        assert "'docs'" in content
        # PHASE 5 contract: the installer package is REQUIRED at runtime
        # (ui.welcome_wizard / ui.model_manager_dialog import
        # installer.hardware at module level) — excluding it was a bug.
        assert "'installer'" not in content

    def test_write_pyinstaller_spec_creates_file(self, tmp_path):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
            spec_file=tmp_path / "test.spec",
        )
        out_path = write_pyinstaller_spec(spec)
        assert out_path == tmp_path / "test.spec"
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "TestApp" in content


class TestInnoSetupScriptGeneration:
    """PHASE 6 contract: real onedir payload, no user-data dirs, safe uninstall."""

    def test_build_inno_setup_script_basic(self, tmp_path):
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            output_path=tmp_path / "MyApp.iss",
        )
        assert isinstance(iss, InnoSetupScript)
        content = iss.script_text

        assert "AppName=MyApp" in content
        assert "AppVersion=1.0.0" in content
        assert "DefaultDirName={autopf}\\MyApp" in content
        assert "Compression=lzma2/max" in content
        assert "SolidCompression=yes" in content
        assert "PrivilegesRequired=admin" in content
        assert "[Files]" in content
        assert "[Icons]" in content
        assert "[Run]" in content
        assert "[UninstallDelete]" in content
        # PHASE 6: no [Dirs] — the app creates its own user data at
        # runtime under the real user account.
        assert "[Dirs]" not in content

    def test_build_inno_setup_script_packages_onedir_payload(self, tmp_path):
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            output_path=tmp_path / "MyApp.iss",
        )
        content = iss.script_text
        assert r"dist\MyApp\MyApp.exe" in content
        assert r"dist\MyApp\_internal\*" in content
        assert "recursesubdirs" in content

    def test_build_inno_setup_script_does_not_create_data_dirs(self, tmp_path):
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            output_path=tmp_path / "MyApp.iss",
        )
        content = iss.script_text
        # PHASE 6: user-data creation belongs to the application, not
        # the (elevated) installer process.
        assert r"{localappdata}" not in content.split("[UninstallDelete]")[0]

    def test_build_inno_setup_script_creates_shortcuts(self, tmp_path):
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            output_path=tmp_path / "MyApp.iss",
        )
        content = iss.script_text
        assert "{group}\\MyApp" in content
        assert "{autodesktop}\\MyApp" in content
        assert "Tasks: desktopicon" in content

    def test_build_inno_setup_script_custom_install_dir(self, tmp_path):
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            install_dir=r"C:\Custom\Path",
            output_path=tmp_path / "MyApp.iss",
        )
        assert r"DefaultDirName=C:\Custom\Path" in iss.script_text

    def test_build_inno_setup_script_writes_file(self, tmp_path):
        output = tmp_path / "test.iss"
        iss = build_inno_setup_script(
            app_name="MyApp",
            version="1.0.0",
            app_filename="MyApp",
            output_path=output,
        )
        assert iss.output_path == output
        assert output.exists()
        assert "MyApp" in output.read_text(encoding="utf-8")


class TestGenerateInstallerPackage:
    def test_generate_installer_package_returns_both(self, tmp_path):
        spec = PackageSpec(
            app_name="TestApp",
            version="1.0.0",
            entry_point="run.py",
            spec_file=tmp_path / "test.spec",
        )
        spec_content, iss = generate_installer_package(spec, inno_output=tmp_path / "test.iss")

        assert isinstance(spec_content, str)
        assert "TestApp" in spec_content
        assert isinstance(iss, InnoSetupScript)
        assert "TestApp" in iss.script_text
        assert (tmp_path / "test.spec").exists()
        assert (tmp_path / "test.iss").exists()


# --------------------------------------------------------------------------- #
# Hardware detection tests
# --------------------------------------------------------------------------- #

class TestHardwareDetection:
    @patch("installer.hardware.platform.processor")
    @patch("installer.hardware.psutil.cpu_count")
    @patch("installer.hardware.psutil.virtual_memory")
    @patch("installer.hardware.psutil.disk_usage")
    @patch("installer.hardware._detect_gpu")
    def test_detect_hardware_returns_profile(
        self, mock_detect_gpu, mock_disk, mock_mem, mock_cpu_count, mock_processor
    ):
        mock_processor.return_value = "AMD Ryzen 7 5700X"
        mock_cpu_count.side_effect = [8, 16]  # logical=False, logical=True

        mock_mem.return_value = MagicMock(total=32 * 1024**3, available=16 * 1024**3)
        mock_disk.return_value = MagicMock(total=500 * 1024**3, free=100 * 1024**3)
        mock_detect_gpu.return_value = (GPUBrand.NVIDIA, "RTX 3080", 10.0, True)

        profile = detect_hardware()

        assert isinstance(profile, HardwareProfile)
        assert profile.cpu_name == "AMD Ryzen 7 5700X"
        assert profile.cpu_cores == 8
        assert profile.cpu_threads == 16
        assert profile.ram_total_gb == 32.0
        assert profile.gpu_brand == GPUBrand.NVIDIA
        assert profile.gpu_name == "RTX 3080"
        assert profile.gpu_vram_gb == 10.0
        assert profile.storage_free_gb == 100.0
        assert profile.cuda_available is True

    @patch("installer.hardware.platform.processor")
    @patch("installer.hardware.psutil.cpu_count")
    @patch("installer.hardware.psutil.virtual_memory")
    @patch("installer.hardware.psutil.disk_usage")
    @patch("installer.hardware._detect_gpu")
    def test_detect_hardware_no_gpu(
        self, mock_detect_gpu, mock_disk, mock_mem, mock_cpu_count, mock_processor
    ):
        mock_processor.return_value = "Intel i5"
        mock_cpu_count.side_effect = [4, 8]
        mock_mem.return_value = MagicMock(total=16 * 1024**3, available=8 * 1024**3)
        mock_disk.return_value = MagicMock(total=256 * 1024**3, free=50 * 1024**3)
        mock_detect_gpu.return_value = (GPUBrand.UNKNOWN, "", None, False)

        profile = detect_hardware()

        assert profile.gpu_brand == GPUBrand.UNKNOWN
        assert profile.gpu_name == ""
        assert profile.gpu_vram_gb is None
        assert profile.cuda_available is False

    def test_recommend_model_high_end_gpu(self):
        from installer.hardware import GPUBrand, HardwareProfile
        profile = HardwareProfile(
            cpu_name="AMD Ryzen 9",
            cpu_cores=16,
            cpu_threads=32,
            ram_total_gb=64,
            ram_available_gb=32,
            gpu_brand=GPUBrand.NVIDIA,
            gpu_name="RTX 4090",
            gpu_vram_gb=24.0,
            storage_total_gb=1000,
            storage_free_gb=500,
            cuda_available=True,
        )
        rec = recommend_model(profile)
        assert isinstance(rec, ModelRecommendation)
        assert rec.label == "14B (CUDA)"
        assert rec.model_size_b == 14_000_000_000

    def test_recommend_model_mid_range_gpu(self):
        from installer.hardware import GPUBrand, HardwareProfile
        profile = HardwareProfile(
            cpu_name="AMD Ryzen 7",
            cpu_cores=8,
            cpu_threads=16,
            ram_total_gb=32,
            ram_available_gb=16,
            gpu_brand=GPUBrand.NVIDIA,
            gpu_name="RTX 3080",
            gpu_vram_gb=10.0,
            storage_total_gb=500,
            storage_free_gb=200,
            cuda_available=True,
        )
        rec = recommend_model(profile)
        assert isinstance(rec, ModelRecommendation)
        assert rec.label == "7B (CUDA)"
        assert rec.model_size_b == 7_000_000_000

    def test_recommend_model_no_gpu(self):
        from installer.hardware import GPUBrand, HardwareProfile
        profile = HardwareProfile(
            cpu_name="Intel i5",
            cpu_cores=6,
            cpu_threads=12,
            ram_total_gb=16,
            ram_available_gb=8,
            gpu_brand=GPUBrand.UNKNOWN,
            gpu_name="",
            gpu_vram_gb=None,
            storage_total_gb=256,
            storage_free_gb=100,
            cuda_available=False,
        )
        rec = recommend_model(profile)
        assert isinstance(rec, ModelRecommendation)
        # With 16 GB RAM, should recommend 14b (min 16 GB for 14b)
        assert rec.model_size_b == 14_000_000_000
        assert rec.label == "14b"

    def test_recommend_model_low_ram(self):
        from installer.hardware import GPUBrand, HardwareProfile
        profile = HardwareProfile(
            cpu_name="Intel i3",
            cpu_cores=4,
            cpu_threads=8,
            ram_total_gb=8,
            ram_available_gb=4,
            gpu_brand=GPUBrand.UNKNOWN,
            gpu_name="",
            gpu_vram_gb=None,
            storage_total_gb=128,
            storage_free_gb=50,
            cuda_available=False,
        )
        rec = recommend_model(profile)
        assert isinstance(rec, ModelRecommendation)
        # With 8 GB RAM, should recommend 7b (min 8 GB for 7b)
        assert rec.model_size_b == 7_000_000_000
        assert rec.label == "7b"


# --------------------------------------------------------------------------- #
# Downloader tests
# --------------------------------------------------------------------------- #

class TestModelDownloader:
    def test_download_progress_dataclass(self):
        from installer.downloader import DownloadStatus
        progress = DownloadProgress(
            bytes_downloaded=500,
            total_bytes=1000,
            chunks_downloaded=1,
            status=DownloadStatus.DOWNLOADING,
        )
        assert progress.bytes_downloaded == 500
        assert progress.total_bytes == 1000
        assert progress.status == DownloadStatus.DOWNLOADING

    def test_downloader_init(self):
        downloader = ModelDownloader()
        assert downloader is not None


# --------------------------------------------------------------------------- #
# InstallConfig tests
# --------------------------------------------------------------------------- #

class TestInstallConfig:
    def test_install_config_defaults(self):
        config = default_config(InstallProfile.STANDARD)
        assert config.profile == InstallProfile.STANDARD
        assert config.install_dir is not None

    def test_install_config_custom(self):
        config = default_config(InstallProfile.ADVANCED)
        assert config.profile == InstallProfile.ADVANCED
        assert config.enable_voice is True
        assert config.enable_knowledge is True

    def test_install_config_save_load(self, tmp_path):
        config = default_config(InstallProfile.BASIC)
        config_path = tmp_path / "install_config.json"
        save_config(config, config_path)

        loaded = load_config(config_path)
        assert loaded.profile == InstallProfile.BASIC
        assert loaded.model_label == "3B"