"""Model loading abstractions.

Defines the :class:`ModelLoader` interface, :class:`ModelInfo` metadata,
:class:`ModelSource` for tracking provenance, and a concrete
:class:`GGUFModelLoader` that uses ``llama-cpp-python`` to load GGUF models
through the llama.cpp backend.

A :class:`StubModelLoader` is provided for environments where no LLM
library or model is available — it returns canned responses so the
application remains functional in CI / demo mode (TEST_MODE only).
"""

from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ai.models.gpu_runtime import (
    GPU_LAYER_MAGIC_FULL,
    apply_cuda_dll_discovery,
    decide_gpu_layers,
    detect_gpu_capabilities,
)
from ai.models.performance import InferenceMetrics, PerformanceProfiler
from core.logger import get_logger
from core.paths import get_model_category_dir

logger = get_logger("model_loader")
_profiler = PerformanceProfiler()


class ModelStatus(Enum):
    """Model availability states for user display."""

    MODEL_AVAILABLE = "model_available"
    NO_MODEL_AVAILABLE = "no_model_available"
    STUB_MODE = "stub_mode"
    RUNTIME_UNAVAILABLE = "runtime_unavailable"
    LOAD_FAILED = "load_failed"
    LOADING = "loading"

    @property
    def description(self) -> str:
        if self == ModelStatus.MODEL_AVAILABLE:
            return "AI model ready"
        if self == ModelStatus.NO_MODEL_AVAILABLE:
            return "No local model found"
        if self == ModelStatus.STUB_MODE:
            return "Limited mode (stub active)"
        if self == ModelStatus.RUNTIME_UNAVAILABLE:
            return "GGUF inference runtime is unavailable"
        if self == ModelStatus.LOAD_FAILED:
            return "Model detected, but it could not be loaded"
        if self == ModelStatus.LOADING:
            return "Loading model..."
        return "Unknown"


def get_model_status(models: list, has_backend: bool) -> ModelStatus:
    """Determine the current model availability state."""
    if not has_backend:
        if models:
            return ModelStatus.RUNTIME_UNAVAILABLE
        return ModelStatus.NO_MODEL_AVAILABLE
    if not models:
        return ModelStatus.NO_MODEL_AVAILABLE
    return ModelStatus.MODEL_AVAILABLE


@dataclass
class ModelCapabilities:
    """Technical capabilities of a model.

    All capabilities default to False (unknown/unavailable) for safety.
    When capability cannot be determined, it remains False (safe default).
    """

    text_generation: bool = False
    streaming: bool = False
    vision: bool = False
    tool_calling: bool = False
    function_calling: bool = False
    structured_output: bool = False
    json_output: bool = False
    reasoning: bool = False
    code_generation: bool = False
    embeddings: bool = False
    multimodal: bool = False
    long_context: bool = False

    def is_compatible_with(self, required_capabilities: list[str]) -> bool:
        """Check if model supports all required capabilities."""
        for cap in required_capabilities:
            if not getattr(self, cap, False):
                return False
        return True

    def to_dict(self) -> dict[str, bool]:
        """Export capabilities as dictionary."""
        return {f: getattr(self, f) for f in [
            "text_generation", "streaming", "vision", "tool_calling",
            "function_calling", "structured_output", "json_output",
            "reasoning", "code_generation", "embeddings", "multimodal", "long_context"
        ]}


class ModelSource(Enum):
    """Where a model was discovered from."""

    LOCAL_GGUF = "local_gguf"
    EXTENSIONLESS = "extensionless"
    OLLAMA_STORAGE = "ollama_storage"
    LM_STUDIO = "lm_studio"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        if self == ModelSource.LOCAL_GGUF:
            return "Local GGUF"
        if self == ModelSource.EXTENSIONLESS:
            return "Local GGUF (extensionless)"
        if self == ModelSource.OLLAMA_STORAGE:
            return "Ollama Storage"
        if self == ModelSource.LM_STUDIO:
            return "LM Studio"
        return "Unknown"


class ModelType(Enum):
    """Functional type of a model, used to determine runtime suitability."""

    LLM = "llm"
    VISION_LLM = "vision_llm"
    EMBEDDING = "embedding"
    PROJECTOR = "projector"
    DIFFUSION = "diffusion"
    AUXILIARY = "auxiliary"
    UNKNOWN = "unknown"

    @property
    def display_name(self) -> str:
        names = {
            ModelType.LLM: "LLM",
            ModelType.VISION_LLM: "Vision LLM",
            ModelType.EMBEDDING: "Embedding",
            ModelType.PROJECTOR: "Vision Projector",
            ModelType.DIFFUSION: "Diffusion",
            ModelType.AUXILIARY: "Auxiliary",
            ModelType.UNKNOWN: "Unknown",
        }
        return names.get(self, "Unknown")

    @property
    def is_chat_compatible(self) -> bool:
        """True if this model type is a valid text-generation LLM."""
        return self in (ModelType.LLM, ModelType.VISION_LLM)


@dataclass
class ModelInfo:
    """Metadata about a local AI model on disk."""

    name: str
    path: Path
    size_bytes: int
    model_format: str = "gguf"
    active: bool = False
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    load_time_seconds: float = 0.0
    last_inference_metrics: InferenceMetrics | None = None
    source: ModelSource = ModelSource.LOCAL_GGUF
    source_identifier: str = ""
    architecture: str = ""
    parameters: str = ""
    quantization: str = ""
    context_length: int = 0
    model_family: str = ""
    model_type: ModelType = ModelType.UNKNOWN

    @property
    def size_mb(self) -> float:
        return round(self.size_bytes / (1024 * 1024), 1)

    @property
    def size_human(self) -> str:
        if self.size_bytes >= 1024**3:
            return f"{self.size_bytes / (1024**3):.1f} GB"
        return f"{self.size_mb:.0f} MB"


class ModelLoader(ABC):
    """Abstract interface for loading and running an LLM."""

    is_stub: bool = False

    @abstractmethod
    def load(self, path: Path) -> None:
        """Load the model from *path* into memory."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        """Generate a complete response for *prompt* (blocking)."""

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        """Yield response tokens as an iterator (for streaming UI)."""

    @abstractmethod
    def generate_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        """Generate a full response from chat ``messages``.

        Implementations MUST apply the model's native chat template
        (via llama.cpp ``create_chat_completion`` / GGUF
        ``tokenizer.chat_template``) rather than a hand-built transcript.
        """

    @abstractmethod
    def generate_chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        """Stream response tokens from chat ``messages`` (native template)."""

    @abstractmethod
    def count_tokens(self, messages: list[dict[str, str]]) -> int:
        """Return the number of tokens that would be used for generation.

        Uses the model's tokenizer to count tokens exactly. This is used for
        prompt truncation to ensure we stay within the model's context window.
        """

    @abstractmethod
    def unload(self) -> None:
        """Free model memory."""


class StubModelLoader(ModelLoader):
    """Fallback loader that emits canned responses.

    Used only when ``OFFLINE_AI_TEST_MODE=1`` is set in the environment.
    In production, a real loader (``GGUFModelLoader``) must be available.
    """

    is_stub: bool = True

    def __init__(self) -> None:
        self._loaded = False
        self._load_error: str | None = None
        logger.info("StubModelLoader active — using placeholder responses (TEST MODE only)")

    def load(self, path: Path) -> None:
        self._loaded = True
        self._load_error = None
        logger.info("Stub model loaded (path=%s) — no real LLM (TEST MODE only)", path)

    def generate(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.7,
        top_p: float = 0.9, top_k: int = 40, min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        return (
            "This is a placeholder response because no AI model is loaded. "
            "Install a .gguf model in the models/llm/ folder to get "
            "a real answer. (StubModelLoader — PHASE 3 fallback)"
        )

    def generate_stream(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.7,
        top_p: float = 0.9, top_k: int = 40, min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        response = self.generate(prompt, max_tokens=max_tokens, temperature=temperature)
        yield response

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        return self.generate(" ", max_tokens=max_tokens, temperature=temperature)

    def generate_chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        yield self.generate_chat(messages, max_tokens, temperature)

    def count_tokens(self, messages: list[dict[str, str]]) -> int:
        """Return estimated token count for stub loader.

        Uses a character-based estimate since no model is loaded.
        """
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return total_chars // 4

    def unload(self) -> None:
        self._loaded = False

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def status(self) -> ModelStatus:
        if self._loaded:
            return ModelStatus.STUB_MODE
        return ModelStatus.NO_MODEL_AVAILABLE


def is_gpu_available() -> bool:
    """Return True if llama-cpp-python with CUDA/GPU offload backend is available.

    Delegates to the centralized PHASE 4 runtime (:mod:`ai.models.gpu_runtime`).
    """
    return detect_gpu_capabilities().offload_supported


def get_gpu_vram_bytes() -> int:
    """Return total VRAM in bytes for GPU index 0, or 0 if unavailable."""
    return detect_gpu_capabilities().vram_bytes


def detect_optimal_gpu_layers() -> int:
    """Legacy compatibility shim — full offload when a capable GPU exists.

    .. deprecated:: PHASE 4
        Universal full offload is unsafe for models larger than VRAM.
        :func:`ai.models.gpu_runtime.decide_gpu_layers` is the model-aware
        replacement; this shim is retained only for API compatibility and
        is used by nothing in the production load path.
    """
    if not is_gpu_available():
        logger.info("No GPU offload — CPU mode (n_gpu_layers=0)")
        return 0
    logger.warning(
        "detect_optimal_gpu_layers is deprecated (universal full offload); "
        "use ai.models.gpu_runtime.decide_gpu_layers for model-aware strategy"
    )
    return GPU_LAYER_MAGIC_FULL


def can_fit_model_on_gpu(model_size_bytes: int) -> bool:
    """Return True if the model fits in GPU VRAM with headroom.

    Uses the conservative PHASE 4 estimator (overhead factor + KV cache
    allowance + VRAM reserve).
    """
    from ai.models.gpu_runtime import estimate_model_vram_bytes

    caps = detect_gpu_capabilities()
    if not caps.vram_known:
        return False
    from ai.models.gpu_runtime import _VRAM_RESERVE_FRACTION

    safe_budget = int(caps.vram_bytes * (1.0 - _VRAM_RESERVE_FRACTION))
    # Legacy callers have no n_ctx; assume a mid-range context.
    return estimate_model_vram_bytes(model_size_bytes, 4096) <= safe_budget


def _looks_like_gpu_failure(exc: BaseException) -> bool:
    """Heuristic: does *exc* look like a GPU/CUDA allocation failure?

    Used only to decide whether a CPU retry is worthwhile — never to
    swallow the error (the retry re-raises on failure).
    """
    text = str(exc).lower()
    markers = (
        "cuda",
        "ggml-cuda",
        "vram",
        "out of memory",
        "cudaerror",
        "devicememory",
        "insufficient memory",
        "cublas",
    )
    return any(marker in text for marker in markers)


def _extract_streaming_text(chunk: dict[str, Any]) -> str:
    """Extract text from a streaming chunk (supports multiple backends).

    Supports:
    - llama-cpp-python 0.3.34:  ``{"choices": [{"text": "..."}]}``
    - OpenAI delta format:      ``{"choices": [{"delta": {"text": "..."}}]}``

    Returns an empty string if no text is found or the chunk structure is
    unexpected.
    """
    choices = chunk.get("choices")
    if not choices or not isinstance(choices, list):
        return ""
    choice = choices[0]
    if not isinstance(choice, dict):
        return ""
    delta = choice.get("delta")
    if isinstance(delta, dict):
        return delta.get("text", "") or ""
    return choice.get("text", "") or ""


class GGUFModelLoader(ModelLoader):
    """Concrete loader using llama-cpp-python (llama.cpp backend).

    Loads GGUF model files via the ``Llama`` class from ``llama_cpp``.
    Supports CPU inference by default; GPU acceleration is controlled
    via ``n_gpu_layers`` (offload layers to GPU when the backend
    supports it, e.g. via CUDA/Metal/Vulkan build of llama.cpp).

    When ``n_gpu_layers`` is set to ``Auto`` (or omitted on an AutoConfig),
    the loader attempts to auto-detect the optimal GPU layer count based
    on the model file size and available GPU VRAM.

    Vision: multimodal (vision) models need a companion ``mmproj*.gguf``
    clip projector.  Pass ``mmproj_path`` (auto-detected by
    :class:`ModelManager` for vision-capable models) to enable image
    understanding.
    """

    is_stub: bool = False

    def __init__(
        self,
        n_threads: int = 4,
        n_gpu_layers: int = 0,
        n_ctx: int = 4096,
        auto_gpu_layers: bool = False,
        mmproj_path: Path | None = None,
        gpu_mode: str = "auto",
    ) -> None:
        self.n_threads = n_threads
        self.n_ctx = n_ctx
        self._auto_gpu = auto_gpu_layers
        self._gpu_mode = gpu_mode
        self._mmproj_path = mmproj_path
        self._vision_enabled = mmproj_path is not None
        self._model: Any = None
        self._model_path: Path | None = None
        self._load_error: str | None = None
        # PHASE 4 GPU configuration semantics (backward compatible):
        #   * auto_gpu_layers=True  → centralized model-aware strategy
        #     (manual non-zero n_gpu_layers still wins as expert override).
        #   * auto_gpu_layers=False + n_gpu_layers==0 → static CPU mode
        #     (the historical default; nothing automatic happens).
        #   * auto_gpu_layers=False + n_gpu_layers>0  → expert manual mode.
        if auto_gpu_layers:
            self._manual_gpu_layers: int | None = (
                n_gpu_layers if n_gpu_layers > 0 else None
            )
            self._auto_decide = True
        else:
            self._manual_gpu_layers = n_gpu_layers if n_gpu_layers > 0 else None
            self._auto_decide = n_gpu_layers > 0
        # Resolved per-model at load() time (needs the file size + ctx).
        self.n_gpu_layers = n_gpu_layers
        self._gpu_reason: str = ""

    @property
    def vision_enabled(self) -> bool:
        """True when a vision projector is attached and usable."""
        return self._vision_enabled

    def _attach_vision_projector(self) -> None:
        """Attach the mmproj clip projector to the loaded model.

        Tries the modern ``libmtmd`` path first (llama-cpp-python >= 0.3.x
        accepts ``mmproj`` at load time via the ``Llama`` constructor —
        handled in :meth:`load``) and falls back to the legacy
        ``Llava15ChatHandler`` for older versions.  When neither works the
        model still runs text-only.
        """
        if self._model is None or self._mmproj_path is None:
            return
        # Modern path: constructor kwarg handled in load(); nothing to do.
        if getattr(self._model, "_clip_ctx", None) is not None:
            self._vision_enabled = True
            return
        # Legacy path: Llava15ChatHandler with clip model.
        try:
            from llama_cpp import Llava15ChatHandler

            handler = Llava15ChatHandler(
                clip_model_path=str(self._mmproj_path),
                n_ctx=self.n_ctx,
            )
            self._model.chat_handler = handler
            self._vision_enabled = True
            logger.info("Vision projector attached (legacy handler): %s", self._mmproj_path)
        except Exception as exc:
            self._vision_enabled = False
            logger.warning(
                "Vision projector could not be attached (%s) — running text-only", exc
            )

    def _decide_gpu_layers_for(self, path: Path) -> int:
        """Run the centralized, model-aware GPU strategy for *path*.

        Uses the file size and configured context length so a model larger
        than the GPU budget never receives the universal full-offload
        value.  Static/expert configurations (auto off with explicit
        layers, or auto off + 0 = CPU) bypass the automatic strategy and
        keep their exact value.  The decision and its reason are logged
        (observability) and cached on the loader for the UI.
        """
        if not self._auto_decide:
            self._gpu_reason = (
                "static configuration (auto GPU off) — n_gpu_layers unchanged"
            )
            return self.n_gpu_layers
        try:
            size = path.stat().st_size
        except OSError as exc:
            logger.warning("Cannot stat %s for GPU sizing: %s — CPU mode", path, exc)
            self._gpu_reason = "model size unavailable — CPU mode"
            return 0
        decision = decide_gpu_layers(
            model_size_bytes=size,
            n_ctx=self.n_ctx,
            capabilities=detect_gpu_capabilities(),
            mode=self._gpu_mode,
            manual_layers=self._manual_gpu_layers,
        )
        self._gpu_reason = decision.reason
        logger.info(
            "GPU strategy for %s: %s (n_gpu_layers=%d) — %s",
            path.name,
            decision.strategy.value,
            decision.n_gpu_layers,
            decision.reason,
        )
        return decision.n_gpu_layers

    def load(self, path: Path) -> None:
        self._load_error = None
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise ImportError(
                "llama-cpp-python is not installed. "
                "Install it with: pip install llama-cpp-python"
            ) from exc

        if not path.exists():
            raise FileNotFoundError(f"Model not found: {path}")

        # Centralized GPU decision (model-aware; replaces universal 999).
        self.n_gpu_layers = self._decide_gpu_layers_for(path)

        _profiler.start_load_timer()
        logger.info(
            "Loading GGUF model: %s (threads=%d, gpu_layers=%d, ctx=%d, mmproj=%s)",
            path, self.n_threads, self.n_gpu_layers, self.n_ctx,
            self._mmproj_path if self._mmproj_path else "none",
        )
        try:
            kwargs: dict[str, Any] = {
                "model_path": str(path),
                "n_ctx": self.n_ctx,
                "n_threads": self.n_threads,
                "n_gpu_layers": self.n_gpu_layers,
                "verbose": False,
            }
            if self._mmproj_path is not None and self._mmproj_path.exists():
                kwargs["mmproj"] = str(self._mmproj_path)
            try:
                self._model = Llama(**kwargs)
            except TypeError:
                # Older llama-cpp-python without the mmproj kwarg — load
                # text-only and attach the projector afterwards.
                kwargs.pop("mmproj", None)
                self._model = Llama(**kwargs)
        except Exception as exc:
            # GPU initialization failure vs. real model failure: when the
            # strategy chose GPU layers and the failure looks like a
            # CUDA/VRAM allocation problem, retry once on CPU before
            # surfacing the error.  A retry that fails too is a genuine
            # load failure and is re-raised (never silently swallowed).
            if self.n_gpu_layers > 0 and _looks_like_gpu_failure(exc):
                logger.warning(
                    "GPU offload failed during load (%s) — retrying on CPU",
                    exc,
                )
                self.n_gpu_layers = 0
                self._gpu_reason = f"GPU load failed, fell back to CPU: {exc}"
                kwargs["n_gpu_layers"] = 0
                kwargs.pop("mmproj", None)
                try:
                    self._model = Llama(**kwargs)
                except Exception as cpu_exc:
                    raise RuntimeError(
                        f"Failed to load model {path.name} (CPU retry): {cpu_exc}"
                    ) from cpu_exc
            else:
                raise RuntimeError(f"Failed to load model {path.name}: {exc}") from exc

        self._model_path = path
        if self._mmproj_path is not None:
            self._attach_vision_projector()
        load_time = _profiler.end_load_timer()
        chat_format = getattr(self._model, "chat_format", None)
        logger.info(
            "Model loaded: %s (%.2fs) — native chat format: %s, vision: %s",
            path.name, load_time, chat_format, self._vision_enabled,
        )

    def generate(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.7,
        top_p: float = 0.9, top_k: int = 40, min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        if self._model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")
        _profiler.start_inference_timer()
        try:
            output = self._model(
                prompt,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                min_p=min_p,
                repeat_penalty=repeat_penalty,
                stop=stop if stop else [],
            )
            text = output["choices"][0]["text"]
            completion_tokens = output.get("usage", {}).get("completion_tokens", len(text.split()))
            metrics = _profiler.end_inference_timer(completion_tokens)
            metrics.prompt_tokens = output.get("usage", {}).get("prompt_tokens", len(prompt.split()))
            if self._model_path:
                model = next((m for m in discover_models() if m.path == self._model_path), None)
                if model:
                    model.last_inference_metrics = metrics
            return text
        except Exception as exc:
            raise RuntimeError(f"Generation error: {exc}") from exc

    def generate_stream(
        self, prompt: str, max_tokens: int = 512, temperature: float = 0.7,
        top_p: float = 0.9, top_k: int = 40, min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        if self._model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")
        _profiler.start_inference_timer()
        _profiler.set_prompt_tokens(len(prompt.split()))
        try:
            completion_tokens = 0
            for chunk in self._model(
                prompt, max_tokens=max_tokens, temperature=temperature,
                top_p=top_p, top_k=top_k, min_p=min_p, repeat_penalty=repeat_penalty,
                stop=stop if stop else [], stream=True,
            ):
                token = _extract_streaming_text(chunk)
                if token:
                    completion_tokens += 1
                yield token
            metrics = _profiler.end_inference_timer(completion_tokens)
            if self._model_path:
                model = next((m for m in discover_models() if m.path == self._model_path), None)
                if model:
                    model.last_inference_metrics = metrics
        except Exception as exc:
            raise RuntimeError(f"Streaming generation error: {exc}") from exc

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> str:
        """Generate from chat ``messages`` using llama.cpp's native chat template.

        Delegates to :meth:`Llama.create_chat_completion`, which applies the
        model's GGUF ``tokenizer.chat_template`` (auto-detected at load time)
        via llama.cpp's Jinja2 chat formatter. No hand-built transcript is used,
        and no Llama-specific ``/INST`` or ``\nUser`` stop sequences are imposed
        (llama.cpp applies the model's native EOS via the template).
        """
        if self._model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")
        _profiler.start_inference_timer()
        try:
            output = self._model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                min_p=min_p,
                repeat_penalty=repeat_penalty,
                stop=stop if stop else [],
            )
            choices = output.get("choices", [])
            text = choices[0].get("message", {}).get("content", "") if choices else ""
            completion_tokens = output.get("usage", {}).get("completion_tokens", len(text.split()))
            metrics = _profiler.end_inference_timer(completion_tokens)
            metrics.prompt_tokens = output.get("usage", {}).get("prompt_tokens", 0)
            if self._model_path:
                model = next((m for m in discover_models() if m.path == self._model_path), None)
                if model:
                    model.last_inference_metrics = metrics
            return text
        except Exception as exc:
            raise RuntimeError(f"Chat generation error: {exc}") from exc

    def generate_chat_stream(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        min_p: float = 0.05,
        repeat_penalty: float = 1.1,
        stop: list[str] | None = None,
    ) -> Iterator[str]:
        """Stream chat tokens using the model's native chat template."""
        if self._model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")
        _profiler.start_inference_timer()
        try:
            completion_tokens = 0
            for chunk in self._model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                top_k=top_k,
                min_p=min_p,
                repeat_penalty=repeat_penalty,
                stop=stop if stop else [],
                stream=True,
            ):
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                token = delta.get("content", "") or chunk.get("choices", [{}])[0].get("text", "")
                if token:
                    completion_tokens += 1
                yield token
            metrics = _profiler.end_inference_timer(completion_tokens)
            if self._model_path:
                model = next((m for m in discover_models() if m.path == self._model_path), None)
                if model:
                    model.last_inference_metrics = metrics
        except Exception as exc:
            raise RuntimeError(f"Streaming chat generation error: {exc}") from exc

    def unload(self) -> None:
        if self._model is not None:
            try:
                self._model.close()
            except Exception as exc:
                logger.warning("Llama.close() failed during unload: %s", exc)
        self._model = None
        self._model_path = None
        logger.info("GGUF model unloaded")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def loaded_path(self) -> Path | None:
        return self._model_path

    @property
    def load_error(self) -> str | None:
        return self._load_error

    @property
    def status(self) -> ModelStatus:
        if self._model is not None:
            return ModelStatus.MODEL_AVAILABLE
        if self._load_error is not None:
            return ModelStatus.LOAD_FAILED
        return ModelStatus.NO_MODEL_AVAILABLE

    def count_tokens(self, messages: list[dict[str, str]]) -> int:
        """Return the number of tokens for the given messages.

        Uses the model's tokenizer to count tokens exactly. This is used for
        prompt truncation to ensure we stay within the model's context window.

        For llama.cpp models, we build the chat template text and tokenize it.
        The tokenize method expects bytes and returns token IDs.
        """
        if self._model is None:
            raise RuntimeError("Model is not loaded. Call load() first.")

        try:
            transcript = self._build_chat_transcript(messages)
            tokens = self._model.tokenize(transcript.encode("utf-8"), add_bos=True)
            return len(tokens)
        except Exception as exc:
            logger.debug("Token counting failed, using character estimate: %s", exc)
            total_chars = sum(len(m.get("content", "")) for m in messages)
            return total_chars // 4

    def _build_chat_transcript(self, messages: list[dict[str, str]]) -> str:
        """Build chat transcript text for tokenization.

        Uses the model's native chat template if available, otherwise falls back
        to a simple format that works for token counting purposes.
        """
        if self._model is None:
            return ""

        if hasattr(self._model, "chat_format") and self._model.chat_format:
            tokenizer = getattr(self._model, "_tokenizer", None)
            if tokenizer is not None and hasattr(tokenizer, "apply_chat_template"):
                try:
                    return tokenizer.apply_chat_template(messages, tokenize=False)
                except Exception as exc:
                    logger.debug("Chat template failed, using fallback: %s", exc)

        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.append(f"<|system|>\n{content}\n")
            elif role == "user":
                parts.append(f"<|user|>\n{content}\n")
            elif role == "assistant":
                parts.append(f"<|assistant|>\n{content}\n")
            else:
                parts.append(f"{role}: {content}\n")
        return "".join(parts)


def discover_models(directory: Path | None = None) -> list[ModelInfo]:
    """Find all GGUF model files in *directory* and subdirectories.

    Discovers both:
    - Files with ``*.gguf`` extension (``source=LOCAL_GGUF``)
    - Extensionless files whose first 4 bytes are ``b"GGUF"``
      (``source=EXTENSIONLESS``)

    PHASE 3: the default *directory* is the llm category dir under the
    configured (user-selected) models root — resolved at call time, never
    a module-import snapshot and never CWD-dependent.

    Returns a list of :class:`ModelInfo`.
    """
    if directory is None:
        directory = get_model_category_dir("llm")
    models: list[ModelInfo] = []
    if not directory.exists():
        return models

    for entry in sorted(directory.rglob("*")):
        if not entry.is_file():
            continue
        if entry.suffix == ".gguf":
            info = _build_model_info(entry, source=ModelSource.LOCAL_GGUF)
            if info is not None:
                models.append(info)
        else:
            if not _is_valid_gguf(entry):
                continue
            info = _build_model_info(entry, source=ModelSource.EXTENSIONLESS)
            if info is not None:
                models.append(info)

    return models


def _build_model_info(path: Path, source: ModelSource) -> ModelInfo | None:
    """Create a ModelInfo from a file path if it is a valid GGUF file."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        logger.debug("Cannot stat %s: %s", path, exc)
        return None

    if size == 0:
        return None

    caps = ModelCapabilities(
        text_generation=True,
        streaming=True,
        long_context=True,
    )
    metadata: dict[str, Any] = {}
    try:
        caps = _extract_capabilities(path, model_name=path.stem)
        metadata = _extract_metadata(path)
    except Exception as exc:
        logger.debug("Could not extract metadata from %s: %s", path.name, exc)

    info = ModelInfo(
        name=path.stem,
        path=path,
        size_bytes=size,
        capabilities=caps,
        source=source,
        source_identifier=path.stem,
        architecture=metadata.get("architecture", ""),
        parameters=metadata.get("parameters", ""),
        quantization=metadata.get("quantization", ""),
        context_length=metadata.get("context_length", 0),
        model_family=metadata.get("model_family", ""),
        model_type=classify_model(path.stem, path, metadata.get("architecture", ""), _read_gguf_metadata(path) or {}),
    )
    logger.debug("Discovered model: %s (%.1f MB) [%s]", path.name, info.size_mb, source.value)
    return info


def _extract_metadata(path: Path) -> dict[str, Any]:
    """Extract GGUF header metadata: architecture, parameters, quantization, context length."""
    result: dict[str, Any] = {}
    if not has_llama_cpp():
        return result
    try:
        from llama_cpp import Llama
        llama = Llama(model_path=str(path), n_ctx=1, n_threads=1, verbose=False)
        if hasattr(llama, "n_ctx_train") and llama.n_ctx_train:
            result["context_length"] = llama.n_ctx_train
    except Exception as exc:
        logger.debug("Could not extract GGUF metadata from %s: %s", path, exc)
    return result


def _is_valid_gguf(path: Path) -> bool:
    """Return True if *path* starts with the GGUF magic bytes."""
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"GGUF"
    except OSError:
        return False


def infer_capabilities(name: str, architecture: str = "", model_family: str = "") -> ModelCapabilities:
    """Infer model capabilities from model name, architecture, and family.

    Uses pattern matching on well-known model families and name tokens —
    not hardcoded for any specific model file.  Falls back gracefully:
    every GGUF model gets ``text_generation`` and ``streaming``.
    """
    name_lower = (name or "").lower()
    arch_lower = (architecture or "").lower()
    family_lower = (model_family or "").lower()
    combined = f"{name_lower} {arch_lower} {family_lower}"

    caps = ModelCapabilities(
        text_generation=True,
        streaming=True,
    )

    if "coder" in combined or "code" in combined:
        caps.code_generation = True

    vision_hints = ("vision", "vl", "image", "img", "llava", "moondream", "minicpm-v", "minicpmv", "gemma3n", "pixtral", "internvl", "lamm")
    if any(h in combined for h in vision_hints):
        caps.vision = True
        caps.multimodal = True

    if "reasoning" in combined or "r1" in combined or "think" in combined:
        caps.reasoning = True

    if "instruct" in combined or "chat" in combined or "qwen" in combined:
        caps.tool_calling = True
        caps.json_output = True
        caps.function_calling = True
        caps.structured_output = True

    if "embed" in combined:
        caps.embeddings = True

    return caps


# Architecture prefixes that map to text-generation LLMs.
# These are the GGUF ``general.architecture`` values that llama.cpp supports for
# causal LM inference (as opposed to diffusion, embedding, or vision-only models).
_KNOWN_LLM_ARCHITECTURES = frozenset({
    "llama", "llama2", "mllama",
    "phi2", "phi3", "phi3d1",
    "qwen", "qwen2", "qwen2vl", "qwen2moe", "qwen3", "qwen3moe", "qwen35",
    "gemma", "gemma2", "gemma3", "gemma4",
    "gpt2", "gptj", "gptneox",
    "mpt", "mptd",
    "bloom",
    "starcoder", "starcoder2",
    "command", "command-r",
    "falcon",
    "baizhipin",
    "internlm", "internlm2",
    "minicpm", "minicpm3",
    "yi", "yivl",
    "deepseek", "deepseekv2", "deepseek3",
    "glm", "glm4", "chatglm",
    "RefinedWebModel",
    "xwin",
    "gpt_bigcode",
    "granite",
    "nous",
    "dbrx",
    "jais",
    "miko",
    "openelm",
    "stablelm",
    "mamba", "mamba2",
    "nemotron",
    "r1",
})

# Architecture prefixes that indicate embedding models (non-text-generation).
_EMBEDDING_ARCHITECTURES = frozenset({
    "bert",
    "nomic-bert",
    "jina-bert",
    "minilm",
    "e5",
    "bge",
    "gte",
    "qwen2moe",  # could be LLM or embedding, depends on use
})

# Architecture that indicates diffusion (FLUX, stable diffusion, etc.).
_DIFFUSION_ARCHITECTURES = frozenset({
    "flux",
    "stable_diffusion",
    "stable_diffusion_xl",
})

# Filename patterns for known non-LLM files.
_PROJECTOR_PREFIXES = ("mmproj",)
_DIFFUSION_PATTERNS = ("flux", "stable-diffusion", "sdxl", "stable_diffusion", "karr", "sd3", "kolors")
_EMBEDDING_PATTERNS = ("mxbai-embed", "bge-", "e5-", "jina-embed", "nomic-embed", "gte-", "text2vec", "all-minilm")


# GGUF value type byte sizes for metadata parsing.
# Keys are the GGUF type enum values (NOT the ggml_type enum).
_GGUF_TYPE_SIZE: dict[int, int] = {
    0: 1,   # UINT8
    1: 1,   # INT8
    2: 2,   # UINT16
    3: 2,   # INT16
    4: 4,   # UINT32
    5: 4,   # INT32
    6: 4,   # FLOAT32
    7: 1,   # BOOL
    8: -1,  # STRING (variable length)
    9: -1,  # ARRAY (variable length)
    10: 8,  # UINT64
    11: 8,  # INT64
    12: 8,  # FLOAT64
}


def _read_gguf_metadata(path: Path, max_keys: int = 2000) -> dict[str, str] | None:
    """Read GGUF metadata key-value pairs from the file header.

    Returns a dict of metadata key-value pairs, or ``None`` if the file
    cannot be read as GGUF.  Only reads the header — does NOT instantiate
    ``Llama()`` (which would be slow and require the full runtime).

    GGUF v2+ header layout (24 bytes):
        magic (uint32) | version (uint32) | tensor_count (uint64)
        | metadata_kv_count (uint64)

    GGUF v1 header layout (16 bytes):
        magic (uint32) | version (uint32) | tensor_count (uint32)
        | metadata_len (uint32)

    Metadata values after header, each entry:
        key: uint64 length + UTF-8 bytes
        value_type: uint32
        value: depends on type

    GGUF type enum (NOT the ggml_type enum):
        0:UINT8, 1:INT8, 2:UINT16, 3:INT16, 4:UINT32, 5:INT32,
        6:FLOAT32, 7:BOOL, 8:STRING, 9:ARRAY, 10:UINT64, 11:INT64,
        12:FLOAT64
    """
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            if header != b"GGUF":
                return None
            version = int.from_bytes(f.read(4), "little")

            if version >= 2:
                # v2+ header: magic(4) + version(4) + tensor_count(8) + metadata_kv_count(8)
                f.read(8)  # tensor_count (unused)
                num_metadata = int.from_bytes(f.read(8), "little")
            else:
                # v1 header: magic(4) + version(4) + tensor_count(3) + metadata_len(4)
                f.read(4)  # tensor_count
                metadata_len = int.from_bytes(f.read(4), "little")
                num_metadata = metadata_len  # v1 uses byte-length, we iterate byte-by-byte later

            metadata: dict[str, str] = {}

            if version >= 2:
                for _ in range(min(num_metadata, max_keys)):
                    # Key: uint64 length + UTF-8 bytes
                    key_len = int.from_bytes(f.read(8), "little")
                    if key_len > 65535:
                        break
                    key = f.read(key_len).decode("utf-8", errors="replace")
                    val_type = int.from_bytes(f.read(4), "little")

                    if val_type == 8:  # STRING
                        str_len = int.from_bytes(f.read(8), "little")
                        val = f.read(str_len).decode("utf-8", errors="replace")
                        metadata[key] = val
                    elif val_type == 0:  # UINT8
                        metadata[key] = str(f.read(1)[0])
                    elif val_type == 1:  # INT8
                        b = f.read(1)[0]
                        metadata[key] = str(struct.unpack("b", bytes([b]))[0])
                    elif val_type == 2:  # UINT16
                        metadata[key] = str(int.from_bytes(f.read(2), "little"))
                    elif val_type == 3:  # INT16
                        metadata[key] = str(int.from_bytes(f.read(2), "little", signed=True))
                    elif val_type == 4:  # UINT32
                        metadata[key] = str(int.from_bytes(f.read(4), "little"))
                    elif val_type == 5:  # INT32
                        metadata[key] = str(int.from_bytes(f.read(4), "little", signed=True))
                    elif val_type == 6:  # FLOAT32
                        metadata[key] = str(struct.unpack("<f", f.read(4))[0])
                    elif val_type == 7:  # BOOL
                        metadata[key] = str(f.read(1)[0] != 0)
                    elif val_type == 10:  # UINT64
                        metadata[key] = str(int.from_bytes(f.read(8), "little"))
                    elif val_type == 11:  # INT64
                        metadata[key] = str(int.from_bytes(f.read(8), "little", signed=True))
                    elif val_type == 12:  # FLOAT64
                        metadata[key] = str(struct.unpack("<d", f.read(8))[0])
                    elif val_type == 9:  # ARRAY
                        arr_type = int.from_bytes(f.read(4), "little")
                        arr_len = int.from_bytes(f.read(8), "little")
                        # Skip array data — too complex to parse generically
                        type_size = _GGUF_TYPE_SIZE.get(arr_type, 0)
                        if type_size > 0:
                            f.read(arr_len * type_size)
                        elif arr_type == 8:  # STRING array
                            for _ in range(arr_len):
                                s_len = int.from_bytes(f.read(8), "little")
                                f.read(s_len)
                        else:
                            pass
                        metadata[key] = f"<array[{arr_len}] type={arr_type}>"
                    else:
                        metadata[key] = f"<type:{val_type}>"
            else:
                # v1: read metadata_len bytes
                remaining = metadata_len
                while remaining > 4:
                    key_len = int.from_bytes(f.read(4), "little")
                    remaining -= 4
                    if key_len > remaining or key_len > 65535:
                        break
                    key = f.read(key_len).decode("utf-8", errors="replace")
                    remaining -= key_len
                    val_type = int.from_bytes(f.read(4), "little")
                    remaining -= 4
                    if val_type == 8:  # STRING
                        str_len = int.from_bytes(f.read(8), "little")
                        remaining -= 8
                        if str_len > remaining:
                            break
                        val = f.read(str_len).decode("utf-8", errors="replace")
                        remaining -= str_len
                        metadata[key] = val
                    elif val_type == 0:
                        metadata[key] = str(f.read(1)[0])
                        remaining -= 1
                    elif val_type == 4:
                        metadata[key] = str(int.from_bytes(f.read(4), "little"))
                        remaining -= 4
                    elif val_type == 10:
                        metadata[key] = str(int.from_bytes(f.read(8), "little"))
                        remaining -= 8
                    else:
                        metadata[key] = f"<type:{val_type}>"

            return metadata
    except Exception:
        logger.debug("Failed to read GGUF metadata from %s", path)
        return None


def classify_model(
    name: str,
    path: Path | None = None,
    architecture: str = "",
    metadata: dict[str, str] | None = None,
) -> ModelType:
    """Classify a model's functional type.

    Priority:
    1. GGUF ``general.architecture`` metadata (most reliable)
    2. Filename patterns (conservative fallback)
    3. ``UNKNOWN`` if nothing matches

    Returns a :class:`ModelType` enum value.
    """
    arch = (architecture or "").lower().strip()
    name_lower = (name or "").lower()
    family_lower = ""
    if metadata:
        family_lower = (metadata.get("general.family", "") + " " +
                        metadata.get("general.type", "")).lower()

    combined = f"{arch} {name_lower} {family_lower}"

    # --- Architecture-based classification (from GGUF metadata) ---
    if arch:
        if arch in _DIFFUSION_ARCHITECTURES or arch in ("flux", "sd", "stable_diffusion"):
            return ModelType.DIFFUSION
        if arch in ("clip", "mmproj", "multimodal"):
            return ModelType.PROJECTOR
        if arch in _EMBEDDING_ARCHITECTURES:
            return ModelType.EMBEDDING
        # Check architecture against known LLM architectures
        if arch in _KNOWN_LLM_ARCHITECTURES:
            if "vision" in combined or "vl" in combined or arch in ("qwen2vl", "mllama", "yivl"):
                return ModelType.VISION_LLM
            return ModelType.LLM

    # --- Filename-based classification (fallback) ---
    if path is not None:
        filename = path.name.lower()
        if filename.startswith(_PROJECTOR_PREFIXES):
            return ModelType.PROJECTOR

    for pattern in _DIFFUSION_PATTERNS:
        if pattern in name_lower:
            return ModelType.DIFFUSION

    for pattern in _EMBEDDING_PATTERNS:
        if name_lower.startswith(pattern) or pattern in name_lower:
            return ModelType.EMBEDDING

    # If architecture was read but not recognized, and filename has no
    # specific pattern match, classify as UNKNOWN rather than guessing LLM.
    if arch and arch not in _KNOWN_LLM_ARCHITECTURES:
        return ModelType.UNKNOWN

    # If filename has no recognized patterns and no architecture,
    # we cannot confidently classify — default to UNKNOWN.
    # However, the old default behavior was text_generation=True for all GGUF.
    # We keep that for backward compatibility only when nothing else matches:
    # but only if the model has text_generation capability (which all GGUF do
    # via the old infer_capabilities).
    # For safety, we return UNKNOWN for unrecognizable files.
    return ModelType.UNKNOWN


def _extract_capabilities(path: Path, model_name: str = "") -> ModelCapabilities:
    """Extract capabilities from GGUF file metadata, enhanced with name-based inference.

    Uses ``infer_capabilities`` for name/architecture-based inference (reliable,
    no dependencies), then overrides with GGUF tensor metadata when available
    (e.g. vision tensor detection).  Falls back to name-based inference if
    GGUF metadata parsing fails.
    """
    name = model_name or path.stem
    caps = infer_capabilities(name)
    try:
        with open(path, "rb") as f:
            header = f.read(4)
            if header != b"GGUF":
                return caps
            f.read(4)  # version
            n_tensors = int.from_bytes(f.read(4), "little")
            f.read(4)  # length of key-value metadata
            for _ in range(n_tensors):
                name_len = int.from_bytes(f.read(4), "little")
                tensor_name = f.read(name_len).decode("utf-8", errors="ignore")
                f.read(4)  # data type
                f.read(4)  # data offset (split into 3 reads for 32-bit safety)
                f.read(4)
                f.read(4)
                dims = int.from_bytes(f.read(4), "little")
                f.read(4)  # num parameters
                f.read(1)  # data type
                f.read(4)  # num parameters (split)
                if "vision" in tensor_name.lower() or "image" in tensor_name.lower():
                    caps.vision = True
                    caps.multimodal = True
                if dims > 4096:
                    caps.long_context = True
    except Exception:
        logger.debug("Failed to extract capabilities from %s", path)
    return caps


def pick_default_model(models: list[ModelInfo]) -> ModelInfo | None:
    """Choose the smallest chat-compatible model as a safe default.

    Only models whose :attr:`ModelInfo.model_type` is :attr:`ModelType.LLM`
    or :attr:`ModelType.VISION_LLM` are considered.  Embedding, projector,
    diffusion, auxiliary, and unknown models are excluded so that the
    default selector never picks a non-text-generation model.

    Returns ``None`` when no chat-compatible models are found.
    """
    chat_models = [m for m in models if m.model_type.is_chat_compatible]
    if not chat_models:
        return None
    return min(chat_models, key=lambda m: m.size_bytes)


def has_llama_cpp() -> bool:
    """Return True if llama-cpp-python is importable."""
    return _try_import_llama_cpp()


def _add_cuda_dll_directories() -> None:
    """Register CUDA DLL directories (PHASE 4 centralized discovery).

    Kept as an internal alias for backward compatibility — the real
    implementation lives in :mod:`ai.models.gpu_runtime` and covers the
    ``nvidia`` package layout via the import system, ``sysconfig`` site
    directories, explicitly registered locations, and only *additionally*
    ``sys.path`` entries.
    """
    apply_cuda_dll_discovery()


def _try_import_llama_cpp() -> bool:
    _add_cuda_dll_directories()
    try:
        import llama_cpp  # noqa: F401
        return True
    except (ImportError, RuntimeError, OSError):
        return False
