"""Installer System — Phase 12 (v1.2.0).

Public API:
    detect_hardware       — detect CPU / RAM / GPU / Storage
    recommend_model       — recommend an AI model size
    ModelDownloader       — download models with resume, checksum, retry
    PackageSpec           — metadata for a packaged installer build
    InnoSetupScript       — generated Inno Setup script content
    build_pyinstaller_spec — generate a PyInstaller spec
    write_pyinstaller_spec — write a PyInstaller spec to disk
    build_inno_setup_script — generate an Inno Setup script
    generate_installer_package — generate both packaging artifacts
    InstallConfig         — per-profile installation configuration
    InstallProfile        — installation profile enum
    HardwareProfile       — summary of detected hardware
    ModelRecommendation   — recommended model size
"""

from __future__ import annotations

from installer.config import InstallConfig, InstallProfile
from installer.downloader import DownloadResult, ModelDownloader
from installer.hardware import (
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

__all__ = [
    "DownloadResult",
    "HardwareProfile",
    "InnoSetupScript",
    "InstallConfig",
    "InstallProfile",
    "ModelDownloader",
    "ModelRecommendation",
    "PackageSpec",
    "build_inno_setup_script",
    "build_pyinstaller_spec",
    "detect_hardware",
    "generate_installer_package",
    "recommend_model",
    "write_pyinstaller_spec",
]