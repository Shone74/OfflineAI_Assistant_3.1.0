"""Installation configuration for the Installer System.

Defines install profiles (Basic / Standard / Advanced), default
paths, and profile-to-model mapping so the installer can pre-
select options based on the user's hardware.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class InstallProfile(str, Enum):
    BASIC = "basic"
    STANDARD = "standard"
    ADVANCED = "advanced"


@dataclass(frozen=True, slots=True)
class InstallConfig:
    """Per-profile installation configuration."""

    profile: InstallProfile
    install_dir: Path
    models_dir: Path
    config_dir: Path
    logs_dir: Path
    data_dir: Path
    model_size_b: int
    model_label: str
    enable_voice: bool
    enable_knowledge: bool
    enable_automation: bool
    enable_plugins: bool
    offline_mode: bool


_PROFILE_DEFAULTS: dict[InstallProfile, dict] = {
    InstallProfile.BASIC: {
        "model_size_b": 3_000_000_000,
        "model_label": "3B",
        "enable_voice": False,
        "enable_knowledge": False,
        "enable_automation": False,
        "enable_plugins": False,
        "offline_mode": True,
    },
    InstallProfile.STANDARD: {
        "model_size_b": 7_000_000_000,
        "model_label": "7B",
        "enable_voice": True,
        "enable_knowledge": True,
        "enable_automation": True,
        "enable_plugins": True,
        "offline_mode": True,
    },
    InstallProfile.ADVANCED: {
        "model_size_b": 14_000_000_000,
        "model_label": "14B",
        "enable_voice": True,
        "enable_knowledge": True,
        "enable_automation": True,
        "enable_plugins": True,
        "offline_mode": False,
    },
}


DEFAULT_INSTALL_DIR = Path(r"C:\Program Files\OfflineAI")
DEFAULT_USER_DATA_DIR = Path.home() / "AppData" / "Local" / "OfflineAI"


def default_config(profile: InstallProfile = InstallProfile.STANDARD) -> InstallConfig:
    """Return a default InstallConfig for the given profile."""
    defaults = _PROFILE_DEFAULTS[profile]
    return InstallConfig(
        profile=profile,
        install_dir=DEFAULT_INSTALL_DIR,
        models_dir=DEFAULT_INSTALL_DIR / "models",
        config_dir=DEFAULT_USER_DATA_DIR / "config",
        logs_dir=DEFAULT_USER_DATA_DIR / "logs",
        data_dir=DEFAULT_USER_DATA_DIR / "data",
        model_size_b=defaults["model_size_b"],
        model_label=defaults["model_label"],
        enable_voice=defaults["enable_voice"],
        enable_knowledge=defaults["enable_knowledge"],
        enable_automation=defaults["enable_automation"],
        enable_plugins=defaults["enable_plugins"],
        offline_mode=defaults["offline_mode"],
    )


def save_config(config: InstallConfig, path: Path) -> None:
    """Serialize InstallConfig to JSON on disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "profile": config.profile.value,
        "install_dir": str(config.install_dir),
        "models_dir": str(config.models_dir),
        "config_dir": str(config.config_dir),
        "logs_dir": str(config.logs_dir),
        "data_dir": str(config.data_dir),
        "model_size_b": config.model_size_b,
        "model_label": config.model_label,
        "enable_voice": config.enable_voice,
        "enable_knowledge": config.enable_knowledge,
        "enable_automation": config.enable_automation,
        "enable_plugins": config.enable_plugins,
        "offline_mode": config.offline_mode,
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_config(path: Path) -> InstallConfig:
    """Deserialize InstallConfig from JSON on disk."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return InstallConfig(
        profile=InstallProfile(raw["profile"]),
        install_dir=Path(raw["install_dir"]),
        models_dir=Path(raw["models_dir"]),
        config_dir=Path(raw["config_dir"]),
        logs_dir=Path(raw["logs_dir"]),
        data_dir=Path(raw["data_dir"]),
        model_size_b=raw["model_size_b"],
        model_label=raw["model_label"],
        enable_voice=raw["enable_voice"],
        enable_knowledge=raw["enable_knowledge"],
        enable_automation=raw["enable_automation"],
        enable_plugins=raw["enable_plugins"],
        offline_mode=raw["offline_mode"],
    )
