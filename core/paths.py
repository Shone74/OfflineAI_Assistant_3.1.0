r"""Runtime path resolution — single source of truth for application paths.

Deterministic, CWD-independent path architecture for both development and
PyInstaller (frozen) environments.

Layout contract:

* ``app_root()``          — application installation root (dev: project root,
                            frozen: ``sys._MEIPASS`` runtime root).
* ``resource_root()``     — bundled read-only resources (never writable,
                            never used for user data).
* ``user_data_root()``    — user-writable application data
                            (default ``%LOCALAPPDATA%\\OfflineAI``).

Environment override:

    OFFLINE_AI_DATA_DIR

Rules for the override (documented contract):

* Unset or empty           -> the default ``%LOCALAPPDATA%\\OfflineAI`` is used.
* Absolute path            -> accepted and used as the user-data root.
* Relative path            -> REJECTED (logged warning) and the default is
                              used instead.  Relative overrides are never
                              resolved against the process CWD — that would
                              reintroduce a CWD dependency.  Rejecting keeps
                              behaviour deterministic.

Directory creation:

* Importing this module does NOT create any directory.
* Call :func:`ensure_dirs` explicitly to create the writable application
  directories (config/data/logs/models).

External AI models (PHASE 3): the user-selected model storage root is a
single logical setting — ``models.storage_root`` — persisted in the
application configuration and selected during first-run setup (or later in
Settings).  It may live on ANY drive/location the user chose; no path is
ever hardcoded and the application never assumes a fixed drive letter or
that models sit inside the installation or user-data directories.  See the
"User-selected model storage" section below.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Environment variable for the user-data root override (see module docstring).
DATA_DIR_ENV_VAR = "OFFLINE_AI_DATA_DIR"

# Default user-data location: %LOCALAPPDATA%\OfflineAI.
# Built from Path.home() so it never depends on the process CWD or on the
# LOCALAPPDATA environment variable being set correctly for this process.
DEFAULT_USER_DATA_BASE = Path.home() / "AppData" / "Local" / "OfflineAI"


def _is_frozen() -> bool:
    """Return True when running inside a PyInstaller bundle.

    ``sys.frozen`` is the authoritative PyInstaller marker (set for both
    onefile and onedir builds).  ``sys._MEIPASS`` alone is NOT treated as a
    frozen signal — a stale ``_MEIPASS`` attribute must never switch a
    normal development process into frozen mode.  ``_MEIPASS`` is only used
    (after the frozen check) to resolve the bundle resource root.
    """
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """Return the application installation root.

    Development: the project/application directory (the directory that
    contains the ``core`` package).

    Frozen: the PyInstaller runtime root (``sys._MEIPASS``).  This is the
    bundle's read-only extraction/assembly root, NOT a writable location.
    """
    if _is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
    # Development: <project root>/core/paths.py -> project root.
    return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
    """Return the bundled read-only resources root.

    Development: ``<project root>/resources``.

    Frozen: ``Path(sys._MEIPASS) / "resources"``.

    Resources are assumed read-only.  Never place user-writable data here.
    """
    if _is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return (Path(meipass) / "resources").resolve()
    return app_root() / "resources"


def _resolve_user_data_root() -> Path:
    """Resolve the user-data root honouring the OFFLINE_AI_DATA_DIR override.

    See the module docstring for the override contract.  The result is always
    an absolute, resolved path and never depends on the process CWD.
    """
    override = os.environ.get(DATA_DIR_ENV_VAR, "").strip()
    if override:
        candidate = Path(override)
        if not candidate.is_absolute():
            # Relative overrides are rejected, not CWD-resolved.  Falling
            # back to the default keeps the application functional and the
            # behaviour deterministic regardless of the working directory.
            print(
                f"[core.paths] {DATA_DIR_ENV_VAR} must be an absolute path; "
                f"ignoring relative override {override!r} and using the "
                f"default user-data location.",
                file=sys.stderr,
            )
        else:
            try:
                return candidate.resolve()
            except OSError:
                # Path.resolve can fail on exotic/invalid paths; fall back to
                # absolute() which never touches the filesystem.
                return candidate.absolute()
    try:
        return DEFAULT_USER_DATA_BASE.resolve()
    except OSError:
        return DEFAULT_USER_DATA_BASE.absolute()


def user_data_root() -> Path:
    """Return the user-writable application data root.

    Default: ``Path.home() / "AppData" / "Local" / "OfflineAI"``.
    Override: absolute path in the ``OFFLINE_AI_DATA_DIR`` environment
    variable (relative values are rejected — see module docstring).

    Never falls back to the process CWD.  Never under ``_MEIPASS``.
    Never under Program Files unless the user explicitly overrides to it.
    """
    return _resolve_user_data_root()


def get_user_data_dir() -> Path:
    """Get base directory for user data (config, data, logs, models).

    Compatibility alias for :func:`user_data_root`.
    """
    return user_data_root()


def get_config_dir() -> Path:
    """Get the configuration directory."""
    return user_data_root() / "config"


def get_data_dir() -> Path:
    """Get the database/data directory."""
    return user_data_root() / "data"


def get_logs_dir() -> Path:
    """Get the logs directory."""
    return user_data_root() / "logs"


def get_models_dir() -> Path:
    """Get the default (user-data) models directory.

    PHASE 3: this is only the DEFAULT SUGGESTION for model storage when the
    user has not selected a custom root.  The canonical, user-selected root
    is :func:`get_models_root` (config-driven, any drive/location).
    """
    return user_data_root() / "models"


def ensure_dirs() -> list[Path]:
    """Create the required writable application directories.

    Explicit creation point — importing :mod:`core.paths` never creates
    directories.  Returns the list of directories that were ensured.

    Raises OSError (propagated from mkdir) on genuine filesystem failures;
    callers that must stay resilient (e.g. startup) catch and log it.
    """
    dirs = [
        get_config_dir(),
        get_data_dir(),
        get_logs_dir(),
        get_models_dir(),
        get_plugins_dir(),
        get_knowledge_docs_dir(),
    ]
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)
    return dirs


# --------------------------------------------------------------------------- #
# Writable runtime drop-locations (NOT bundled resources)
# --------------------------------------------------------------------------- #

def get_plugins_dir() -> Path:
    """Return the runtime plugins directory under the user-data root.

    This is where operators drop third-party plugins (each
    ``<plugin_id>/plugin.json``) at runtime; the app discovers and loads
    them from here.  It is writable user data — deliberately NOT the
    read-only ``plugins`` source package of the application and NOT a
    bundled ``resource_root()`` location.  Kept empty (zero plugins) is a
    valid, fully functional state.
    """
    return user_data_root() / "plugins"


def get_knowledge_docs_dir() -> Path:
    """Return the runtime knowledge documents directory under the user-data root.

    This is where the user drops ``*.md`` / ``*.txt`` documents for
    indexing.  The knowledge indexer only *reads* this directory (the
    persistent index itself lives under the data directory); the directory
    must nonetheless be user-writable so users can add documents, which
    rules out any read-only bundled location.
    """
    return user_data_root() / "knowledge_docs"


# --------------------------------------------------------------------------- #
# User-selected model storage (PHASE 3)
# --------------------------------------------------------------------------- #
# One logical setting: ``models.storage_root`` in settings.json.  It is the
# user-selected root directory for externally stored AI models (any drive,
# anywhere the user chose during setup or later in Settings).  It is
# DISTINCT from the application installation, from bundled read-only
# resources, and independent from the normal user-data root.
#
# Layout under models_root (existing categories, standardized):
#     <models_root>/llm/        — chat + vision GGUF (+ mmproj companions)
#     <models_root>/embedding/ — embedding GGUF
#     <models_root>/stt/       — faster-whisper model folders
#
# The historical layout kept voice models under models/voice/stt; the
# default user-data models root retains that layout, and the stt category
# resolver honours both (vision companions stay next to their LLM, matching
# the existing mmproj discovery contract).
#
# Migration/precedence (minimal, models-only — Phase 9 owns broad migration):
#     1. ``models.storage_root``       (canonical; wins when set)
#     2. ``ai.models_dir``             (legacy absolute path — migrated
#                                       transparently: category dirs derive
#                                       from its PARENT so existing trees
#                                       with llm/ keep working)
#     3. user-data ``<user_data>/models`` (default suggestion only)
# Relative values are REJECTED, never CWD-resolved.
#
# PHASE 9 — roles of the three model-storage settings (all retained):
#
# ``models.storage_root``
#     CANONICAL model-storage root.  New code and UI treat this as the
#     primary root; the wizard/Settings persist it via
#     :func:`set_models_root`.  Nothing supersedes it.
#
# ``ai.models_dir``
#     LEGACY COMPATIBILITY KEY — intentionally retained (NOT removed in
#     Phase 9).  Pre-Phase-3 settings.json files carry only this key;
#     :func:`get_models_root` still resolves them (precedence 2 above),
#     taking the PARENT when the value points at the llm category dir.
#     :func:`set_models_root` MIRRORS every change to ``<root>/llm``
#     under this key so older readers stay consistent during the
#     transition (see its docstring).
#
# ``ai.model_search_paths``
#     LEGACY/ADVISORY additional search roots — intentionally retained
#     (NOT removed in Phase 9).  Read ONCE at application startup
#     (``app.application``) and passed to
#     ``ModelManager(search_paths=...)`` as ADDITIONAL scan directories
#     on top of the canonical root's llm category dir, so hand-edited
#     absolute entries keep participating in model discovery.  It is a
#     search hint, NOT a storage location, and never a replacement for
#     ``models.storage_root``.  :func:`set_models_root` rewrites the
#     list to ``[<root>/llm]`` to keep it coherent with the canonical
#     root.  STARTUP-ONLY: runtime root changes re-point the manager
#     (``set_models_dir`` replaces the search-path list) without
#     touching this key; edited values apply on next launch.

# Configuration keys (dot-separated, matching ConfigManager semantics).
MODELS_ROOT_CONFIG_KEY = "models.storage_root"
LEGACY_MODELS_DIR_CONFIG_KEY = "ai.models_dir"
_LEGACY_MODELS_DIR_CATEGORY = "llm"  # category the legacy key pointed at

# Category layout constants (stable, user-facing contract).
MODEL_CATEGORIES = ("llm", "embedding", "stt")
_STT_LEGACY_SUBPATH = Path("voice") / "stt"  # legacy models/voice/stt layout

# Optional environment override mirroring OFFLINE_AI_DATA_DIR semantics.
# Primarily for tests; the configuration key is the production source.
MODELS_ROOT_ENV_VAR = "OFFLINE_AI_MODELS_ROOT"


def _read_settings_models_root() -> tuple[str, bool]:
    """Best-effort read of the models_root keys from settings.json.

    Returns ``(value, from_canonical_key)`` where *value* is the raw
    non-empty string (or ``""``) and *from_canonical_key* says whether it
    came from ``models.storage_root`` (canonical) or ``ai.models_dir``
    (legacy).  Tolerates a missing/corrupt file.  Avoids importing
    ConfigManager to keep core.paths dependency-free at import time.
    """
    try:
        import json

        with SETTINGS_FILE.open(encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return "", False
    models_cfg = data.get("models")
    if isinstance(models_cfg, dict):
        root = models_cfg.get("storage_root")
        if isinstance(root, str) and root.strip():
            return root.strip(), True
    # Legacy key: ai.models_dir pointed at the llm category directory.
    ai_cfg = data.get("ai")
    if isinstance(ai_cfg, dict):
        legacy = ai_cfg.get("models_dir")
        if isinstance(legacy, str) and legacy.strip():
            return legacy.strip(), False
    return "", False


def _resolve_models_root_candidate(value: str) -> Path | None:
    """Return a normalized absolute models root from *value*, or None.

    Absolute values are accepted and resolved.  Relative values are
    rejected (logged) — never resolved against the process CWD.
    """
    candidate = Path(value)
    if not candidate.is_absolute():
        print(
            f"[core.paths] models_root must be an absolute path; ignoring "
            f"relative value {value!r}. Relative model paths never acquire "
            f"meaning from the current working directory.",
            file=sys.stderr,
        )
        return None
    try:
        return candidate.resolve()
    except OSError:
        return candidate.absolute()


def get_models_root() -> Path:
    """Return the user-selected model storage root.

    Precedence (see module section docstring):

    1. ``OFFLINE_AI_MODELS_ROOT`` env var (tests / explicit override) —
       absolute only; relative values are rejected.
    2. ``models.storage_root`` from settings.json (the canonical,
       user-configured location — installer/wizard write here).
    3. Legacy ``ai.models_dir`` (absolute) — its PARENT becomes the root
       so existing trees (``<root>/llm``) keep resolving correctly.
    4. Default suggestion: ``<user_data_root>/models`` (writable,
       platform-appropriate, NOT Program Files, NOT the install dir).

    The result is always absolute and never depends on the process CWD.
    """
    env_value = os.environ.get(MODELS_ROOT_ENV_VAR, "").strip()
    if env_value:
        resolved = _resolve_models_root_candidate(env_value)
        if resolved is not None:
            return resolved

    configured, from_canonical = _read_settings_models_root()
    if configured:
        # Legacy ai.models_dir pointed at the llm CATEGORY dir; the root is
        # its parent so category dirs continue to resolve underneath it.
        candidate = Path(configured)
        if not from_canonical and candidate.name == _LEGACY_MODELS_DIR_CATEGORY:
            candidate = candidate.parent
        resolved = _resolve_models_root_candidate(str(candidate))
        if resolved is not None:
            return resolved

    return get_models_dir()


def set_models_root(path: str | Path, config=None) -> Path:
    """Persist *path* as the model storage root and return it normalized.

    Writes the canonical ``models.storage_root`` key through the given
    ConfigManager-like *config* object (must expose ``set(key, value)``).
    The value must be absolute; relative paths raise ``ValueError`` —
    they are never CWD-resolved.  Also mirrors the legacy
    ``ai.models_dir`` to the llm category dir under the new root so older
    readers stay consistent during the transition.
    """
    candidate = Path(path)
    if not candidate.is_absolute():
        raise ValueError(
            f"models_root must be an absolute path; got relative {path!r}. "
            f"Relative model paths never acquire meaning from the current "
            f"working directory."
        )
    try:
        normalized = candidate.resolve()
    except OSError:
        normalized = candidate.absolute()

    if config is not None:
        config.set(MODELS_ROOT_CONFIG_KEY, str(normalized))
        config.set(LEGACY_MODELS_DIR_CONFIG_KEY, str(normalized / "llm"))
        # Keep the search-path list coherent with the new root.
        config.set("ai.model_search_paths", [str(normalized / "llm")])
    return normalized


def get_model_category_dir(category: str) -> Path:
    """Return the category directory under the configured models root.

    Categories (MODEL_CATEGORIES): ``llm``, ``embedding``, ``stt``.
    The stt resolver honours the historical ``voice/stt`` sublayout: when
    the legacy directory exists under the root it is returned so existing
    model folders keep resolving; otherwise the flat ``stt/`` layout is
    used.
    """
    if category not in MODEL_CATEGORIES:
        raise ValueError(
            f"Unknown model category {category!r}; expected one of {MODEL_CATEGORIES}"
        )
    root = get_models_root()
    if category == "stt":
        legacy = root / _STT_LEGACY_SUBPATH
        if legacy.exists():
            return legacy
        return root / "stt"
    return root / category


def ensure_model_dirs() -> list[Path]:
    """Create the model category directories under the models root.

    Explicit creation point (no import-time mkdir).  Returns the ensured
    directories.  Never creates anything under the application install
    directory or bundled resources — the root itself is user-selected.
    """
    root = get_models_root()
    dirs = [root]
    dirs.extend(get_model_category_dir(category) for category in MODEL_CATEGORIES)
    for path in dirs:
        path.mkdir(parents=True, exist_ok=True)
    return dirs


# Compatibility alias — the historical name for the llm category dir.
def get_llm_dir() -> Path:
    """Return the LLM category dir (compatibility alias)."""
    return get_model_category_dir("llm")


# --------------------------------------------------------------------------- #
# Public constants — API compatibility
# --------------------------------------------------------------------------- #
# These derive from the centralized user-data resolution above.  They are
# plain Paths captured at first import; the get_*() functions remain the
# dynamic accessors (they re-resolve on every call, honouring later
# environment changes in tests).  No directory is created at import time.

CONFIG_DIR: Path = get_config_dir()
DATA_DIR: Path = get_data_dir()
LOGS_DIR: Path = get_logs_dir()
MODELS_DIR: Path = get_models_dir()
LLM_DIR: Path = MODELS_DIR / "llm"
VOICE_DIR: Path = MODELS_DIR / "voice"
STT_DIR: Path = VOICE_DIR / "stt"
TTS_DIR: Path = VOICE_DIR / "tts"

SETTINGS_FILE = CONFIG_DIR / "settings.json"

# Backward-compatible alias for the previous module-level name.
USER_DATA_BASE = user_data_root()
