r"""Runtime path resolution for both development and PyInstaller environments.

Provides correct paths for user-writable data regardless of execution context.

Development: Uses project-relative paths.
PyInstaller: Uses %LOCALAPPDATA%\OfflineAI\ for all writable data.
"""

from __future__ import annotations

import sys
from pathlib import Path

USER_DATA_BASE = Path.home() / "AppData" / "Local" / "OfflineAI"

def _is_frozen() -> bool:
    """Check if running from PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")

def get_user_data_dir() -> Path:
    """Get base directory for user data (config, data, logs, models)."""
    return USER_DATA_BASE

def get_config_dir() -> Path:
    """Get configuration directory."""
    return get_user_data_dir() / "config"

def get_data_dir() -> Path:
    """Get database/data directory."""
    return get_user_data_dir() / "data"

def get_logs_dir() -> Path:
    """Get logs directory."""
    return get_user_data_dir() / "logs"

def get_models_dir() -> Path:
    """Get models directory."""
    return get_user_data_dir() / "models"


CONFIG_DIR: Path = get_config_dir()
DATA_DIR: Path = get_data_dir()
LOGS_DIR: Path = get_logs_dir()
MODELS_DIR: Path = get_models_dir()
LLM_DIR: Path = MODELS_DIR / "llm"
VOICE_DIR: Path = MODELS_DIR / "voice"
STT_DIR: Path = VOICE_DIR / "stt"
TTS_DIR: Path = VOICE_DIR / "tts"

SETTINGS_FILE = CONFIG_DIR / "settings.json"

if __name__ != "__main__":
    for _path in [CONFIG_DIR, DATA_DIR, LOGS_DIR, MODELS_DIR]:
        _path.mkdir(parents=True, exist_ok=True)