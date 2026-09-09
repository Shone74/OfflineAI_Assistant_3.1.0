"""Configuration manager for the Offline AI Assistant.

All settings live in ``config/settings.json`` which is created with safe
defaults on first run. Modules never read the JSON file directly — they go
through :class:`ConfigManager`.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.paths import SETTINGS_FILE, get_model_category_dir

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
        # PHASE 4: canonical GPU execution mode —
        #   "auto" (detect + safe strategy) | "cpu" (force CPU) | "gpu"
        #   (prefer GPU, degrade safely).  A non-zero ai.n_gpu_layers
        #   remains an expert override honoured by the runtime's
        #   centralized decision point (validated, never bypassing hard
        #   limits such as a CPU-only llama.cpp build).
        "gpu_mode": "auto",
        # Legacy keys kept for backward compatibility (PHASE 3): empty means
        # "derive from the canonical models.storage_root via core.paths".
        # The runtime (app.application) resolves empty values dynamically —
        # these static defaults are only the last-resort suggestion and are
        # computed from the deterministic user-data root, never a fixed
        # machine path.
        "models_dir": str(get_model_category_dir("llm")),
        "model_search_paths": [str(get_model_category_dir("llm"))],
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
    # PHASE 3: user-selected model storage root (canonical key).  Empty
    # string means "not configured yet" — the runtime then uses the
    # deterministic default suggestion (user-data models dir) or the legacy
    # ai.models_dir value.  Written by the welcome wizard / Settings UI via
    # core.paths.set_models_root(); never a relative path.
    "models": {
        "storage_root": "",
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
    """Load, validate, and persist application settings.

    ``set()`` uses a short write-coalescing window: the FIRST write in a
    burst persists immediately (single-write callers — wizard finalize,
    critical keys — never lose durability), while writes that follow
    within ``_WRITE_COALESCE_SECONDS`` only mark the config dirty and one
    trailing flush persists the final state.  This keeps slider/spinner
    ``valueChanged`` bursts from doing a full JSON serialization + atomic
    rename PER TICK without changing any observable persistence contract
    (the flush window is well under any UI action cadence and any later
    read goes through the in-memory ``_data`` anyway).
    """

    _WRITE_COALESCE_SECONDS = 1.0

    def __init__(self, settings_path: Path | None = None) -> None:
        self.settings_path = settings_path or SETTINGS_FILE
        self._data: dict[str, Any] = {}
        # M9: write-coalescing state (guarded by _write_lock; the flush
        # runs on a daemon timer thread so it is safe from any caller
        # thread, including non-GUI workers).
        self._write_lock = threading.Lock()
        self._last_write_ts = 0.0
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------ #
    def _flush_if_dirty(self) -> None:
        """Persist pending coalesced writes (called by the flush timer)."""
        with self._write_lock:
            if not self._dirty:
                return
            self._dirty = False
        self.save()

    def _schedule_flush(self) -> None:
        """Schedule the single trailing save after a coalesced burst."""
        timer = threading.Timer(
            self._WRITE_COALESCE_SECONDS, self._flush_if_dirty
        )
        timer.daemon = True
        timer.start()

    # ------------------------------------------------------------------ #

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
        """Set a dot-separated key and persist (write-coalesced).

        First write in a burst window persists immediately; rapid follow-up
        writes (slider/spinner valueChanged ticks) coalesce into one
        trailing flush so disk I/O stays O(1) per burst instead of O(n)
        per tick.  The in-memory value is ALWAYS updated synchronously —
        later ``get()`` calls observe it regardless of flush state.
        """
        parts = key.split(".")
        current: Any = self._data
        for part in parts[:-1]:
            current = current.setdefault(part, {})
        old_value = current.get(parts[-1])
        current[parts[-1]] = value
        try:
            with self._write_lock:
                now = time.monotonic()
                if now - self._last_write_ts >= self._WRITE_COALESCE_SECONDS:
                    # First write in a burst — persist now (durability for
                    # single-write callers).
                    self._last_write_ts = now
                    self._dirty = False
                    persist_now = True
                else:
                    # Inside a burst — coalesce; one trailing flush saves.
                    self._last_write_ts = now
                    self._dirty = True
                    persist_now = False
            if persist_now:
                self.save()
            else:
                self._schedule_flush()
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
