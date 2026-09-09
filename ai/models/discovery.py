"""Unified Local Model Discovery.

Discovers GGUF models from multiple local sources:

1. **Local GGUF files** — ordinary ``*.gguf`` files in user-selected folders
2. **Extensionless GGUF blobs** — files verified by magic bytes (``GGUF``) without ``.gguf`` extension
3. **Ollama storage** — resolves manifests and blobs from Ollama's blob/manifest
   directory structure **without** calling the Ollama HTTP API and **without**
   copying or renaming model files.
4. **LM Studio storage** — scans LM Studio's model cache directory for ``.gguf`` files.

The module produces :class:`ModelInfo` objects with full provenance metadata:
source type, architecture, parameter count, quantization, context length, etc.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ai.models.model_loader import (
    ModelInfo,
    ModelSource,
    _read_gguf_metadata,
    classify_model,
    infer_capabilities,
)
from core.logger import get_logger
from core.paths import get_model_category_dir

logger = get_logger("discovery")

_GGUF_MAGIC = b"GGUF"
_MODEL_LAYER_MEDIA_TYPE = "application/vnd.ollama.image.model"


def _default_llm_category_dir() -> Path:
    """LLM category dir under the configured models root (PHASE 3).

    Avoids a static import of core.paths.LLM_DIR (a module-import snapshot)
    so category resolution always honours the current models root.
    """
    return get_model_category_dir("llm")


def _is_within(path: Path, root: Path) -> bool:
    """True when the resolved *path* stays inside the resolved *root*.

    Security guard for recursive discovery: entries reached through
    symlink/junction directories that escape the scanned root are treated
    as outside and skipped, so a link inside the model tree cannot leak
    files from arbitrary locations into discovery results.
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _get_ollama_models_dir() -> Path | None:
    """Resolve the Ollama models directory from env or default location."""
    env_dir = os.environ.get("OLLAMA_MODELS")
    if env_dir:
        return Path(env_dir)
    if os.environ.get("OLLAMA_MODELS_DIR"):
        return Path(os.environ["OLLAMA_MODELS_DIR"])
    default = Path.home() / ".ollama" / "models"
    if default.exists():
        return default
    return None


def _get_lm_studio_models_dir() -> Path | None:
    """Resolve LM Studio's model cache directory."""
    candidates = [
        Path.home() / "AppData" / "Local" / "llama.cpp" / "models",
        Path.home() / "AppData" / "Roaming" / "llama-studio" / "models",
        Path.home() / ".lmstudio" / "models",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _is_valid_gguf(path: Path) -> bool:
    """Return True if *path* starts with the GGUF magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == _GGUF_MAGIC
    except OSError:
        return False


def _safe_stat(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def discover_local_gguf(directory: Path) -> list[ModelInfo]:
    """Discover ``.gguf`` files in *directory* (recursive).

    Security (PHASE 3): recursion never follows symlink/junction escapes —
    an entry whose resolved path leaves *directory* is skipped, so a link
    inside the model tree cannot pull in files from outside the scanned
    root.
    """
    models: list[ModelInfo] = []
    if not directory.exists():
        return models

    try:
        scan_root = directory.resolve(strict=False)
    except (OSError, RuntimeError):
        scan_root = directory.absolute()

    for entry in sorted(directory.rglob("*.gguf")):
        if not entry.is_file():
            continue
        try:
            resolved = entry.resolve(strict=False)
        except (OSError, RuntimeError):
            resolved = entry.absolute()
        if not _is_within(resolved, scan_root):
            logger.debug(
                "Skipping GGUF outside scanned root (symlink/junction escape): %s",
                entry,
            )
            continue
        size = _safe_stat(entry)
        if size == 0:
            continue
        metadata = _read_gguf_metadata(entry)
        architecture = ""
        if metadata:
            architecture = metadata.get("general.architecture", "")
        info = ModelInfo(
            name=entry.stem,
            path=entry,
            size_bytes=size,
            capabilities=infer_capabilities(entry.stem, architecture=architecture),
            source=ModelSource.LOCAL_GGUF,
            source_identifier=entry.stem,
            architecture=architecture,
            parameters=metadata.get("general.param_count", "") if metadata else "",
            quantization=metadata.get("general.file_type", "") if metadata else "",
            context_length=0,
            model_family=metadata.get("general.basename", "") if metadata else "",
            model_type=classify_model(entry.stem, entry, architecture, metadata or {}),
        )
        models.append(info)
        logger.debug("Discovered local GGUF: %s (%.1f MB)", entry.name, info.size_mb)

    return models


def discover_extensionless_gguf(
    directory: Path,
    exclude_suffixes: tuple[str, ...] = (".gguf",),
    exclude_paths: set[Path] | None = None,
) -> list[ModelInfo]:
    """Discover extensionless files that are valid GGUF (by magic bytes).

    Scans *directory* recursively for files whose suffix is not ``.gguf``
    and whose first 4 bytes are ``b"GGUF"``.

    *exclude_paths* is a set of resolved paths to skip (used to prevent
    Ollama blob files from being rediscovered as generic extensionless
    GGUF when Ollama manifest discovery already covers them).

    PHASE 7: incomplete downloader files (``*.part``) are always
    excluded — a partial download that happens to contain the GGUF
    magic bytes must never surface as a usable model.
    """
    models: list[ModelInfo] = []
    if not directory.exists():
        return models

    exclude_resolved: set[Path] = set()
    if exclude_paths:
        for p in exclude_paths:
            try:
                exclude_resolved.add(p.resolve())
            except OSError:
                exclude_resolved.add(p)

    for entry in sorted(directory.rglob("*")):
        if not entry.is_file():
            continue
        if entry.suffix.lower() in exclude_suffixes:
            continue
        # PHASE 7: never surface incomplete downloads as models.
        if entry.suffix.lower() == ".part":
            continue
        try:
            resolved = entry.resolve()
        except OSError:
            resolved = entry
        if resolved in exclude_resolved:
            continue
        # PHASE 3 security: never surface files reached through
        # symlink/junction escapes out of the scanned root.
        try:
            scan_root = directory.resolve(strict=False)
        except (OSError, RuntimeError):
            scan_root = directory.absolute()
        if not _is_within(resolved, scan_root):
            logger.debug(
                "Skipping extensionless GGUF outside scanned root: %s", entry
            )
            continue
        if not _is_valid_gguf(entry):
            continue
        size = _safe_stat(entry)
        if size == 0:
            continue
        metadata = _read_gguf_metadata(entry)
        architecture = ""
        if metadata:
            architecture = metadata.get("general.architecture", "")
        info = ModelInfo(
            name=entry.stem,
            path=entry,
            size_bytes=size,
            capabilities=infer_capabilities(entry.stem, architecture=architecture),
            source=ModelSource.EXTENSIONLESS,
            source_identifier=entry.stem,
            architecture=architecture,
            parameters=metadata.get("general.param_count", "") if metadata else "",
            quantization=metadata.get("general.file_type", "") if metadata else "",
            context_length=0,
            model_family=metadata.get("general.basename", "") if metadata else "",
            model_type=classify_model(entry.stem, entry, architecture, metadata or {}),
        )
        models.append(info)
        logger.debug("Discovered extensionless GGUF: %s (%.1f MB)", entry.name, info.size_mb)

    return models


def _discover_ollama_in_dir(ollama_dir: Path) -> tuple[list[ModelInfo], set[Path]]:
    """Discover models from a single Ollama models directory.

    Returns a tuple of ``(models, used_blob_paths)`` where
    ``used_blob_paths`` is the set of resolved blob file paths that belong
    to discovered Ollama models.  Callers use this to exclude those blobs
    from generic extensionless-GGUF discovery, preventing duplicate
    entries.
    """
    models: list[ModelInfo] = []
    used_blobs: set[Path] = set()

    blobs_dir = ollama_dir / "blobs"
    manifests_root = ollama_dir / "manifests"

    if not blobs_dir.exists() or not manifests_root.exists():
        logger.debug("Ollama dir missing blobs or manifests: %s", ollama_dir)
        return models, used_blobs

    seen_blobs: set[str] = set()

    for manifest_path in sorted(manifests_root.rglob("*")):
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Skipping invalid manifest %s: %s", manifest_path, exc)
            continue

        layers = manifest.get("layers", [])
        model_layer = None
        for layer in layers:
            if layer.get("media_type", "") == _MODEL_LAYER_MEDIA_TYPE:
                model_layer = layer
                break
            if layer.get("mediaType", "") == _MODEL_LAYER_MEDIA_TYPE:
                model_layer = layer
                break

        if model_layer is None:
            continue

        digest = model_layer.get("digest", "")
        layer_size = model_layer.get("size", 0)
        blob_name = _digest_to_blob_name(digest)
        blob_path = blobs_dir / blob_name

        if not blob_path.exists():
            logger.debug("Ollama blob not found: %s", blob_path)
            continue

        blob_hash = digest.replace("sha256:", "")
        if blob_hash in seen_blobs:
            logger.debug("Skipping duplicate Ollama blob: %s", blob_hash)
            continue
        seen_blobs.add(blob_hash)

        if not _is_valid_gguf(blob_path):
            logger.debug("Skipping non-GGUF Ollama blob: %s", blob_path)
            continue

        size = _safe_stat(blob_path)
        if size == 0:
            continue

        model_name = _manifest_to_model_name(manifest_path)
        config = _load_ollama_config(blobs_dir, manifest)

        # Read GGUF metadata from the blob for accurate classification
        blob_metadata = _read_gguf_metadata(blob_path)
        blob_arch = ""
        if blob_metadata:
            blob_arch = blob_metadata.get("general.architecture", "")
        arch = blob_arch or config.get("model_family", "")

        info = ModelInfo(
            name=model_name,
            path=blob_path,
            size_bytes=size if size else layer_size,
            capabilities=infer_capabilities(
                model_name,
                architecture=arch,
                model_family=config.get("model_family", ""),
            ),
            source=ModelSource.OLLAMA_STORAGE,
            source_identifier=model_name,
            architecture=arch,
            parameters=config.get("model_type", ""),
            quantization=config.get("file_type", ""),
            context_length=0,
            model_family=config.get("model_family", ""),
            model_type=classify_model(model_name, blob_path, arch, blob_metadata or {}),
        )
        models.append(info)
        used_blobs.add(blob_path)
        logger.info(
            "Discovered Ollama model: %s (%.1f MB, arch=%s, params=%s, quant=%s)",
            model_name, info.size_mb, info.architecture, info.parameters, info.quantization,
        )

    return models, used_blobs


def _digest_to_blob_name(digest: str) -> str:
    """Convert a digest like 'sha256:abcd...' to blob filename 'sha256-abcd...'."""
    if digest.startswith("sha256:"):
        return digest.replace("sha256:", "sha256-", 1)
    return digest


def _manifest_to_model_name(manifest_path: Path) -> str:
    """Convert manifest path to model name like 'qwen2.5-coder:7b'.

    Ollama manifest path structure:
        manifests/registry.ollama.ai/library/<repo>/<tag>
    """
    parts = manifest_path.parts
    try:
        library_idx = parts.index("library")
        repo = parts[library_idx + 1]
        tag = parts[library_idx + 2]
        return f"{repo}:{tag}"
    except (ValueError, IndexError):
        return manifest_path.stem


def _load_ollama_config(blobs_dir: Path, manifest: dict) -> dict[str, Any]:
    """Load and parse the Ollama config blob referenced in the manifest."""
    config = manifest.get("config", {})
    config_digest = config.get("digest", "")
    if not config_digest:
        return {}
    config_blob_name = _digest_to_blob_name(config_digest)
    config_path = blobs_dir / config_blob_name
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to read Ollama config blob %s: %s", config_path, exc)
        return {}


def discover_ollama_models(ollama_dir: Path | None = None) -> list[ModelInfo]:
    """Discover models from Ollama storage.

    Resolves the Ollama models directory from *ollama_dir* or the
    ``OLLAMA_MODELS`` / ``OLLAMA_MODELS_DIR`` env vars, then falls back
    to the default ``~/.ollama/models`` location.

    Does **not** call the Ollama HTTP API and does **not** copy or rename
    any files.
    """
    if ollama_dir is None:
        ollama_dir = _get_ollama_models_dir()
    if ollama_dir is None:
        return []
    models, _ = _discover_ollama_in_dir(ollama_dir)
    return models


def discover_lm_studio_models(lm_studio_dir: Path | None = None) -> list[ModelInfo]:
    """Discover models from LM Studio's storage."""
    if lm_studio_dir is None:
        lm_studio_dir = _get_lm_studio_models_dir()
    if lm_studio_dir is None:
        return []
    models = discover_local_gguf(lm_studio_dir)
    for m in models:
        m.source = ModelSource.LM_STUDIO
        m.source_identifier = f"lm-studio:{m.name}"
    return models


def discover_all_models(
    search_paths: list[Path] | None = None,
    include_ollama: bool = True,
    include_lm_studio: bool = True,
    ollama_models_dir: Path | None = None,
) -> list[ModelInfo]:
    """Discover all local models from all known sources.

    Parameters
    ----------
    search_paths
        Additional directories to scan for ``.gguf`` and extensionless-
        GGUF files.  Defaults to ``[LLM_DIR]``.
    include_ollama
        If ``True``, scan Ollama storage.
    include_lm_studio
        If ``True``, scan LM Studio storage.
    ollama_models_dir
        Explicit Ollama models directory.  Overrides env-var and
        default resolution.  When provided, it is also used to exclude
        Ollama blob files from generic extensionless-GGUF discovery.

    Returns a list of :class:`ModelInfo` objects, deduplicated by resolved
    file path.  Sorted by model name.
    """
    if search_paths is None:
        search_paths = [_default_llm_category_dir()]

    models: list[ModelInfo] = []
    seen_paths: set[Path] = set()
    ollama_blob_paths: set[Path] = set()

    # Run Ollama discovery first so we know which blob paths to exclude
    # from the generic extensionless-GGUF scan (prevents double-discovery).
    if include_ollama:
        resolved_ollama_dir = ollama_models_dir
        if resolved_ollama_dir is None:
            resolved_ollama_dir = _get_ollama_models_dir()
        if resolved_ollama_dir is not None:
            ollama_models, ollama_blob_paths = _discover_ollama_in_dir(resolved_ollama_dir)
            for info in ollama_models:
                resolved = info.path.resolve()
                if resolved not in seen_paths:
                    seen_paths.add(resolved)
                    models.append(info)

    for d in search_paths:
        if not d.exists():
            continue
        for info in discover_local_gguf(d):
            resolved = info.path.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                models.append(info)
        for info in discover_extensionless_gguf(d, exclude_paths=ollama_blob_paths):
            resolved = info.path.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                models.append(info)

    if include_lm_studio:
        for info in discover_lm_studio_models():
            resolved = info.path.resolve()
            if resolved not in seen_paths:
                seen_paths.add(resolved)
                models.append(info)

    models.sort(key=lambda m: m.name)
    logger.info("Total models discovered: %d", len(models))
    return models
