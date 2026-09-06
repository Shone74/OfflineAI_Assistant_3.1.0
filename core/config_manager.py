"""Configuration manager for the Offline AI Assistant.

All settings live in ``config/settings.json`` which is created with safe
defaults on first run. Modules never read the JSON file directly — they go
through :class:`ConfigManager`.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.paths import LLM_DIR, SETTINGS_FILE

logger = get_logger("config")

_DEFAULTS: dict[str, Any] = {
    "app": {
        "name": "Offline AI Assistant",
        "language": "en",
    },
    "ui": {
        "theme": "grey_emerald",
        "window_width": 1000,
        "window_height": 700,
    },
    "ai": {
        "model_name": "qwen-8b",
        "n_ctx": 4096,
        "n_threads": 4,
        "n_gpu_layers": 0,
        "auto_gpu_layers": True,
        "models_dir": str(LLM_DIR),
        "model_search_paths": [str(LLM_DIR)],
        "ollama_models_dir": "",
        "max_tokens": 512,
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "min_p": 0.05,
        "repeat_penalty": 1.1,
        "verifier": {
            "max_tokens": 256,
            "temperature": 0.1,
        },
    },
    "memory": {
        "short_term_window": 10,
        "enabled": True,
        "embedding_model": "stub",
        "max_context_memories": 5,
    },
    "filesystem": {
        "enabled": True,
        "read_roots": [],
        "write_roots": [],
        "follow_symlinks": True,
    },
    "assistant": {
        "identity": {"name": None, "description": ""},
        "communication": {
            "language": "auto",
            "tone": "neutral",
            "formality": "neutral",
            "response_style": "balanced",
        },
        "personality": {
            "traits": [],
            "humor": 0.5,
            "proactivity": 0.3,
        },
        "expertise": {"areas": []},
        "behavior": {
            "response_approach": "direct",
            "uncertainty_handling": "ask_clarify",
            "question_style": "open_ended",
        },
        "boundaries": {"custom_instructions": ""},
    },
    "logging": {
        "level": "INFO",
    },
    "voice": {
        "enabled": True,
        "language": "auto",
        "stt": {
            "provider": "faster-whisper",
            "model": "base",
            "device": "auto",
        },
        "tts": {
            "provider": "pyttsx3",
            "voice": "",
            "rate": 200,
            "volume": 1.0,
        },
        "wake_word": {
            "enabled": True,
            "provider": "openwakeword",
            "hotword": "hey_jarvis",
            "threshold": 0.5,
        },
    },
    "audio": {
        "input_device_index": None,
        "input_device_name": "",
        "input_device_hostapi": "",
        "output_device_index": None,
        "output_device_name": "",
        "output_device_hostapi": "",
        "prefer_wasapi": True,
        "wasapi_fallback_to_mme": True,
    },
    "api": {
        "enabled": False,
        "default_provider": "openrouter",
        # Legacy flat mirror (kept for backward compatibility with the
        # single-provider era; synced with providers.<default>):
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "",
        "timeout": 120,
        # Multi-provider store: {"openrouter": {"api_key": ..., "base_url": ..., "model": ...}, ...}
        "providers": {},
        # User-registered custom OpenAI-compatible providers:
        # {"myprovider": {"base_url": "https://..."}}
        "custom_providers": {},
    },
}


class ConfigManager:
    """Load, validate, and persist application settings."""

    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or SETTINGS_FILE
        self._data: dict[str, Any] = {}
        self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        if not self.settings_path.exists():
            logger.info("Settings file not found; creating with defaults at %s",
                        self.settings_path)
            self._data = _deep_copy(_DEFAULTS)
            self.save()
            return

        try:
            with open(self.settings_path, encoding="utf-8-sig") as fh:
                self._data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load settings: %s", exc)
            self._data = _deep_copy(_DEFAULTS)
            self.save()
            return

        self._data = _merge_defaults(_deep_copy(_DEFAULTS), self._data)

        # Migration: old default had auto_gpu_layers=False + n_gpu_layers=0
        # meaning "CPU only".  New default is auto_gpu_layers=True which calls
        # detect_optimal_gpu_layers() and preserves CPU fallback when CUDA
        # is unavailable.  Only migrate the old *default* combination; if the
        # user explicitly set n_gpu_layers to a non-zero value, leave it.
        ai_cfg = self._data.get("ai", {})
        if not ai_cfg.get("auto_gpu_layers") and ai_cfg.get("n_gpu_layers") == 0:
            ai_cfg["auto_gpu_layers"] = True
            self.save()

        logger.debug("Settings loaded from %s", self.settings_path)

    def save(self) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        data_str = json.dumps(self._data, indent=2, sort_keys=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(self.settings_path.parent),
            prefix=".tmp_settings_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(data_str)
            os.replace(tmp_path, self.settings_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        logger.debug("Settings saved to %s", self.settings_path)

    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Any = None) -> Any:
        """Get a dot-separated key, e.g. ``app.theme``."""
        current: Any = self._data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def set(self, key: str, value: Any) -> None:
        """Set a dot-separated key and persist immediately."""
        parts = key.split(".")
        current = self._data
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        old_value = current.get(parts[-1])
        current[parts[-1]] = value
        try:
            self.save()
        except OSError:
            current[parts[-1]] = old_value
            raise
        logger.debug("Config set: %s = %s", key, value)


# ---------------------------------------------------------------------- #
# Helper functions
# ---------------------------------------------------------------------- #
def _deep_copy(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: _deep_copy(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_deep_copy(v) for v in data]
    return data


def _merge_defaults(defaults: Any, override: Any) -> Any:
    if isinstance(defaults, dict) and isinstance(override, dict):
        for key, default_val in defaults.items():
            if key not in override:
                override[key] = _deep_copy(default_val)
            else:
                override[key] = _merge_defaults(default_val, override[key])
        return override
    return override if override is not None else _deep_copy(defaults)
