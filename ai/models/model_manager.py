"""Model Manager — discovers, selects, and loads local AI models.

The manager keeps track of which model is *active* and provides the
appropriate :class:`ModelLoader` for the currently active model.  When
no real backend (``llama-cpp-python``) or model file is available it
falls back to :class:`StubModelLoader` so the application still runs.
"""

from __future__ import annotations

import os
from pathlib import Path

from ai.models.discovery import discover_all_models
from ai.models.model_loader import (
    GGUFModelLoader,
    ModelInfo,
    ModelLoader,
    ModelSource,
    ModelType,
    StubModelLoader,
    get_gpu_vram_bytes,
    has_llama_cpp,
    is_gpu_available,
    pick_default_model,
)
from core.exceptions import ModelError
from core.logger import get_logger

logger = get_logger("model_manager")


def _validate_chat_model(model: ModelInfo, test_mode: bool) -> str | None:
    """Validate that *model* is suitable for text-generation chat.

    Returns ``None`` if the model is valid, or an error message string
    explaining why it cannot be activated as a chat/LLM model.
    """
    if model.model_type == ModelType.UNKNOWN:
        if test_mode:
            logger.warning(
                "TEST_MODE: model '%s' has UNKNOWN type — assuming LLM for testing",
                model.name,
            )
            return None
        return (
            f"Model '{model.name}' could not be classified. "
            f"Unable to determine if it is a text-generation model."
        )
    if not model.model_type.is_chat_compatible:
        return (
            f"Model '{model.name}' is a {model.model_type.display_name} "
            f"and cannot be used for text generation. "
            f"Only LLM and Vision LLM models are supported."
        )
    return None


def _is_test_mode() -> bool:
    """Return True if the application is running in test mode."""
    return os.environ.get("OFFLINE_AI_TEST_MODE", "") == "1"


def _find_mmproj_for(model: ModelInfo) -> Path | None:
    """Locate a vision projector (mmproj*.gguf) next to a vision model.

    Searches the model's own directory (and its parent for blob-style
    stores) for files starting with ``mmproj``.  Returns ``None`` for
    non-vision models or when no projector file is found — the model
    then runs text-only.
    """
    if not (model.capabilities.vision or model.model_type == ModelType.VISION_LLM):
        return None
    try:
        candidates: list[Path] = []
        model_dir = model.path.parent
        candidates.append(model_dir)
        if model_dir.parent != model_dir:
            candidates.append(model_dir.parent)
        seen: set[Path] = set()
        for directory in candidates:
            if directory in seen or not directory.is_dir():
                continue
            seen.add(directory)
            for entry in sorted(directory.glob("*.gguf")):
                if entry.name.lower().startswith("mmproj"):
                    return entry
    except OSError:
        return None
    return None


class ModelManager:
    """High-level manager over local model files and their loader.

    Discovers models from multiple local sources via the unified
    :mod:`ai.models.discovery` layer (local GGUF, extensionless GGUF,
    Ollama storage, LM Studio).
    """

    def __init__(
        self,
        models_dir: Path | None = None,
        search_paths: list[Path] | None = None,
        ollama_models_dir: Path | None = None,
        include_ollama: bool = True,
        include_lm_studio: bool = True,
        n_threads: int = 4,
        n_gpu_layers: int = 0,
        n_ctx: int = 4096,
        auto_gpu_layers: bool = False,
        gpu_mode: str = "auto",
    ) -> None:
        # PHASE 3: the default models dir is the llm category dir under the
        # configured (user-selected) models root — never a static snapshot
        # and never CWD/developer-machine dependent.
        if models_dir is None:
            from core.paths import get_model_category_dir

            models_dir = get_model_category_dir("llm")
        self.models_dir = models_dir
        # Build search paths: include models_dir plus any configured search_paths,
        # deduplicated. This ensures the configured models_dir is always scanned
        # even when search_paths is explicitly provided and differs from models_dir.
        all_paths: list[Path] = []
        if models_dir is not None:
            all_paths.append(models_dir)
        for p in (search_paths or []):
            if p not in all_paths:
                all_paths.append(p)
        self._search_paths = all_paths if all_paths else [models_dir]
        self._ollama_models_dir: Path | None = ollama_models_dir
        self._include_ollama = include_ollama
        self._include_lm_studio = include_lm_studio
        self._n_threads = n_threads
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._auto_gpu_layers = auto_gpu_layers
        self._gpu_mode = gpu_mode
        self._models: list[ModelInfo] = []
        self._active_model: ModelInfo | None = None
        self._loader: ModelLoader | None = None
        self._load_error: str | None = None
        # H4 discovery cache (see rescan()): inputs signature + shallow
        # directory fingerprint + cached result.
        self._last_scan_signature: tuple | None = None
        self._last_scan_fingerprint: tuple | None = None
        self._last_scan_models: list[ModelInfo] | None = None
        self._scan()

    def set_models_dir(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._search_paths = [models_dir]
        self._scan()

    def set_search_paths(self, search_paths: list[Path]) -> None:
        """Set the list of directories to scan for local GGUF files."""
        self._search_paths = list(search_paths)
        self._scan()

    def set_ollama_models_dir(self, ollama_dir: Path | None) -> None:
        """Override the Ollama storage directory (useful for testing)."""
        self._ollama_models_dir = ollama_dir
        self._scan()

    def set_discovery_options(
        self,
        include_ollama: bool | None = None,
        include_lm_studio: bool | None = None,
    ) -> None:
        """Enable or disable discovery of external model stores."""
        if include_ollama is not None:
            self._include_ollama = include_ollama
        if include_lm_studio is not None:
            self._include_lm_studio = include_lm_studio
        self._scan()

    # ------------------------------------------------------------------ #
    def _scan(self) -> None:
        self._models = discover_all_models(
            search_paths=self._search_paths,
            include_ollama=self._include_ollama,
            include_lm_studio=self._include_lm_studio,
            ollama_models_dir=self._ollama_models_dir,
        )
        for m in self._models:
            m.active = False
        # H4: remember the scan inputs AND a cheap directory fingerprint so
        # unchanged repeat scans (Models page navigation, refresh clicks)
        # reuse this result instead of re-walking every directory on the
        # caller's (GUI) thread.
        self._last_scan_signature = self._scan_signature()
        self._last_scan_fingerprint = self._dir_fingerprint()
        self._last_scan_models = [m for m in self._models]
        logger.info("Scanned %d search path(s) — found %d model(s)",
                     len(self._search_paths), len(self._models))

    def _scan_signature(self) -> tuple:
        """Fingerprint of the scan INPUT configuration.

        Any change (paths, options, Ollama dir) produces a different
        signature, forcing a real rescan.
        """
        return (
            tuple(str(p) for p in self._search_paths),
            bool(self._include_ollama),
            bool(self._include_lm_studio),
            str(self._ollama_models_dir) if self._ollama_models_dir else "",
        )

    def _dir_fingerprint(self) -> tuple:
        """Cheap directory fingerprint: one SHALLOW ``os.scandir`` of each
        search path — names, file counts, and mtimes only.

        This costs microseconds even for huge model roots (no recursion,
        no file opens, no GGUF header parsing), unlike the full
        discovery walk.  Used by :meth:`rescan` to detect real changes
        (added/removed/renamed model files) so the expensive recursive
        discovery only runs when something actually changed.
        """
        parts: list = []
        for path in self._search_paths:
            try:
                entries = sorted(os.scandir(path), key=lambda e: e.name)
                parts.append(
                    (
                        str(path),
                        tuple(
                            (e.name, int(e.stat(follow_symlinks=False).st_mtime))
                            for e in entries
                        ),
                    )
                )
            except OSError:
                parts.append((str(path), ()))
        if self._include_ollama:
            odir = self._ollama_models_dir
            try:
                if odir is None:
                    from ai.models.discovery import _get_ollama_models_dir

                    odir = _get_ollama_models_dir()
                if odir is not None:
                    entries = sorted(os.scandir(odir), key=lambda e: e.name)
                    parts.append(
                        (
                            str(odir),
                            tuple(
                                (e.name, int(e.stat(follow_symlinks=False).st_mtime))
                                for e in entries
                            ),
                        )
                    )
            except OSError:
                pass
        return tuple(parts)

    def rescan(self) -> list[ModelInfo]:
        """Re-scan the models directory (call after adding/removing models).

        H4: the expensive recursive discovery (opens files, parses GGUF
        headers, walks Ollama/LM Studio trees) runs ONLY when the scan
        inputs changed OR the cheap shallow directory fingerprint shows
        the contents changed (file added/removed/renamed/mtime bumped).
        Otherwise the cached result is returned — Models-page navigation
        no longer re-walks every directory on the GUI thread.
        ``rescan_force()`` (the Refresh button) always rescans for real.
        """
        if (
            self._last_scan_models is not None
            and self._scan_signature() == self._last_scan_signature
            and self._dir_fingerprint() == self._last_scan_fingerprint
        ):
            logger.debug("Discovery cache hit — reusing %d model(s)",
                         len(self._last_scan_models))
            return list(self._last_scan_models)
        self._scan()
        return list(self._models)

    def rescan_force(self) -> list[ModelInfo]:
        """Force a full filesystem rescan, bypassing the discovery cache."""
        self._scan()
        return list(self._models)

    def list_models(self) -> list[ModelInfo]:
        """Return all discovered models (a copy)."""
        return list(self._models)

    def get_active_model(self) -> ModelInfo | None:
        return self._active_model

    def get_loader(self) -> ModelLoader:
        """Return the currently active loader (stub if none loaded)."""
        if self._loader is not None:
            return self._loader
        if _is_test_mode():
            logger.warning("No model loaded — returning StubModelLoader (TEST MODE)")
            self._loader = StubModelLoader()
            return self._loader
        logger.error("No model loaded — no loader available")
        raise ModelError(
            "GGUF inference runtime is unavailable. "
            "Select a model and ensure llama-cpp-python is installed."
        )

    def get_loader_for_model(self, name: str) -> ModelLoader:
        """Return a loader for *name* **without** changing the active model.

        This enables per-agent model resolution without mutating global Chat
        state.  Raises :class:`ModelError` if the model is not found, is not
        chat-compatible, or cannot be loaded.
        """
        model = self._find(name)
        if model is None:
            raise ModelError(f"Model '{name}' not found in {self.models_dir}")

        # Validate model type before attempting to load
        type_error = _validate_chat_model(model, _is_test_mode())
        if type_error is not None:
            raise ModelError(type_error)

        if not has_llama_cpp():
            if _is_test_mode():
                logger.warning(
                    "TEST_MODE: llama-cpp-python is not installed — "
                    "using stub loader for '%s'", model.name,
                )
                loader: ModelLoader = StubModelLoader()
                loader.load(model.path)
                return loader
            raise ModelError(
                f"llama-cpp-python is not installed. "
                f"Cannot load GGUF model '{model.name}'."
            )
        loader = GGUFModelLoader(
            n_threads=self._n_threads,
            n_gpu_layers=self._n_gpu_layers,
            n_ctx=self._n_ctx,
            auto_gpu_layers=self._auto_gpu_layers,
            mmproj_path=_find_mmproj_for(model),
            gpu_mode=self._gpu_mode,
        )
        try:
            loader.load(model.path)
        except Exception as exc:
            raise ModelError(
                f"Model '{model.name}' detected, but it could not be loaded. "
                f"Technical details: {exc}"
            ) from exc
        return loader

    # ------------------------------------------------------------------ #
    def select_default(self) -> ModelInfo | None:
        """Select the smallest model automatically, or fall back to stub.

        Raises ModelError if the runtime is unavailable and not in TEST_MODE.
        """
        default = pick_default_model(self._models)
        if default is None:
            if _is_test_mode():
                logger.warning("No .gguf models found — using stub loader (TEST MODE)")
                self._loader = StubModelLoader()
                self._loader.load(Path("stub"))
                return None
            logger.error("No .gguf models found in %s", self.models_dir)
            raise ModelError(
                f"No GGUF models found in {self.models_dir}. "
                "Place a .gguf model file in the models folder."
            )
        return self.activate_model(default.name)

    def activate_model(self, name: str) -> ModelInfo:
        """Load *name* by filename stem and make it active.

        Raises ModelError if the model is not chat-compatible (embedding,
        projector, diffusion, auxiliary) or if llama-cpp-python is unavailable
        and not in TEST_MODE — never silently falls back to a fake/stub response.

        If a different model is already active, the request is rejected before
        any loader is created or replaced — the existing model remains intact.
        """
        model = self._find(name)
        if model is None:
            raise ModelError(f"Model '{name}' not found in {self.models_dir}")

        # Reject if a different model is already active — do NOT destroy or
        # replace the existing loader. The user must explicitly Unload first.
        if self._active_model is not None and self._active_model.name != model.name:
            raise ModelError(
                f"Model '{model.name}' cannot be activated. "
                f"Model '{self._active_model.name}' is already active. "
                f"Unload the active model first before activating a different model."
            )

        # Validate model type before attempting to load — rejects embedding,
        # projector, diffusion, and auxiliary models early.
        type_error = _validate_chat_model(model, _is_test_mode())
        if type_error is not None:
            self._load_error = type_error
            raise ModelError(type_error)

        if not has_llama_cpp():
            if _is_test_mode():
                logger.warning(
                    "TEST_MODE: llama-cpp-python is not installed — using stub loader for '%s'",
                    model.name,
                )
                old_loader = self._loader
                self._loader = StubModelLoader()
                try:
                    self._loader.load(model.path)
                except Exception as exc:
                    self._loader.unload()
                    self._loader = old_loader
                    self._load_error = str(exc)
                    raise ModelError(
                        f"Model '{model.name}' detected, but it could not be loaded. "
                        f"Technical details: {exc}"
                    ) from exc
                if old_loader is not None:
                    old_loader.unload()
                self._load_error = "llama-cpp-python not installed (TEST_MODE stub)"
            else:
                self._load_error = (
                    f"llama-cpp-python is not installed. "
                    f"Cannot load GGUF model '{model.name}'."
                )
                raise ModelError(self._load_error)
        else:
            old_loader = self._loader
            mmproj = _find_mmproj_for(model)
            if mmproj is not None:
                logger.info("Vision projector detected for '%s': %s", model.name, mmproj.name)
            self._loader = GGUFModelLoader(
                n_threads=self._n_threads,
                n_gpu_layers=self._n_gpu_layers,
                n_ctx=self._n_ctx,
                auto_gpu_layers=self._auto_gpu_layers,
                mmproj_path=mmproj,
                gpu_mode=self._gpu_mode,
            )
            try:
                self._loader.load(model.path)
            except Exception as exc:
                self._loader.unload()
                self._loader = old_loader
                self._load_error = str(exc)
                raise ModelError(
                    f"Model '{model.name}' detected, but it could not be loaded. "
                    f"Technical details: {exc}"
                ) from exc
            if old_loader is not None:
                old_loader.unload()
            self._load_error = None

        self._set_active(model)
        return model

    def activate_stub(self) -> None:
        """Force the stub loader (no real model)."""
        if not _is_test_mode():
            logger.warning("activate_stub called outside TEST_MODE — stub will not generate real responses")
        logger.info("Activating stub loader (no real model)")
        self._loader = StubModelLoader()
        self._loader.load(Path("stub"))
        self._active_model = None
        self._load_error = None

    def unload(self) -> None:
        if self._loader is not None:
            self._loader.unload()
        self._loader = None
        self._load_error = None
        if self._active_model is not None:
            self._active_model.active = False
            self._active_model = None
        logger.info("Model unloaded")

    # ------------------------------------------------------------------ #
    def download_model(
        self,
        url: str,
        filename: str,
        expected_checksum: str | None = None,
        downloader_factory=None,
    ) -> ModelInfo:
        """Download a model file and add it to the model list.

        *downloader_factory* (optional) lets the caller — typically the
        UI download worker — construct the downloader so it can hold a
        live reference for cooperative cancellation while this method
        keeps its orchestration (scan + find).  It receives the same
        keyword arguments this method would pass; omitting it preserves
        the previous behavior exactly.
        """
        try:
            from installer.downloader import ModelDownloader
        except ImportError as exc:
            raise ImportError("Installer module not available") from exc

        self.models_dir.mkdir(parents=True, exist_ok=True)
        if downloader_factory is not None:
            downloader = downloader_factory(dest_dir=self.models_dir)
        else:
            downloader = ModelDownloader(dest_dir=self.models_dir)
        result = downloader.download(url, filename, expected_checksum)

        if not result.success:
            raise ModelError(f"Download failed: {result.error}")

        self._scan()
        model = self._find(filename)
        if model is None:
            stem = Path(filename).stem
            model = self._find(stem)
        if model is None:
            raise ModelError(f"Downloaded model not found: {filename}")

        logger.info("Model downloaded and ready: %s", model.name)
        return model

    def delete_model(self, name: str) -> bool:
        """Delete a model file from disk."""
        model = self._find(name)
        if model is None:
            return False
        try:
            model.path.unlink()
            self._scan()
            if self._active_model is not None and self._active_model.path == model.path:
                self.activate_stub()
            logger.info("Model deleted: %s", model.name)
            return True
        except OSError as exc:
            logger.error("Failed to delete model %s: %s", model.name, exc)
            return False

    # ------------------------------------------------------------------ #
    def _find(self, name: str) -> ModelInfo | None:
        stem = name
        if not stem.endswith(".gguf"):
            stem = name
        for m in self._models:
            if (m.path.stem == stem
                    or m.path.name == stem
                    or m.name == stem
                    or m.source_identifier == stem):
                return m
            if m.source == ModelSource.OLLAMA_STORAGE and m.name == stem:
                return m
        return None

    def _set_active(self, model: ModelInfo) -> None:
        if self._active_model is not None:
            self._active_model.active = False
        model.active = True
        self._active_model = model

    @property
    def is_ready(self) -> bool:
        return self._active_model is not None and self._loader is not None

    @property
    def runtime_available(self) -> bool:
        """True if llama-cpp-python is importable."""
        return has_llama_cpp()

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def gpu_available(self) -> bool:
        """True if NVIDIA GPU is detected via pynvml."""
        return is_gpu_available()

    @property
    def gpu_vram_bytes(self) -> int:
        """Total VRAM in bytes for GPU index 0, or 0 if unavailable."""
        return get_gpu_vram_bytes()

    @property
    def active_gpu_layers(self) -> int:
        """Number of GPU layers the active loader is using, or 0."""
        if isinstance(self._loader, GGUFModelLoader):
            return self._loader.n_gpu_layers
        return 0
