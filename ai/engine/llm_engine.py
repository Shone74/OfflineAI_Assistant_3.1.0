"""LLM Engine abstraction + concrete backends.

``LLMEngine`` is the protocol every backend must implement.  Two backends
ship with Phase 3:

* :class:`LlamaCppEngine` — real inference via llama-cpp-python.
* :class:`StubEngine`     — canned responses when no backend/model is ready.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from ai.engine.tool_calling import (
    ToolCallParser,
    ToolCallResponse,
)
from ai.models.model_loader import (
    ModelCapabilities,
    ModelLoader,
    ModelSource,
    has_llama_cpp,
    is_gpu_available,
)
from ai.models.model_manager import ModelManager
from ai.prompts.system_prompts import SYSTEM_PROMPT
from core.exceptions import ModelError
from core.logger import get_logger

logger = get_logger("llm_engine")


def _is_test_mode() -> bool:
    return os.environ.get("OFFLINE_AI_TEST_MODE", "") == "1"


@dataclass
class GenerationConfig:
    """Parameters controlling LLM generation."""

    max_tokens: int = 512
    temperature: float = 0.7
    top_p: float = 0.9
    top_k: int = 40
    min_p: float = 0.05
    repeat_penalty: float = 1.1
    stop: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.stop is None:
            # Defaults to an empty stop list so that each model uses its own
            # native EOS handling (via the GGUF tokenizer template / eos token id)
            # instead of imposing Llama-specific "[/INST]" or the artificial
            # "\nUser" transcript delimiter globally.
            self.stop = []


class LLMEngine(ABC):
    """Abstract interface for a local LLM engine."""

    @abstractmethod
    def configure(self, model_manager: ModelManager) -> None:
        """Bind the engine to a model manager and activate a model."""

    @abstractmethod
    def unload(self) -> None:
        """Release the currently loaded model/loader. Safe to call when no model is loaded."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
    ) -> str:
        """Generate a full response (blocking)."""

    @abstractmethod
    def generate_stream(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
    ) -> Iterator[str]:
        """Yield response tokens one by one (for UI streaming)."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the currently active model."""

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """True if a model is loaded and ready for inference."""

    @property
    def model_capabilities(self) -> ModelCapabilities:
        """Return the capabilities of the currently active model."""
        raise NotImplementedError

    @property
    def supports_tool_calling(self) -> bool:
        """True if the active model supports native tool/function calling."""
        caps = self.model_capabilities
        return caps.tool_calling or caps.function_calling

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        config: GenerationConfig | None = None,
    ) -> ToolCallResponse:
        """Generate a response with native tool-call support.

        The default implementation generates plain text and parses it for
        tool-call patterns via :class:`ToolCallParser`.  Subclasses with
        a provider-native protocol (e.g. OpenAI Chat Completions) may
        override this to use the raw tool_call objects directly.
        """
        text = self.generate(prompt, config)
        return ToolCallParser.parse(text)

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig | None = None,
    ) -> str:
        """Generate a full response from chat ``messages``.

        The default implementation renders the messages into the legacy
        transcript prompt and delegates to :meth:`generate`.  Backends that
        support a native chat template (e.g. :class:`LlamaCppEngine`) override
        this to call ``Llama.create_chat_completion`` so the model's GGUF
        ``tokenizer.chat_template`` is applied.
        """
        system_prompt, history, user_input = _messages_to_transcript(messages)
        prompt = build_response_prompt(system_prompt, history, user_input)
        return self.generate(prompt, config)

    def generate_chat_stream(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig | None = None,
    ) -> Iterator[str]:
        """Stream a response from chat ``messages`` (native template when supported)."""
        system_prompt, history, user_input = _messages_to_transcript(messages)
        prompt = build_response_prompt(system_prompt, history, user_input)
        yield from self.generate_stream(prompt, config)


class LlamaCppEngine(LLMEngine):
    """Backend wrapping a ``ModelLoader`` (GGUF via llama-cpp-python)."""

    def __init__(self) -> None:
        self._manager: ModelManager | None = None
        self._loader: ModelLoader | None = None
        self._model_name_override: str | None = None

    def configure(self, model_manager: ModelManager) -> None:
        self._manager = model_manager
        if model_manager.list_models():
            if model_manager.get_active_model() is None:
                model_manager.select_default()
            self._loader = model_manager.get_loader()
        elif _is_test_mode() and not model_manager.list_models():
            logger.warning("No models available — engine will use stub (TEST MODE)")
            model_manager.activate_stub()
            self._loader = model_manager.get_loader()
        else:
            logger.warning("No models available — engine cannot configure without a real model")
            if not _is_test_mode():
                raise ModelError(
                    "No GGUF models found in the models folder. "
                    "Place a .gguf model file in the models folder."
                )

    def unload(self) -> None:
        """Release the currently loaded model. Safe to call when no model is loaded."""
        if self._loader is not None:
            self._loader.unload()
        self._loader = None
        logger.info("Engine model unloaded")

    def generate(self, prompt: str, config: GenerationConfig | None = None) -> str:
        if self._loader is None:
            raise ModelError("Engine not configured — call configure() first")
        if not _is_test_mode() and getattr(self._loader, "is_stub", False):
            raise ModelError(
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and load a GGUF model."
            )
        cfg = config or GenerationConfig()
        return self._loader.generate(
            prompt,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            min_p=cfg.min_p,
            repeat_penalty=cfg.repeat_penalty,
            stop=cfg.stop,
        )

    def generate_stream(self, prompt: str, config: GenerationConfig | None = None) -> Iterator[str]:
        if self._loader is None:
            raise ModelError("Engine not configured — call configure() first")
        if not _is_test_mode() and getattr(self._loader, "is_stub", False):
            raise ModelError(
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and load a GGUF model."
            )
        cfg = config or GenerationConfig()
        yield from self._loader.generate_stream(
            prompt,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            min_p=cfg.min_p,
            repeat_penalty=cfg.repeat_penalty,
            stop=cfg.stop,
        )

    def generate_chat(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig | None = None,
    ) -> str:
        if self._loader is None:
            raise ModelError("Engine not configured — call configure() first")
        if not _is_test_mode() and getattr(self._loader, "is_stub", False):
            raise ModelError(
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and load a GGUF model."
            )
        cfg = config or GenerationConfig()
        return self._loader.generate_chat(
            messages,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            min_p=cfg.min_p,
            repeat_penalty=cfg.repeat_penalty,
            stop=cfg.stop,
        )

    def generate_chat_stream(
        self,
        messages: list[dict[str, str]],
        config: GenerationConfig | None = None,
    ) -> Iterator[str]:
        if self._loader is None:
            raise ModelError("Engine not configured — call configure() first")
        if not _is_test_mode() and getattr(self._loader, "is_stub", False):
            raise ModelError(
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and load a GGUF model."
            )
        cfg = config or GenerationConfig()
        yield from self._loader.generate_chat_stream(
            messages,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            top_p=cfg.top_p,
            top_k=cfg.top_k,
            min_p=cfg.min_p,
            repeat_penalty=cfg.repeat_penalty,
            stop=cfg.stop,
        )

    def count_tokens(self, messages: list[dict[str, str]]) -> int:
        """Return the number of tokens that would be used for generation.

        Uses the model's tokenizer to count tokens exactly. This is used for
        prompt truncation to ensure we stay within the model's context window.
        """
        if self._loader is None:
            raise ModelError("Engine not configured — call configure() first")
        return self._loader.count_tokens(messages)

    @property
    def model_name(self) -> str:
        if self._model_name_override is not None:
            return self._model_name_override
        if self._manager is not None:
            active = self._manager.get_active_model()
            if active is not None:
                source_tag = f" [{active.source.display_name}]" if active.source != ModelSource.LOCAL_GGUF else ""
                return f"{active.name}{source_tag}"
        return "stub"

    @property
    def is_ready(self) -> bool:
        return self._loader is not None

    @property
    def runtime_available(self) -> bool:
        """True if llama-cpp-python is importable."""
        return has_llama_cpp()

    @property
    def load_status(self) -> str:
        """Return a human-readable status string for the UI."""
        if self._manager is None:
            return "not_configured"
        if not self._manager.runtime_available:
            return "runtime_unavailable"
        if self._loader is None:
            return "not_loaded"
        if hasattr(self._loader, "is_stub") and self._loader.is_stub:
            return "stub_mode"
        if hasattr(self._loader, "status"):
            return self._loader.status.value
        if self._loader is not None:
            return "ready"
        return "not_loaded"

    @property
    def load_error(self) -> str | None:
        if self._manager is not None:
            return self._manager.load_error
        return None

    @property
    def gpu_available(self) -> bool:
        """True if NVIDIA GPU is detected."""
        return is_gpu_available()

    @property
    def gpu_layers(self) -> int:
        """Returns the active loader's n_gpu_layers, or 0."""
        if self._loader is not None and hasattr(self._loader, "n_gpu_layers"):
            return self._loader.n_gpu_layers  # type: ignore[no-any-return]
        return 0

    @property
    def model_capabilities(self) -> ModelCapabilities:
        if self._manager is not None:
            active = self._manager.get_active_model()
            if active is not None:
                return active.capabilities
        if getattr(self._loader, "is_stub", False):
            return ModelCapabilities(text_generation=True, streaming=True)
        return ModelCapabilities()


class StubEngine(LLMEngine):
    """Engine that always returns a canned response (for CI / demo)."""

    def __init__(self) -> None:
        self._model_name = "stub-model"
        self._queued_responses: list[ToolCallResponse] = []

    def configure(self, model_manager: ModelManager) -> None:
        model_manager.activate_stub()

    def unload(self) -> None:
        logger.info("StubEngine unload — no-op (no real model)")

    def generate(self, prompt: str, config: GenerationConfig | None = None) -> str:
        return (
            "Ovo je placeholder odgovor. Nema povezanog AI modela. "
            "(StubEngine)"
        )

    def generate_stream(self, prompt: str, config: GenerationConfig | None = None) -> Iterator[str]:
        yield self.generate(prompt, config)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_ready(self) -> bool:
        return True

    @property
    def model_capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            text_generation=True,
            streaming=True,
        )

    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        config: GenerationConfig | None = None,
    ) -> ToolCallResponse:
        """Stub implementation that can be configured for tool-call testing.

        When ``_queued_responses`` contains :class:`ToolCallResponse` objects
        they are returned in order (once each).  After the queue is empty,
        normal canned-text generation resumes.
        """
        if self._queued_responses:
            return self._queued_responses.pop(0)
        return ToolCallResponse(text=self.generate(prompt, config))

    def queue_tool_response(self, response: ToolCallResponse) -> None:
        """Enqueue a :class:`ToolCallResponse` to be returned by the next
        ``generate_with_tools`` call.  Used by tests to simulate model
        tool-call behaviour."""
        self._queued_responses.append(response)


def build_response_prompt(
    system_prompt: str,
    history: list[dict[str, str]],
    user_input: str,
) -> str:
    """Assemble the full prompt string sent to the LLM."""
    parts: list[str] = [f"[SYSTEM]\n{system_prompt}\n"]
    for msg in history:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prefix = "User" if role == "user" else "Assistant"
        parts.append(f"{prefix}: {content}\n")
    parts.append(f"User: {user_input}\nAssistant:")
    return "".join(parts)


def _messages_to_transcript(
    messages: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]], str]:
    """Extract ``(system_prompt, history, user_input)`` from a chat messages list.

    Used as a fallback by :meth:`LLMEngine.generate_chat` /
    :meth:`LLMEngine.generate_chat_stream` when a backend does not override the
    native chat-template path.  The first ``system`` message becomes the system
    prompt, intermediate ``user``/``assistant`` turns become ``history``, and the
    final ``user`` message is treated as the current input.
    """
    system_prompt = ""
    history: list[dict[str, str]] = []
    user_input = ""
    seen_system = False
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system" and not seen_system:
            system_prompt = content
            seen_system = True
        elif role == "user":
            if user_input:
                history.append({"role": "user", "content": user_input})
            user_input = content
        elif role == "assistant":
            history.append({"role": "assistant", "content": content})
    return system_prompt, history, user_input


DEFAULT_SYSTEM_PROMPT = SYSTEM_PROMPT
