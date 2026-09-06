"""Core AI Assistant — the logical coordinator of the application.

After Phase 3 the assistant delegates to an :class:`LLMEngine` (llama.cpp
backend) and assembles the prompt from the system prompt + conversation
history.  After Phase 4 memory (short-term, long-term, vector) is woven
into context assembly and persistence.
"""

from __future__ import annotations

import copy
import json
import os
import re
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ai.engine.inference import InferenceSession
from ai.engine.llm_engine import GenerationConfig, LLMEngine, build_response_prompt
from ai.models.model_manager import ModelManager
from ai.prompts.system_prompts import (
    SYSTEM_PROMPT_TEMPLATE,
)
from core.config_manager import ConfigManager
from core.event_bus import EventBus, EventCallback
from core.exceptions import ModelError
from core.logger import apply_log_level, get_logger
from core.router import Router
from database.models import Agent, MemoryType
from memory.memory_manager import MemoryManager
from project.context import (
    AgentRuntimeState,
    ProjectContext,
    ProjectContextManager,
)
from project.profile_stack import ProfileStack
from tools.base import ToolRegistry, ToolResult

if TYPE_CHECKING:
    from agent.orchestrator import AgentOrchestrator
    from agent.planner import Planner
    from agent.repository import AgentRepository
    from agent.verifier import AgentVerifier
    from automation.manager import AutomationManager
    from knowledge.knowledge_base import KnowledgeBase
    from knowledge.rag_pipeline import RAGPipeline
    from plugins.manager import PluginManager
    from project.manager import ProjectManager, WorkspaceManager

logger = get_logger("assistant")


def _is_test_mode() -> bool:
    return os.environ.get("OFFLINE_AI_TEST_MODE", "") == "1"


_MEMORY_TRIGGERS = (
    "please remember that ",
    "please remember ",
    "i want you to remember ",
    "i want you to remember that ",
    "remember that ",
    "remember ",
    "save this: ",
    "save this:",
    "save that ",
    "store that ",
)
_MEMORY_NEGATIVE_PHRASES = (
    "don't save",
    "don't remember",
    "do not save",
    "don't",
    "no thanks",
    "leave it",
    "not now",
)
_MEMORY_NEGATIVE_TOKENS = {"no", "nope", "nah", "never", "cancel", "dont", "not"}

_MEMORY_AFFIRMATIVE_PHRASES = (
    "save it",
    "remember it",
    "do it",
    "go ahead",
    "yes please",
    "please do it",
    "please save it",
)
_MEMORY_AFFIRMATIVE_TOKENS = {
    "yes",
    "yeah",
    "sure",
    "yep",
    "ok",
    "okay",
    "y",
    "confirm",
    "confirmed",
    "absolutely",
    "definitely",
}


def _extract_memory_fact(text: str) -> str | None:
    """Detect an explicit user request to remember something.

    Returns the extracted fact (capitalised) when an explicit ``Remember…`` /
    ``Save this…`` trigger is found, otherwise ``None``.  Normal conversation
    text is never treated as a memory on its own.
    """
    lowered = text.strip().lower()
    for trigger in _MEMORY_TRIGGERS:
        if lowered.startswith(trigger):
            fact = text[len(trigger):].strip()
            if not fact:
                return None
            return fact[0].upper() + fact[1:]
    return None


def _classify_confirmation(text: str) -> str | None:
    """Classify a follow-up reply as ``affirmative``, ``negative`` or ``None``.

    Purely keyword based — no NLP model.  Negative forms are checked first so
    that e.g. ``don't save it`` is not swallowed by the ``save it`` affirmative.
    Short keywords are matched as *whole tokens* to avoid false positives such
    as ``"ok" in "joke"`` or ``"y" in "today"``.
    """
    t = re.sub(r"\s+", " ", text.strip().lower())
    if not t:
        return None
    tokens = set(re.findall(r"[a-z0-9]+", t.replace("'", "")))
    if any(phrase in t for phrase in _MEMORY_NEGATIVE_PHRASES):
        return "negative"
    if tokens & _MEMORY_NEGATIVE_TOKENS:
        return "negative"
    if any(phrase in t for phrase in _MEMORY_AFFIRMATIVE_PHRASES):
        return "affirmative"
    if tokens & _MEMORY_AFFIRMATIVE_TOKENS:
        return "affirmative"
    return None


def _classify_memory_type(fact: str) -> str:
    """Pick an existing MemoryType for an extracted fact."""
    lowered = fact.lower()
    if any(w in lowered for w in ("prefer", "favorite", "favor")):
        return MemoryType.USER_PREFERENCE.value
    if any(w in lowered for w in ("project", "called", "named", "application")):
        return MemoryType.PROJECT_INFO.value
    if any(w in lowered for w in ("always", "never", "must", "should", "don't", "do not")):
        return MemoryType.INSTRUCTION.value
    return MemoryType.FACT.value


class Assistant:
    """Central coordinator that ties together config, events, routing, memory, and the LLM engine."""

    def __init__(
        self,
        config: ConfigManager,
        event_bus: EventBus,
        router: Router,
        model_manager: ModelManager | None = None,
        engine: LLMEngine | None = None,
        memory: MemoryManager | None = None,
        tools: ToolRegistry | None = None,
        knowledge: KnowledgeBase | None = None,
        rag_pipeline: RAGPipeline | None = None,
        planner: Planner | None = None,
        orchestrator: AgentOrchestrator | None = None,
        automation_manager: AutomationManager | None = None,
        plugin_manager: PluginManager | None = None,
        workspace_manager: WorkspaceManager | None = None,
        project_manager: ProjectManager | None = None,
        agent_repository: AgentRepository | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.router = router
        self._model_manager = model_manager
        self._engine = engine
        self._memory = memory
        self._tools = tools
        self._knowledge = knowledge
        self._rag_pipeline = rag_pipeline
        self._planner = planner
        self._orchestrator = orchestrator
        self._automation = automation_manager
        self._plugin_manager = plugin_manager
        self._started = False
        self._workspace_manager = workspace_manager
        self._project_manager = project_manager
        self._agent_repository = agent_repository
        self._context_manager: ProjectContextManager | None = None
        if project_manager is not None:
            self._context_manager = ProjectContextManager(
                event_bus=self.event_bus,
                project_manager=project_manager,
            )
        self._verifier: AgentVerifier | None = None
        self._active_workspace_id: str | None = None
        self._active_project_id: str | None = None
        self._profile = self._load_assistant_profile()
        self._pending_memory: str | None = None
        self._on_config_changed_sub_id: Any | None = None
        self._cancel_event: threading.Event | None = None
        logger.info("Assistant initialised (Phase 13.1)")

    def _build_generation_config(self) -> GenerationConfig:
        """Build a GenerationConfig from ConfigManager values.

        Central factory for all normal (non-verifier) generation.  Ensures
        max_tokens is clamped to n_ctx - 1 so the prompt always has room.
        """
        n_ctx = self.config.get("ai.n_ctx", 4096)
        max_tokens = self.config.get("ai.max_tokens", 512)
        max_tokens = min(max_tokens, n_ctx - 1) if n_ctx > 1 else max_tokens
        return GenerationConfig(
            max_tokens=max_tokens,
            temperature=self.config.get("ai.temperature", 0.7),
            top_p=self.config.get("ai.top_p", GenerationConfig.top_p),
            top_k=self.config.get("ai.top_k", GenerationConfig.top_k),
            min_p=self.config.get("ai.min_p", GenerationConfig.min_p),
            repeat_penalty=self.config.get("ai.repeat_penalty", GenerationConfig.repeat_penalty),
        )

    def _build_verifier_config(self) -> GenerationConfig:
        """Build a GenerationConfig for the AI verifier — intentionally separate.

        Uses verifier-specific defaults (max_tokens=256, temperature=0.1) to
        ensure short, deterministic evaluation output.  These values are
        configurable via ``ai.verifier.*`` keys but are NOT exposed in the
        Settings UI.
        """
        max_tokens = self.config.get("ai.verifier.max_tokens", 256)
        temperature = self.config.get("ai.verifier.temperature", 0.1)
        try:
            max_tokens = int(max_tokens)
        except (TypeError, ValueError):
            max_tokens = 256
        try:
            temperature = float(temperature)
        except (TypeError, ValueError):
            temperature = 0.1
        return GenerationConfig(max_tokens=max_tokens, temperature=temperature)

    def _enforce_context_budget(
        self,
        messages: list[dict[str, str]],
        cfg: GenerationConfig,
    ) -> list[dict[str, str]]:
        """Truncate messages to stay within the model's context window.

        Policy:
        1. Preserve system prompt (contains instructions, profile, memories, RAG)
        2. Preserve the latest user message (the current query)
        3. Preserve recent conversation history (user+assistant pairs)
        4. Discard oldest history messages first when over budget
        5. Reserve tokens for generation (max_tokens with 25% safety margin)

        Returns a new messages list that fits within the effective context budget.
        """
        if self._engine is None:
            return messages
        if not getattr(self._engine, "is_ready", False):
            return messages

        n_ctx = self.config.get("ai.n_ctx", 4096)

        generation_reserve = int(n_ctx * 0.25)
        generation_reserve = max(generation_reserve, cfg.max_tokens)

        effective_context = max(n_ctx - generation_reserve, 512)

        try:
            prompt_tokens = self._engine.count_tokens(messages)
            if not isinstance(prompt_tokens, int):
                prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4
        except Exception as exc:
            logger.debug("Token counting failed, using fallback: %s", exc)
            prompt_tokens = sum(len(m.get("content", "")) for m in messages) // 4

        if prompt_tokens <= effective_context:
            return messages

        logger.info(
            "Prompt truncated: %d tokens exceeds %d token budget",
            prompt_tokens,
            effective_context,
        )

        if len(messages) <= 2:
            return messages

        result = [messages[0], messages[-1]]

        history_msgs = messages[1:-1]
        truncated_tokens = self._count_tokens_simple(messages[0]) + self._count_tokens_simple(messages[-1]["content"])

        for msg in reversed(history_msgs):
            msg_tokens = self._count_tokens_simple(msg.get("content", ""))
            if truncated_tokens + msg_tokens <= effective_context:
                result.insert(1, msg)
                truncated_tokens += msg_tokens
            else:
                logger.debug(
                    "History message truncated (role=%s)",
                    msg.get("role", "unknown"),
                )

        return result

    def _count_tokens_simple(self, text: str) -> int:
        """Estimate token count using character-based approximation.

        Used as a fallback when exact tokenization is unavailable.
        Typical English text: ~4 characters per token.
        """
        if not text:
            return 0
        if not isinstance(text, str):
            text = str(text)
        return max(1, len(text) // 4)

    def _truncate_history_for_context(
        self,
        history: list[dict[str, str]],
        user_input: str,
        max_tokens: int,
        system_prompt: str,
    ) -> list[dict[str, str]]:
        """Truncate history to fit within the context budget.

        Used by the native tools path which builds a text prompt rather than
        a messages list. Preserves the system prompt, user input, and recent
        history messages while discarding older ones.
        """
        if not history:
            return []

        user_tokens = self._count_tokens_simple(user_input) + self._count_tokens_simple("User: ")
        system_tokens = self._count_tokens_simple(system_prompt) + self._count_tokens_simple("[SYSTEM]\n") + self._count_tokens_simple("\n")

        used = system_tokens + user_tokens
        available = max_tokens - used

        if available < 50:
            return history[-1:] if history else []

        result: list[dict[str, str]] = []
        remaining = available

        for msg in reversed(history):
            msg_tokens = self._count_tokens_simple(msg.get("content", ""))
            prefix = "Assistant: " if msg.get("role") == "assistant" else "User: "
            total = msg_tokens + self._count_tokens_simple(prefix)

            if total <= remaining:
                result.insert(0, msg)
                remaining -= total
            else:
                logger.debug("History message truncated for native tools (role=%s)", msg.get("role", "unknown"))

        return result

    @property
    def model_manager(self) -> ModelManager | None:
        return self._model_manager

    def start(self) -> None:
        """Start the assistant and initialize subsystems.

        Publishes APP_STARTED event on successful start.
        Configures LLM engine and model manager if available.
        Starts conversation in memory system.

        Idempotent: Safe to call multiple times (logs warning if already started).
        """
        if self._started:
            logger.warning("Assistant is already started")
            return
        self.event_bus.publish("APP_STARTED", data={})

        # Handle fast paths that do not require blocking model load.
        # The blocking default-model load is now performed asynchronously
        # by ApplicationManager after the GUI is visible and the event
        # loop is able to process paint/input events.
        if self._engine is not None and self._model_manager is not None:
            models = self._model_manager.list_models()
            if not models:
                if _is_test_mode():
                    logger.warning("No models found — starting in stub mode (TEST MODE)")
                    self._engine.configure(self._model_manager)
                else:
                    logger.warning("No GGUF models found in %s", self._model_manager.models_dir)
                    self.event_bus.publish(
                        "MODEL_LOAD_FAILED",
                        data={"error": "No GGUF models found in the models folder."},
                    )
        if self._memory is not None:
            self._memory.start_conversation(
                profile_snapshot=self.get_effective_profile(),
            )
            logger.info("Memory system ready (conversation started)")

        self._started = True

        # Step 8: initialize agent verifier with the global LLM engine for
        # optional AI-based self-evaluation (never mutates the Chat model).
        from agent.verifier import AgentVerifier

        try:
            self._verifier = AgentVerifier(
                llm_engine=self._engine,
                config=self._build_verifier_config(),
            )
        except Exception:
            logger.warning(
                "AgentVerifier initialization failed — "
                "verification will be skipped (self._verifier = None)",
                exc_info=True,
            )
            self._verifier = None
        self._on_config_changed_sub_id = self.event_bus.subscribe(
            "CONFIG_CHANGED", self._on_config_changed
        )
        logger.info("Assistant started")

    def _load_default_model(self) -> str | None:
        """Load the default model and configure the engine.

        This performs the blocking model-load operation and must be called
        from a background worker thread, not from the Qt GUI thread.

        Returns the loaded model name on success, or ``None`` if no model
        was loaded (e.g., stub mode or no models available).

        Raises :class:`ModelError` if model loading fails.
        """
        if self._engine is None or self._model_manager is None:
            return None

        models = self._model_manager.list_models()
        if not models:
            if _is_test_mode():
                self._engine.configure(self._model_manager)
                return None
            raise ModelError("No GGUF models found in the models folder.")

        active_model = self._model_manager.select_default()
        self._engine.configure(self._model_manager)
        return active_model.name if active_model is not None else None

    def request_cancel(self) -> None:
        """Request cancellation of the current in-flight generation.

        Sets the per-generation cancellation event so the generation loop
        in :meth:`_generate_response` can break out cooperatively at the
        next token boundary.  If no generation is active, this is a no-op.
        """
        if self._cancel_event is not None:
            self._cancel_event.set()
            logger.info("Cancellation requested for in-flight generation")

    def _on_config_changed(self, event_type: str, data: dict) -> None:
        """Handle CONFIG_CHANGED events for generation and memory parameters.

        Memory and generation parameters are read fresh from ConfigManager
        on each use, so no engine or MemoryManager recreation is needed for
        most changes.  ``memory.short_term_window`` is applied at runtime via
        ``ShortTermMemory.set_max_window()``.  ``memory.embedding_model``
        requires a restart (logged).
        """
        key = data.get("key", "")
        if key in (
            "ai.max_tokens", "ai.temperature", "ai.top_p", "ai.top_k",
            "ai.min_p", "ai.repeat_penalty",
        ):
            logger.info("Generation config changed: %s = %s", key, data.get("value"))
            if self._planner is not None and hasattr(self._planner, "_generation_config"):
                self._planner._generation_config = self._build_generation_config()
        elif key in ("ai.verifier.max_tokens", "ai.verifier.temperature"):
            logger.info("Verifier config changed: %s = %s", key, data.get("value"))
            if self._verifier is not None:
                self._verifier._generation_config = self._build_verifier_config()
        elif key == "ai.n_ctx":
            logger.info("Generation config changed: %s = %s", key, data.get("value"))
            logger.warning(
                "ai.n_ctx changed — model reload required for new context size to take effect"
            )
        elif key in (
            "memory.enabled", "memory.short_term_window",
            "memory.max_context_memories", "memory.embedding_model",
        ):
            self.config.set(key, data.get("value"))
            logger.info("Memory config changed: %s = %s", key, data.get("value"))
            if key == "memory.short_term_window":
                self._resize_short_term_window()
            if key == "memory.embedding_model":
                logger.warning(
                    "memory.embedding_model changed — restart required for new backend to take effect"
                )
        elif key == "logging.level":
            apply_log_level(data.get("value", "INFO"))
            logger.info("Log level changed to %s", data.get("value"))

    def _resize_short_term_window(self) -> None:
        """Resize the ShortTermMemory deque to match ``memory.short_term_window``.

        Called when ``CONFIG_CHANGED`` is received for ``memory.short_term_window``.
        Preserves existing recent entries — only the maxlen is adjusted.
        Does NOT touch the persistent SQLite database.
        """
        if self._memory is None:
            return
        new_window = self.config.get("memory.short_term_window", 10)
        try:
            new_window = int(new_window)
        except (TypeError, ValueError):
            new_window = 10
        stm = getattr(self._memory, "_short_term", None)
        if stm is not None and hasattr(stm, "set_max_window"):
            stm.set_max_window(new_window)

    def _resolve_agent_engine(self, agent_def: Agent) -> LLMEngine | None:
        """Resolve the LLMEngine appropriate for *agent_def* without mutating
        the global Chat model.

        - ``model_name == ""`` → returns the global engine (backward compatible).
        - ``model_name`` starting with ``openrouter:`` or ``api:`` → returns
          an :class:`OpenAICompatibleEngine` for the online model (opt-in;
          requires ``api.enabled`` and a stored key — otherwise falls back
          to the global engine with a clear warning).
        - ``model_name`` set (local) → attempts to load a scoped loader via
          ``ModelManager.get_loader_for_model`` and wraps it in a
          ``LlamaCppEngine`` whose ``_model_name_override`` is set.
        - On any failure → logs a warning and falls back to the global engine.

        When ``api.auto_free_models`` is enabled and the agent has no
        explicit model, a free online model is picked from the user's
        selection (Settings → Online API) based on the agent's goal/task
        type — coding, reasoning, vision, or general.

        Limitations:
          Loading a second model alongside the Chat model may consume additional
          memory.  If the model is unavailable or the runtime is missing, the
          global engine is used as a transparent fallback — the Agent still runs.
        """
        # --- Auto free-model routing (no explicit model set) --------------
        if not agent_def.model_name:
            engine = self._build_auto_free_engine(agent_def)
            if engine is not None:
                return engine
            return self._engine

        # --- Online API routing (explicit user opt-in per agent) ---------
        model_spec = agent_def.model_name.strip()
        if ":" in model_spec.split("/")[0] or model_spec.lower().startswith(
            ("openrouter:", "api:", "groq:", "google:", "gemini:", "mistral:",
             "cerebras:", "together:", "or:")
        ):
            from ai.engine.api_engine import parse_online_model_spec

            provider_id, online_model = parse_online_model_spec(model_spec)
            engine = self._build_online_engine(provider_id, online_model)
            if engine is not None:
                logger.info(
                    "Agent '%s' routed to online model '%s' (provider=%s)",
                    agent_def.name, online_model, provider_id or "default",
                )
                try:
                    self.event_bus.publish(
                        "API_ENGINE_ACTIVE",
                        data={
                            "model": online_model,
                            "provider": provider_id or "default",
                            "agent": agent_def.name,
                        },
                    )
                except Exception:
                    logger.debug("API_ENGINE_ACTIVE publish failed", exc_info=True)
                return engine
            logger.warning(
                "Agent '%s' requests online model '%s' but provider '%s' is "
                "not configured (api.enabled/key missing) — using global "
                "local engine",
                agent_def.name, online_model, provider_id or "default",
            )
            return self._engine

        mm = self._model_manager
        if mm is None or self._engine is None:
            logger.info(
                "Agent '%s' has model_name='%s' but no ModelManager/engine — "
                "using global engine", agent_def.name, agent_def.model_name,
            )
            return self._engine

        try:
            loader = mm.get_loader_for_model(agent_def.model_name)
            from ai.engine.llm_engine import LlamaCppEngine

            engine = LlamaCppEngine()
            engine._manager = mm
            engine._loader = loader
            engine._model_name_override = agent_def.model_name
            logger.info("Agent '%s' resolved to model '%s'", agent_def.name, agent_def.model_name)
            return engine
        except Exception as exc:
            logger.warning(
                "Agent '%s' model '%s' unavailable: %s — using global engine",
                agent_def.name, agent_def.model_name, exc,
            )
            return self._engine

    def _build_online_engine(
        self, provider_id: str, online_model: str
    ) -> LLMEngine | None:
        """Build an online engine for *online_model* on the given provider.

        ``provider_id=""`` resolves to the configured default provider.
        Returns ``None`` when the API is disabled or the provider has no
        stored key so the caller can fall back to the local engine.
        """
        try:
            from ai.engine.api_engine import build_provider_engine

            return build_provider_engine(self.config, provider_id, online_model)
        except Exception:
            logger.warning("Could not build online engine", exc_info=True)
            return None

    def _build_auto_free_engine(self, agent_def: Agent) -> LLMEngine | None:
        """Pick a free online model from the user's selection for this agent.

        Uses ``select_free_model_for_task`` heuristics (coding / reasoning /
        vision / general) over the agent's goal.  Returns ``None`` when the
        feature is disabled, nothing is selected, or the provider has no
        stored key — the caller then falls back to the global engine.
        """
        try:
            if not self.config.get("api.auto_free_models", False):
                return None
            if not self.config.get("api.enabled", False):
                return None
            from ai.engine.api_engine import (
                provider_is_configured,
                select_free_model_for_task,
            )

            task_text = " ".join(
                part
                for part in (
                    agent_def.description or "",
                    agent_def.system_prompt or "",
                )
                if isinstance(part, str)
            )
            picked = select_free_model_for_task(self.config, task_text)
            if picked is None:
                return None
            provider_id, model = picked
            if not provider_is_configured(self.config, provider_id):
                return None
            engine = self._build_online_engine(provider_id, model)
            if engine is not None:
                logger.info(
                    "Agent '%s' auto-routed to free model '%s' (provider=%s)",
                    agent_def.name, model, provider_id,
                )
                try:
                    self.event_bus.publish(
                        "API_ENGINE_ACTIVE",
                        data={
                            "model": model,
                            "provider": provider_id,
                            "agent": agent_def.name,
                            "auto": True,
                        },
                    )
                except Exception:
                    logger.debug("API_ENGINE_ACTIVE publish failed", exc_info=True)
            return engine
        except Exception:
            logger.debug("Auto free-model routing failed", exc_info=True)
            return None

    def stop(self) -> None:
        """Stop the assistant and clean up resources.

        Saves assistant profile to memory before shutdown.
        Unloads model manager and ends conversation.
        Publishes APP_STOPPED event on completion.
        """
        if self._profile is not None:
            try:
                self._save_assistant_profile(self._profile)
            except Exception:
                logger.exception("Failed to save assistant profile during shutdown")
        self._started = False
        _sub_id = getattr(self, "_on_config_changed_sub_id", None)
        if _sub_id is not None:
            try:
                self.event_bus.unsubscribe(
                    "CONFIG_CHANGED", _sub_id
                )
            except Exception:
                logger.debug(
                    "CONFIG_CHANGED unsubscribe failed", exc_info=True
                )
            self._on_config_changed_sub_id = None
        if self._model_manager is not None:
            self._model_manager.unload()
        if self._engine is not None and hasattr(self._engine, "unload"):
            self._engine.unload()
        if self._memory is not None:
            self._memory.end_conversation()
            self._memory.close()
        self.event_bus.publish("SHUTDOWN_REQUESTED", data={})
        self.event_bus.publish("APP_STOPPED", data={})
        logger.info("Assistant stopped")

    # ------------------------------------------------------------------ #
    # Assistant Profile Management
    # ------------------------------------------------------------------ #
    def _load_assistant_profile(self) -> dict:
        """Load assistant profile from memory, fallback to config, fallback to default.

        Priority: Memory > Config > Safe Hardcoded Default.
        All loaded profiles are normalised to guarantee structural integrity.

        Profile Location:
        - Memory preference key: "assistant_profile"
        - Config section: "assistant" (nested dict or JSON string)

        Returns:
            Normalized profile dict with all required sections present.
        """
        if self._memory is not None:
            stored = self._memory.get_preference("assistant_profile")
            if stored:
                try:
                    profile = json.loads(stored)
                    return self._normalize_profile(profile)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Invalid assistant_profile JSON in memory (%s); falling back", exc)
        if self.config is not None:
            config_profile = self.config.get("assistant")
            if config_profile:
                return self._normalize_profile(config_profile)
        return self._normalize_profile(self._get_default_profile())

    def _get_default_profile(self) -> dict:
        """Return safe default assistant profile (neutral, no hardcoded name).

        Delegates to :data:`core.config_manager._DEFAULTS["assistant"]` so that
        the default profile has a single source of truth shared with the
        configuration fallback.
        """
        from core.config_manager import _DEFAULTS

        return copy.deepcopy(_DEFAULTS["assistant"])

    def _normalize_profile(self, profile: Any) -> dict:
        """Normalise a profile dict, filling missing sections/keys from defaults.

        Handles missing sections, missing keys, invalid JSON, ``None`` values,
        empty names, and malformed nested dictionaries. On any error a safe
        neutral default profile is returned.

        Args:
            profile: Any value to normalize. Invalid types fall back to defaults.

        Returns:
            A valid profile dict with all default values for missing keys.

        Validation Rules:
        - identity.name: Must be non-empty string (else None)
        - personality.humor: Must be number 0-1 (else 0.5)
        - personality.proactivity: Must be number 0-1 (else 0.3)
        - personality.traits: Must be list (else [])
        - expertise.areas: Must be list (else [])
        - All communication fields: Must be string (else defaults)
        - All behavior fields: Must be string (else defaults)
        """
        defaults = self._get_default_profile()

        if not isinstance(profile, dict):
            return copy.deepcopy(defaults)

        try:
            merged = self._deep_merge(defaults, profile)
        except (TypeError, ValueError):
            logger.warning("Failed to merge assistant profile; using safe default")
            return copy.deepcopy(defaults)

        identity = merged.get("identity")
        if isinstance(identity, dict):
            name = identity.get("name")
            if not name or not isinstance(name, str) or not name.strip():
                identity["name"] = None
            desc = identity.get("description")
            if not isinstance(desc, str):
                identity["description"] = ""

        personality = merged.get("personality")
        if isinstance(personality, dict):
            traits = personality.get("traits")
            if not isinstance(traits, list):
                personality["traits"] = []
            humor = personality.get("humor")
            if not isinstance(humor, (int, float)) or not 0 <= humor <= 1:
                personality["humor"] = 0.5
            proactivity = personality.get("proactivity")
            if not isinstance(proactivity, (int, float)) or not 0 <= proactivity <= 1:
                personality["proactivity"] = 0.3

        expertise = merged.get("expertise")
        if isinstance(expertise, dict):
            areas = expertise.get("areas")
            if not isinstance(areas, list):
                expertise["areas"] = []

        behavior = merged.get("behavior")
        if isinstance(behavior, dict):
            for key in ("response_approach", "uncertainty_handling", "question_style"):
                if not isinstance(behavior.get(key), str):
                    behavior[key] = defaults["behavior"][key]

        boundaries = merged.get("boundaries")
        if isinstance(boundaries, dict):
            custom = boundaries.get("custom_instructions")
            if not isinstance(custom, str):
                boundaries["custom_instructions"] = ""

        comm = merged.get("communication")
        if isinstance(comm, dict):
            for key in ("language", "tone", "formality", "response_style"):
                if not isinstance(comm.get(key), str):
                    comm[key] = defaults["communication"][key]

        return merged

    def _save_assistant_profile(self, profile: dict) -> None:
        """Save assistant profile to memory storage."""
        if self._memory is not None:
            self._memory.set_preference("assistant_profile", json.dumps(profile))

    def _deep_merge(self, base: dict, update: dict) -> dict:
        """Recursively merge *update* into *base*, returning a new dict."""
        result = copy.deepcopy(base)
        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result

    def _render_identity_text(self, profile: dict) -> str:
        """Render assistant's identity line from profile."""
        name = profile.get("identity", {}).get("name")
        if name:
            return f"{name}, the user's personal AI assistant."
        return "the user's personal AI assistant."

    def _build_custom_instructions(self, profile: dict) -> str:
        """Extract custom instructions from profile's 'behavior' and 'expertise' sections."""
        parts = []
        # Communication style
        comm = profile.get("communication", {})
        tone = comm.get("tone")
        if tone and tone != "neutral":
            parts.append(f"Speak in a {tone} tone.")
        formality = comm.get("formality")
        if formality and formality != "neutral":
            parts.append(f"Maintain a {formality} level of formality.")
        response_style = comm.get("response_style")
        if response_style and response_style != "balanced":
            parts.append(f"Provide {response_style} responses.")
        # Personality traits
        personality = profile.get("personality", {})
        traits = personality.get("traits")
        if traits:
            trait_str = ", ".join(traits)
            parts.append(f"You are characterized by being {trait_str}.")
        humor = personality.get("humor")
        if humor is not None and humor != 0.5:
            if humor < 0.5:
                parts.append("You are rarely humorous.")
            else:
                parts.append("You are sometimes humorous.")
        proactivity = personality.get("proactivity")
        if proactivity is not None and proactivity != 0.3:
            if proactivity < 0.3:
                parts.append("You are reactive rather than proactive.")
            else:
                parts.append("You are proactive and offer suggestions.")
        # Expertise areas
        expertise = profile.get("expertise", {})
        areas = expertise.get("areas")
        if areas:
            area_str = ", ".join(areas)
            parts.append(f"Your expertise includes {area_str}.")
        # Custom instructions
        custom = profile.get("boundaries", {}).get("custom_instructions", "")
        if custom:
            parts.append(custom)
        return "\n".join(parts)

    def get_assistant_profile(self) -> dict:
        """Return the current (normalised) assistant profile."""
        if self._profile is None:
            self._profile = self._load_assistant_profile()
        return self._profile

    # ------------------------------------------------------------------ #
    # Workspace & Project Context Management
    # ------------------------------------------------------------------ #
    def set_active_workspace(self, workspace_id: str) -> None:
        """Set the active workspace context.

        Loads the workspace from WorkspaceManager if available and updates
        the profile stack with the workspace's profile override.
        """
        if self._workspace_manager is None:
            self._active_workspace_id = workspace_id
            self._profile_stack = ProfileStack(self._profile)
            self._profile_stack.set_workspace(workspace_id, None)
            return

        workspace = self._workspace_manager.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError(f"Workspace not found: {workspace_id}")

        self._active_workspace_id = workspace_id
        self._active_project_id = None

        raw_override = workspace.profile_override
        if raw_override is not None:
            workspace_override = raw_override if isinstance(raw_override, dict) else json.loads(raw_override)
        else:
            workspace_override = None
        self._load_profile_stack().set_workspace(workspace_id, workspace_override)

        self.event_bus.publish(
            "WORKSPACE_CHANGED",
            data={"workspace_id": workspace_id},
        )

    def clear_active_workspace(self) -> None:
        """Clear the active workspace context, reverting to global profile."""
        self._active_workspace_id = None
        self._active_project_id = None

        stack = self._load_profile_stack()
        stack.clear_workspace()
        stack.clear_project()

        self.event_bus.publish(
            "WORKSPACE_CHANGED",
            data={"workspace_id": None},
        )

    def set_active_project(self, project_id: str) -> None:
        """Set the active project context within the active workspace.

        Loads the project from ProjectManager and updates the profile stack
        with the project's profile override.
        """
        if self._active_workspace_id is None:
            raise ValueError("No active workspace")

        if self._project_manager is None:
            self._active_project_id = project_id
            return

        project = self._project_manager.get_project(project_id)
        if project is None:
            raise ValueError(f"Project not found: {project_id}")

        if project.workspace_id != self._active_workspace_id:
            raise ValueError(f"Project {project_id} does not belong to workspace {self._active_workspace_id}")

        self._active_project_id = project_id

        raw_override = project.profile_override
        if raw_override is not None:
            project_override = raw_override if isinstance(raw_override, dict) else json.loads(raw_override)
        else:
            project_override = None
        self._load_profile_stack().set_project(project_id, project_override)

        self.event_bus.publish(
            "PROJECT_CHANGED",
            data={"project_id": project_id},
        )

    def clear_active_project(self) -> None:
        """Clear the active project context, reverting to workspace-level profile."""
        if self._context_manager is not None:
            self._context_manager.close_project()
        self._active_project_id = None

        self._load_profile_stack().clear_project()

        self.event_bus.publish(
            "PROJECT_CHANGED",
            data={"project_id": None},
        )

    def get_effective_profile(self) -> dict:
        """Get the resolved profile for current context.

        Resolves through ProfileStack layering:
        Global Profile → Workspace Override → Project Override

        Returns:
            Effective profile dict with applied override layers.
        """
        return self._load_profile_stack().get_effective_profile()

    def get_active_workspace_id(self) -> str | None:
        """Get the currently active workspace ID, if any.

        Returns:
            Workspace ID string or None if not set.
        """
        return self._active_workspace_id

    def get_active_project_id(self) -> str | None:
        """Get the currently active project ID, if any.

        Returns:
            Project ID string or None if not set.
        """
        return self._active_project_id

    def get_project_context(self, project_id: str | None = None) -> ProjectContext | None:
        """Get the runtime ProjectContext for a project.

        If *project_id* is None, returns the context for the currently
        open project.
        """
        if self._context_manager is None:
            return None
        return self._context_manager.get_context(project_id)

    def open_project(self, project_id: str) -> ProjectContext | None:
        """Open a project context for Chat/Knowledge integration.

        Sets the active project ID and creates a runtime ProjectContext.
        Does NOT start an Agent.  Does NOT require an active workspace —
        the project context is independent of workspace profile stacks.

        Args:
            project_id: The UUID of the project to open.

        Returns:
            ProjectContext or None if the project could not be opened.
        """
        if self._project_manager is not None:
            project = self._project_manager.get_project(project_id)
            if project is None:
                logger.warning("Cannot open project: not found: %s", project_id)
                return None
        self._active_project_id = project_id
        if self._active_workspace_id is not None:
            try:
                self.set_active_project(project_id)
            except ValueError:
                pass
        if self._context_manager is None:
            return None
        ctx = self._context_manager.open_project(project_id)
        return ctx

    def close_project(self) -> None:
        """Close the current project context."""
        if self._context_manager is not None:
            self._context_manager.close_project()
        self.clear_active_project()

    def assign_agent_to_project(
        self, project_id: str, agent_id: int, agent_name: str
    ) -> ProjectContext | None:
        """Assign a persisted Agent to an open project (runtime only).

        Does NOT start the Agent — just records the assignment.
        """
        if self._context_manager is None:
            return None
        return self._context_manager.assign_agent(project_id, agent_id, agent_name)

    def set_project_agent_state(
        self, state: AgentRuntimeState, task: str | None = None
    ) -> bool:
        """Update the runtime agent state for the currently open project.

        Called by the agent execution layer when an agent assigned to the
        open project starts, completes, or errors.
        """
        if self._context_manager is None or self._active_project_id is None:
            return False
        return self._context_manager.set_agent_runtime_state(
            self._active_project_id, state, task
        )

    def refresh_project_state(self) -> None:
        """Refresh the current project context from persistent storage."""
        if self._context_manager is None or self._active_project_id is None:
            return
        self._context_manager.refresh_from_project(self._active_project_id)

    @property
    def model_capabilities(self) -> dict[str, bool] | None:
        """Get the capabilities of the active model, if any.

        Returns:
            Dict mapping capability names to bool status, or None if no engine.
        """
        if self._engine is not None:
            return self._engine.model_capabilities.to_dict()
        return None

    def _load_profile_stack(self) -> ProfileStack:
        """Load or create the ProfileStack instance.

        Returns:
            ProfileStack instance for current assistant profile.
        """
        if not hasattr(self, '_profile_stack') or self._profile_stack is None:
            self._profile_stack = ProfileStack(self._profile)
        return self._profile_stack

    # ------------------------------------------------------------------ #
    # Conversation Context Management
    # ------------------------------------------------------------------ #
    def start_conversation(
        self,
        title: str = "",
        use_current_context: bool = True,
    ) -> int | None:
        """Start a new conversation with optional workspace/project context.

        Args:
            title: Optional title for the conversation
            use_current_context: If True, captures current workspace/project/effective profile

        Returns:
            Conversation ID, or None if no memory system available
        """
        if self._memory is None:
            return None

        if use_current_context:
            effective_profile = self.get_effective_profile()
            ws_id = self._active_workspace_id
            proj_id = self._active_project_id
        else:
            effective_profile = None
            ws_id = None
            proj_id = None

        return self._memory.start_conversation(
            title=title,
            workspace_id=ws_id,
            project_id=proj_id,
            profile_snapshot=effective_profile,
        )

    def get_conversation_context(self, conversation_id: int) -> tuple[str | None, str | None, dict | None]:
        """Load stored context for a conversation.

        Returns:
            Tuple of (workspace_id, project_id, profile_snapshot)
        """
        if self._memory is None:
            return None, None, None
        return self._memory.get_conversation_context(conversation_id)

    def set_conversation_context(
        self,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Set default context for new conversations.

        Updates the active workspace/project context.
        """
        if workspace_id is not None:
            self.set_active_workspace(workspace_id)
        if project_id is not None and self._active_workspace_id is not None:
            self.set_active_project(project_id)

    def update_assistant_profile(self, updates: dict) -> None:
        """Update the assistant profile with a nested deep merge.

        Only the keys present in *updates* are changed; all other sections
        and fields are preserved. The profile is normalized and persisted
        after every update.

        Args:
            updates: Partial profile dict with keys to modify.
                Example: {"identity": {"name": "Alex"}, "personality": {"humor": 0.7}}

        Side Effects:
        - Updates internal _profile cache
        - Persists via MemoryManager.set_preference("assistant_profile", ...)
        - Publishes PROFILE_UPDATED event with the updates dict
        """
        profile = self.get_assistant_profile()
        merged = self._deep_merge(profile, updates)
        self._profile = self._normalize_profile(merged)
        self._save_assistant_profile(self._profile)
        self.event_bus.publish("PROFILE_UPDATED", data=updates)
        if getattr(self, '_profile_stack', None) is not None:
            self._profile_stack.update_global(self._profile)

    def _build_project_context_prompt(self) -> str:
        """Build a safe, read-only project context section for the system prompt.

        Returns an empty string when no project is open, so normal chat
        behaviour is unchanged.

        The project metadata is treated as DATA, not as instructions —
        it cannot override security rules or tool restrictions.
        """
        ctx = self.get_project_context()
        if ctx is None:
            return ""

        lines: list[str] = []
        lines.append("PROJECT CONTEXT")
        lines.append("The user currently has the following project open.")
        lines.append("")
        lines.append(f"Project ID: {ctx.project_id}")
        lines.append(f"Project Name: {ctx.name}")
        desc = ctx.description or "(no description)"
        lines.append(f"Project Description: {desc}")
        ws = ctx.workspace_path or "(not set)"
        lines.append(f"Workspace Path: {ws}")

        if ctx.settings:
            lines.append(f"Project Settings: {json.dumps(ctx.settings, indent=2)}")
        else:
            lines.append("Project Settings: (none)")

        lines.append("")
        lines.append("Use this information when answering questions about the current project.")
        lines.append("Do not claim knowledge of files or project contents that have not been provided.")
        return "\n".join(lines)

    def _render_system_prompt(self, profile: dict, text: str = "") -> str:
        """Render the full system prompt from the profile via the template."""
        identity_text = self._render_identity_text(profile)
        description = profile.get("identity", {}).get("description", "") or ""
        custom_instructions = self._build_custom_instructions(profile)
        description_block = f"\n{description}\n" if description else ""
        custom_instructions_block = (
            f"\n{custom_instructions}\n" if custom_instructions else ""
        )
        return SYSTEM_PROMPT_TEMPLATE.format(
            identity_text=identity_text,
            description_block=description_block,
            custom_instructions_block=custom_instructions_block,
        )

    def process_message(
        self,
        text: str,
        conversation_id: str | None = None,
        cancel_event: threading.Event | None = None,
        token_callback: Callable[[str], None] | None = None,
        pulse_callback: Callable[[], None] | None = None,
        publish_fn: EventCallback | None = None,
        images: list[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Process a user message and return the LLM-generated response.

        *cancel_event* — thread-safe flag checked cooperatively by the
        generation loop.  When set, generation stops at the next token
        boundary and the partial response is returned.

        *token_callback* — optional callable invoked for each streamed
        token.  Provided by the caller so tokens can reach the GUI via
        Qt Signal rather than solely through the EventBus.

        *pulse_callback* — optional callable invoked between tokens so the
        caller can pump its event loop (e.g. ``QApplication.processEvents()``)
        and remain responsive while streaming.

        *publish_fn* — optional replacement for ``self.event_bus.publish``.
        When supplied, all EventBus publications inside this method and the
        downstream generation path are routed through *publish_fn* instead.
        This allows a worker thread to suppress EventBus publication
        entirely (pass ``None`` or a no-op), because EventBus callbacks
        execute on the publishing thread and subscriber handlers in MainWindow
        call Qt widget methods that must run on the GUI thread.  Default
        behaviour (``publish_fn=None``) uses ``self.event_bus.publish``,
        preserving backward compatibility.

        *images* — optional list of base64-encoded images attached to the
        message.  Only used when the active model supports vision; ignored
        otherwise (a note is returned to the user instead).

        *should_cancel* — optional cooperative cancellation predicate
        checked between tokens (alternative to *cancel_event*).

        Returns an empty string for empty or whitespace-only input.

        """
        # Early exit for empty or whitespace-only input
        if not text or not text.strip():
            if not images:
                return ""
            text = "Describe this image."

        self._cancel_event = cancel_event
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                self.event_bus.publish(event_type, data=data)

        cid = conversation_id or f"conv-{datetime.now(UTC).isoformat()}"
        logger.info("Received message (conv=%s): %s", cid, text)

        conversation_profile: dict | None = None

        if self._memory is not None:
            self._memory.add_user_message(text)
            pub("MEMORY_UPDATED", data={"type": "user_message"})
            # Try to get conversation context if we have a conversation
            try:
                conv_ctx = self._memory.get_conversation_context(self._memory.conversation_id or 0)
                if conv_ctx and conv_ctx[2]:
                    conversation_profile = conv_ctx[2]
            except (AttributeError, TypeError):
                pass

        pub(
            "USER_MESSAGE_RECEIVED",
            data={"text": text, "conversation_id": cid},
        )

        response = self._maybe_resolve_pending_memory(text, publish_fn=publish_fn)
        if response is None:
            command_response = self._handle_slash_command(text, publish_fn=publish_fn)
            if command_response is None:
                command_response = self._handle_memory_intent(text)
            response = (
                command_response
                if command_response is not None
                else self._generate_response(
                    text,
                    conversation_profile,
                    cancel_event=cancel_event,
                    token_callback=token_callback,
                    pulse_callback=pulse_callback,
                    publish_fn=publish_fn,
                    images=images,
                    should_cancel=should_cancel,
                )
            )
        was_cancelled = (cancel_event is not None and cancel_event.is_set())
        if not was_cancelled and self._memory is not None:
            self._memory.add_assistant_message(response)
            pub("MEMORY_UPDATED", data={"type": "assistant_message"})

        if not was_cancelled:
            pub(
                "AI_RESPONSE_RECEIVED",
                data={
                    "text": response,
                    "conversation_id": cid,
                    "model": self._engine.model_name if self._engine else "stub",
                },
            )

        return response

    def _generate_response(
        self,
        text: str,
        conversation_profile: dict | None = None,
        cancel_event: threading.Event | None = None,
        token_callback: Callable[[str], None] | None = None,
        pulse_callback: Callable[[], None] | None = None,
        publish_fn: EventCallback | None = None,
        images: list[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> str:
        """Generate a response via native tool calling, LLM engine, or stub fallback.

        When the active model supports native tool/function calling AND the
        current message is likely to require a tool, the preferred path is
        :meth:`_generate_with_native_tools`.  Ordinary conversational messages
        (e.g. ``"Who was Nikola Tesla?"``) use the normal chat path with the
        model's native chat template instead — they are NOT routed through tool
        calling merely because the model is tool-capable.

        *cancel_event* — cooperative cancellation flag checked in the streaming
        loop.  When set, generation stops at the next token boundary.

        *token_callback* — invoked for each streamed token so the caller can
        relay tokens to the GUI via Qt Signal.

        *pulse_callback* — invoked between tokens so the caller can pump its
        event loop and remain responsive while streaming.

        *publish_fn* — see :meth:`process_message`.

        *images* — optional base64 image list for multimodal (vision) models.
        When the active model lacks vision support the images are ignored and
        an explanatory note is returned instead of a hallucinated description.

        *should_cancel* — optional cooperative cancellation predicate checked
        between tokens (alternative to *cancel_event*).
        """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                self.event_bus.publish(event_type, data=data)

        lowered = text.strip().lower()

        # Native tool-calling path — only when a tool is actually required, so
        # that ordinary chat does not receive tool-call instructions.
        if (
            self._tools is not None
            and self._engine is not None
            and self._engine.is_ready
            and self._engine.supports_tool_calling
            and self._message_needs_tool(lowered)
        ):
            native_result = self._generate_with_native_tools(text, conversation_profile, cancel_event=cancel_event, pulse_callback=pulse_callback, publish_fn=publish_fn)
            if native_result is not None:
                return native_result

        # Fallback: heuristic tool detection (non-native path).
        if self._tools is not None and lowered:
            tool_action = self._detect_tool_action(lowered)
            if tool_action:
                tool_name, params = tool_action
                result = self.run_tool(tool_name, params, publish_fn=publish_fn)
                if result.success:
                    return self._format_tool_result(tool_name, result)
                if result.error == "ConfirmationRequired" or not result.success:
                    return self._format_tool_failure(tool_name, result)

        if self._engine is None or not self._engine.is_ready:
            logger.error("No LLM engine configured — inference unavailable")
            return (
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and select a local GGUF model."
            )

        if not _is_test_mode() and getattr(self._engine, "load_status", "") == "stub_mode":
            logger.error("Engine is in stub mode — refusing to generate fake response")
            return (
                "GGUF inference runtime is unavailable. "
                "Install llama-cpp-python and select a local GGUF model."
            )

        # Use conversation profile if provided, otherwise use effective profile
        profile_to_use = conversation_profile if conversation_profile is not None else self.get_effective_profile()
        # Build base system prompt from effective profile (global + workspace + project overrides)
        system_prompt = self._render_system_prompt(profile_to_use, text)
        # Inject active project context as authoritative application data
        project_ctx = self._build_project_context_prompt()
        if project_ctx:
            system_prompt = f"{system_prompt}\n\n{project_ctx}\n"
        history: list[dict[str, str]] = []
        if self._memory is not None:
            history = self._memory.get_history()
            relevant_memories = self._memories_for_prompt(text)
            if relevant_memories:
                mem_text = "\n".join(m["content"] for m in relevant_memories)
                system_prompt = f"{system_prompt}\n\nRelevant context:\n{mem_text}\n"

        if self._rag_pipeline is not None:
            try:
                results, rag_context = self._rag_pipeline.retrieve_context(text)
                if rag_context:
                    system_prompt = f"{system_prompt}\n\nKnowledge context:\n{rag_context}\n"
                    logger.info("RAG: injected %d source chunk(s)", len(results))
                    pub("RAG_CONTEXT_INJECTED", data={"chunks": len(results)})
            except Exception:
                logger.exception("RAG context retrieval failed")

        # Build messages list for the model's native chat template.
        # The system message carries the full rendered system prompt (identity,
        # project context, memories, RAG).  History messages already carry
        # their "role" and "content" keys.  The final user message is the
        # current input.
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history[:-1] if history else [])
        final_user_message: dict[str, Any] = {"role": "user", "content": text}
        if images:
            # Vision gate: only attach images when the active model truly
            # supports multimodal inference (model + attached projector).
            if getattr(self._engine, "supports_vision", False):
                final_user_message["images"] = list(images)
                logger.info(
                    "Vision: %d image(s) attached to message", len(images)
                )
            else:
                pub("VISION_REJECTED", data={"images": len(images), "reason": "model_no_vision"})
                return (
                    "The active model does not support image understanding. "
                    "Load a vision-capable model (with its mmproj projector) "
                    "to analyze images."
                )
        messages.append(final_user_message)

        cfg = self._build_generation_config()

        # Context budget enforcement: truncate prompt if it would exceed the model's
        # context window. This prevents silent truncation by the model and ensures
        # we stay well within safe limits with room for generation.
        messages = self._enforce_context_budget(messages, cfg)

        total_prompt_chars = sum(len(m.get("content", "")) for m in messages)
        session = InferenceSession(prompt=text)
        pub(
            "GENERATION_STARTED", data={"prompt_length": total_prompt_chars}
        )
        try:
            tokens: list[str] = []
            for token in self._engine.generate_chat_stream(messages, config=cfg):
                if pulse_callback is not None:
                    pulse_callback()
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("Generation cancelled at token boundary")
                    pub(
                        "GENERATION_CANCELLED", data={"tokens_generated": len(tokens)}
                    )
                    partial = "".join(tokens)
                    partial = self._post_process_response(partial)
                    session.fail("cancelled")
                    return partial
                if should_cancel is not None and should_cancel():
                    logger.info("Generation cancelled (predicate) at token boundary")
                    pub(
                        "GENERATION_CANCELLED", data={"tokens_generated": len(tokens)}
                    )
                    partial = "".join(tokens)
                    partial = self._post_process_response(partial)
                    session.fail("cancelled")
                    return partial
                tokens.append(token)
                if token_callback is not None:
                    token_callback(token)
                pub("GENERATION_TOKEN", data={"token": token})
            response = "".join(tokens)
            response = self._post_process_response(response)
            session.complete()
            pub("GENERATION_COMPLETED", data={
                "tokens_used": len(tokens),
                "response_length": len(response),
            })
            return response
        except Exception as exc:
            session.fail(str(exc))
            pub("GENERATION_FAILED", data={"error": str(exc)})
            logger.error("Generation failed: %s", exc)
            return (
                f"Model failed to generate a response: {exc}. "
                "Ensure the model file is valid and llama-cpp-python is properly installed."
            )

    def _post_process_response(self, response: str) -> str:
        """Strip any fabricated future conversation turns from the LLM response.

        Some models (e.g. Qwen2.5-Coder) may continue the transcript format
        by generating additional ``User: ...`` / ``Assistant: ...`` turns after
        the actual answer.  This method truncates the response at the first
        occurrence of a new user turn marker, so only the assistant's reply
        to the current user message is returned.
        """
        import re

        # Match a line that starts with "User:" — the turn delimiter in our
        # transcript-style prompt.  We stop at the first such occurrence.
        match = re.search(r"\nUser:", response)
        if match is not None:
            response = response[: match.start()]
        response = response.rstrip()
        return response

    # ------------------------------------------------------------------ #
    # Tool call detection (Phase 5 stub NLP — replaced by real planner/agents in Phase 9)
    # ------------------------------------------------------------------ #
    def _detect_tool_action(self, lowered: str) -> tuple[str, dict] | None:
        """Heuristically decide whether *lowered* should invoke a tool."""
        import re

        if "system" in lowered or "cpu" in lowered:
            return ("system_info", {})
        # "ram" as standalone word (not substring like "program")
        if re.search(r"\bram\b", lowered):
            return ("system_info", {})

        # File-read intent must be detected before application-launch because
        # "open" and "read" appear in both patterns.
        # Priority 1: "open file X", "read file X"
        english_file_match = re.search(
            r"(?:open|read)\s+file\s+(.+)",
            lowered,
        )
        if english_file_match:
            return ("read_file", {"path": english_file_match.group(1).strip()})

        # Priority 2: "open X" or "read X" where X appears to be a file (has extension)
        open_read_with_ext = re.search(
            r"^(?:open|read)\s+(\S+\.\S+)$",
            lowered,
        )
        if open_read_with_ext:
            return ("read_file", {"path": open_read_with_ext.group(1)})

        # Priority 3: Application-launch patterns
        app_match = re.search(
            r"(?:launch|open|start|run)\s+(?:program\s+)?(.+)",
            lowered,
        )
        if app_match:
            return ("open_application", {"program": app_match.group(1).strip()})

        write_match = re.search(
            r"(?:write|create|save)\s+(?:a\s+|the\s+)?file\b.*",
            lowered,
        )
        if write_match:
            return ("write_file", {"path": lowered})

        return None

    def _message_needs_tool(self, lowered: str) -> bool:
        """Return True when *lowered* likely requires a tool call.

        Reuses :meth:`_detect_tool_action` so the same heuristic gates both
        the native tool-calling path and (indirectly) the fallback heuristic
        path.  Ordinary conversational messages that do not match any
        tool-requiring pattern return ``False`` so they use the normal chat
        generation path instead.
        """
        return self._detect_tool_action(lowered) is not None

    def _generate_with_native_tools(
        self,
        text: str,
        conversation_profile: dict | None = None,
        cancel_event: threading.Event | None = None,
        pulse_callback: Callable[[], None] | None = None,
        publish_fn: EventCallback | None = None,
    ) -> str | None:
        """Generate a response using native LLM tool calling.

        Returns the final response string, or ``None`` to signal the caller
        to fall back to the existing heuristic + LLM path.

        The flow:
            1. Build system prompt with tool schemas injected.
            2. Call ``engine.generate_with_tools()``.
            3. Parse response for tool calls.
            4. Execute each call through ``ToolRegistry`` (→ SecurityLayer).
            5. Inject results back into the conversation prompt.
            6. Repeat until no tool calls or max iterations reached.

        *publish_fn* — see :meth:`process_message`.
        """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                self.event_bus.publish(event_type, data=data)

        from ai.engine.tool_calling import (
            _MAX_TOOL_CALL_ITERATIONS,
            ToolSchemaExporter,
            format_tool_instructions,
            format_tool_result,
        )

        if self._engine is None or self._tools is None:
            return None
        if not self._engine.is_ready or not self._engine.supports_tool_calling:
            return None

        # Build system prompt from effective profile
        profile_to_use = (
            conversation_profile
            if conversation_profile is not None
            else self.get_effective_profile()
        )
        system_prompt = self._render_system_prompt(profile_to_use, text)

        # Export tool schemas — single source of truth (ToolRegistry metadata)
        exporter = ToolSchemaExporter(registry=self._tools)
        schemas = exporter.export_schemas_for_llm()
        tool_instructions = format_tool_instructions(schemas)
        if tool_instructions:
            system_prompt = f"{system_prompt}\n\n{tool_instructions}\n"

        # Inject project context
        project_ctx = self._build_project_context_prompt()
        if project_ctx:
            system_prompt = f"{system_prompt}\n\n{project_ctx}\n"

        # Conversation history
        history: list[dict[str, str]] = []
        if self._memory is not None:
            history = self._memory.get_history()
            relevant_memories = self._memories_for_prompt(text)
            if relevant_memories:
                mem_text = "\n".join(m["content"] for m in relevant_memories)
                system_prompt = f"{system_prompt}\n\nRelevant context:\n{mem_text}\n"

        # RAG context
        if self._rag_pipeline is not None:
            try:
                results, rag_context = self._rag_pipeline.retrieve_context(text)
                if rag_context:
                    system_prompt = f"{system_prompt}\n\nKnowledge context:\n{rag_context}\n"
                    logger.info("RAG: injected %d source chunk(s)", len(results))
                    pub(
                        "RAG_CONTEXT_INJECTED", data={"chunks": len(results)}
                    )
            except Exception:
                logger.exception("RAG context retrieval failed")

        cfg = self._build_generation_config()

        prompt = build_response_prompt(
            system_prompt=system_prompt,
            history=history[:-1] if history else [],
            user_input=text,
        )

        if self._engine is not None and self._engine.is_ready:
            n_ctx = self.config.get("ai.n_ctx", 4096)
            generation_reserve = max(int(n_ctx * 0.25), cfg.max_tokens)
            effective_context = max(512, n_ctx - generation_reserve)

            prompt_tokens = self._count_tokens_simple(prompt)
            if prompt_tokens > effective_context:
                truncated_history = self._truncate_history_for_context(
                    history, text, effective_context, system_prompt
                )
                prompt = build_response_prompt(
                    system_prompt=system_prompt,
                    history=truncated_history,
                    user_input=text,
                )

        session = InferenceSession(prompt=prompt)
        pub(
            "GENERATION_STARTED", data={"prompt_length": len(prompt)}
        )

        try:
            accumulated_text: list[str] = []
            for _iteration in range(_MAX_TOOL_CALL_ITERATIONS):
                if cancel_event is not None and cancel_event.is_set():
                    logger.info("Native tool calling cancelled")
                    pub("GENERATION_CANCELLED", data={})
                    return "".join(accumulated_text).strip()
                if pulse_callback is not None:
                    pulse_callback()
                response = self._engine.generate_with_tools(
                    prompt, schemas, config=cfg
                )

                if response.has_tool_calls:
                    tool_result_strs: list[str] = []
                    for tc in response.tool_calls:
                        tool_result = self.run_tool(tc.name, tc.arguments, publish_fn=publish_fn)
                        result_str = format_tool_result(tc.name, tool_result)
                        tool_result_strs.append(result_str)

                    accumulated_text.append(response.text)
                    observations = "\n".join(tool_result_strs)
                    prompt = (
                        f"{prompt}{response.text}\n"
                        f"{observations}\n"
                        f"[ASSISTANT:]"
                    )
                else:
                    accumulated_text.append(response.text)
                    final = "".join(accumulated_text).strip()
                    final = self._post_process_response(final)
                    session.complete()
                    pub(
                        "GENERATION_COMPLETED",
                        data={
                            "tokens_used": len(final),
                            "response_length": len(final),
                        },
                    )
                    return final

            # Max iterations reached without a final text-only response
            final = "".join(accumulated_text).strip()
            final = self._post_process_response(final)
            session.complete()
            pub(
                "GENERATION_COMPLETED",
                data={
                    "tokens_used": len(final),
                    "response_length": len(final),
                },
            )
            logger.warning(
                "Native tool calling reached max iterations (%d)",
                _MAX_TOOL_CALL_ITERATIONS,
            )
            return final
        except Exception as exc:
            session.fail(str(exc))
            pub(
                "GENERATION_FAILED", data={"error": str(exc)}
            )
            logger.error("Native tool calling failed: %s", exc)
            return None

    def _format_tool_result(self, tool_name: str, result: ToolResult) -> str:
        if tool_name == "system_info":
            d = result.data
            return (
                f"📊 System information:\n"
                f"  CPU: {d.get('cpu_percent')}%\n"
                f"  RAM: {d.get('ram_used_percent')}% ({d.get('ram_total_gb')} GB)\n"
                f"  Disk: {d.get('disk_used_percent')}% ({d.get('disk_total_gb')} GB)\n"
                f"  GPU: {d.get('gpu')}"
            )
        if tool_name == "read_file":
            content = result.data.get("content", "")[:500]
            return f"📄 File content:\n```\n{content}\n```"
        if tool_name == "open_application":
            return f"✅ {result.message}"
        if tool_name == "search_files":
            results = result.data.get("results", [])
            names = [r["name"] for r in results[:10]]
            return f"🔍 Found {len(results)} file(s): {', '.join(names)}"
        return result.message

    def _format_tool_failure(self, tool_name: str, result: ToolResult) -> str:
        if result.error == "ConfirmationRequired":
            return f"⚠️ The action '{tool_name}' requires your confirmation. Do you allow it?"
        return f"❌ Error executing '{tool_name}': {result.message}"

    def _stub_response(self, text: str) -> str:
        lowered = text.strip().lower()
        if lowered in ("hi", "hello"):
            return "Hello! How can I help you?"
        return (
            "The AI model is not loaded yet. "
            "Open Settings → Model → Manage Models to download a .gguf model, "
            "or run the Setup Wizard if this is your first start."
        )

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def knowledge(self) -> KnowledgeBase | None:
        return self._knowledge

    def index_project_knowledge(self, project_id: str) -> int:
        """Index knowledge from a project's workspace directory.

        Uses the project's workspace path to find and index .md and .txt
        files into the knowledge base.  This allows project-specific RAG
        context without polluting the global knowledge store.

        Args:
            project_id: The project whose workspace to index.

        Returns:
            Number of chunks indexed.  Returns 0 if knowledge base or
            project manager is unavailable or workspace path is missing.
        """
        if self._knowledge is None or self._project_manager is None:
            return 0
        proj = self._project_manager.get_project(project_id)
        if proj is None or not proj.workspace_path:
            return 0
        from pathlib import Path
        ws = Path(proj.workspace_path)
        if not ws.exists() or not ws.is_dir():
            return 0
        try:
            count = self._knowledge.index_directory(ws)
            logger.info("Indexed %d chunk(s) from project workspace: %s", count, ws)
            self.event_bus.publish(
                "KNOWLEDGE_INDEXED",
                data={"project_id": project_id, "chunks": count, "directory": str(ws)},
            )
            return count
        except Exception:
            logger.exception("Failed to index project knowledge")
            return 0

    @property
    def memory(self) -> MemoryManager | None:
        return self._memory

    @property
    def agent_repository(self) -> AgentRepository | None:
        return self._agent_repository

    @property
    def model_name(self) -> str:
        if self._engine is not None:
            name = self._engine.model_name
            if name and name != "stub":
                return name
        return "No model loaded"

    @property
    def engine_status(self) -> str:
        """Human-readable engine status for the UI ('ready' / 'not_loaded' / ...)."""
        if self._engine is None:
            return "not_configured"
        return str(getattr(self._engine, "load_status", "unknown"))

    @property
    def is_model_ready(self) -> bool:
        """True when a real (non-stub) model is loaded and ready for inference."""
        if self._engine is None:
            return False
        if not getattr(self._engine, "is_ready", False):
            return False
        return getattr(self._engine, "load_status", "") not in ("stub_mode", "not_configured")

    def switch_model(self, model_name: str) -> None:
        if self._model_manager is None:
            raise RuntimeError("ModelManager not available")
        model = self._model_manager.activate_model(model_name)
        self.config.set("ai.model_name", model_name)
        if self._engine is not None:
            self._engine.configure(self._model_manager)
        self.event_bus.publish(
            "MODEL_LOADED",
            data={"model": model.name, "path": str(model.path)},
        )
        logger.info("Switched to model '%s'", model.name)

    def save_preference(self, key: str, value: str, category: str = "user") -> None:
        """Persist a user preference and mirror it into durable memory.

        Args:
            key: Preference key name.
            value: Preference value as string.
            category: Storage category (default: "user").
        """
        if self._memory is not None:
            self._memory.set_preference(key, value, category)

    @property
    def profile(self) -> dict:
        """Get the current assistant profile (global, pre-stack-resolution).

        Use :meth:`get_effective_profile` for the profile with workspace/project
        overrides applied.
        """
        return self._profile

    # ------------------------------------------------------------------ #
    # Tool execution
    # ------------------------------------------------------------------ #
    def list_tools(self) -> list[dict]:
        if self._tools is None:
            return []
        return self._tools.list_tools()

    def run_tool(
        self,
        name: str,
        params: dict | None = None,
        publish_fn: EventCallback | None = None,
    ) -> ToolResult:
        """Execute a registered tool by name.

        The tool registry handles confirmation gates for risky actions.
        Raises :class:`RuntimeError` if no registry is configured.

        *publish_fn* — optional callable that replaces ``self.event_bus.publish``
        for the ``TOOL_RESULT`` event.  When supplied (e.g. by
        :meth:`_generate_response` running on a worker QThread), the event is
        routed through it so it reaches the GUI thread via Qt signals instead
        of being called directly on the worker thread.
        """
        if self._tools is None:
            return ToolResult(
                success=False,
                message="Nema konfigurisan tool registry",
                tool_name=name,
                error="NoToolRegistry",
            )
        result = self._tools.execute(name, params or {})
        if publish_fn is not None:
            publish_fn(
                "TOOL_RESULT",
                {"tool": name, "success": result.success, "result": result.to_dict()},
            )
        else:
            self.event_bus.publish(
                "TOOL_RESULT",
                data={"tool": name, "success": result.success, "result": result.to_dict()},
            )
        return result

    # ------------------------------------------------------------------ #
    # Knowledge (RAG) — Phase 8
    # ------------------------------------------------------------------ #
    def run_knowledge_search(self, query: str, top_k: int = 3) -> tuple[str, list]:
        """Retrieve relevant knowledge for *query*.

        Returns ``(formatted_context, results)``.  When no RAG pipeline is
        configured, returns empty context.
        """
        if self._rag_pipeline is None:
            return "", []
        results, context = self._rag_pipeline.retrieve_context(query)
        self.event_bus.publish(
            "KNOWLEDGE_RESULT",
            data={"query": query, "chunks": len(results), "context": context},
        )
        return context, results

    # ------------------------------------------------------------------ #
    # Agent System — Phase 9
    # ------------------------------------------------------------------ #
    def _resolve_assigned_agent(self, goal: str) -> Any:
        """Resolve the agent assigned to the active project, if any.

        - Checks :class:`ProjectContextManager` for the currently open project.
        - If the project has a valid :class:`AgentAssignment`, resolves the
          persisted :class:`Agent` by ``agent_id`` from the repository.
        - Stale assignments (deleted agent) or disabled agents cause a fallback
          to ``AgentSelector.select_for_goal`` by returning ``None``.

        Returns the resolved :class:`Agent` or ``None`` when no valid
        assignment exists.
        """
        if self._context_manager is None or self._agent_repository is None:
            return None
        ctx = self._context_manager.get_context(self._active_project_id)
        if ctx is None or ctx.agent_assignment is None:
            return None
        assignment = ctx.agent_assignment
        agent_def = self._agent_repository.get_agent(assignment.agent_id)
        if agent_def is None:
            logger.warning(
                "Project '%s' has stale agent assignment (agent_id=%d no longer exists) "
                "— falling back to AgentSelector",
                self._active_project_id, assignment.agent_id,
            )
            return None
        if not agent_def.enabled:
            logger.warning(
                "Project '%s' assigned agent '%s' is disabled — "
                "falling back to AgentSelector",
                self._active_project_id, agent_def.name,
            )
            return None
        logger.info(
            "Project '%s' using assigned agent '%s' (id=%d) for goal: %s",
            self._active_project_id, agent_def.name, agent_def.id, goal,
        )
        return agent_def

    def run_agent_plan(
        self,
        goal: str,
        max_steps: int = 10,
        project_id: str | None = None,
        cancel_event: threading.Event | None = None,
        publish_fn: EventCallback | None = None,
    ) -> str:
        """Execute *goal* via a single agent over the secured tool registry, with
        assistant profile context forwarded to the planner.

        If an :class:`AgentRepository` is available, attempts to select a persisted,
        enabled agent for *goal*.  Falls back to the generic 'assistant-agent'
        when no suitable persisted agent is found.

        If *project_id* is provided, the project context is opened before
        execution so that the agent has access to the correct project scope.

        *cancel_event* — optional :class:`threading.Event` for cooperative
        cancellation.  When set, the agent stops at the next safe checkpoint.

        *publish_fn* — optional callable that replaces
        ``self.event_bus.publish``.  When supplied (e.g. by a QThread-based
        worker), all EventBus events are routed through it so they can be
        marshalled to the GUI thread via Qt signals instead of being called
         directly on the worker thread.
         """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            pub = self.event_bus.publish
        self._cancel_event = cancel_event
        if self._tools is None:
            return ""
        if project_id is not None:
            self._active_project_id = project_id
            if self._context_manager is not None:
                self._context_manager.open_project(project_id)
        from agent.base import BaseAgent
        from agent.planner import LLMPlanner, StubPlanner

        agent_def: Agent | None = None
        if self._agent_repository is not None:
            assigned = self._resolve_assigned_agent(goal)
            if assigned is not None:
                agent_def = assigned
            else:
                from agent.selector import AgentSelector

                selector = AgentSelector(self._agent_repository)
                agent_def = selector.select_for_goal(goal)

        if agent_def is not None:
            name = agent_def.name or "assistant-agent"
            system_prompt = agent_def.system_prompt
            agent_engine = self._resolve_agent_engine(agent_def)
            planner = self._planner or (
                LLMPlanner(
                    agent_engine, tool_registry=self._tools,
                    profile=self.get_effective_profile(),
                    system_prompt=system_prompt,
                    tool_whitelist=agent_def.tool_whitelist,
                    generation_config=self._build_generation_config(),
                )
                if agent_engine is not None
                else StubPlanner(tool_registry=self._tools, system_prompt=system_prompt, tool_whitelist=agent_def.tool_whitelist)
            )
            if self._planner is not None:
                self._planner.profile = self.get_effective_profile()
                if hasattr(self._planner, "_generation_config"):
                    self._planner._generation_config = self._build_generation_config()

            # Step 6: retrieve agent-scoped memories and inject into planner
            memory_context = ""
            if self._memory is not None and agent_def.id is not None and self._memory_enabled():
                relevant_memories = self._memory.build_agent_context(
                    agent_def.id, goal, max_memories=5,
                )
                if relevant_memories:
                    memory_context = "\n".join(
                        f"[{m['type']}] {m['content']}" for m in relevant_memories
                    )

            if memory_context:
                planner.memory_context = memory_context

            # Step 6c: inject project context (if any) into the planner
            project_context = self._build_project_context_prompt()
            if project_context:
                planner.project_context = project_context

            # Step 6b: pre-retrieve Knowledge (RAG) context and inject into planner
            knowledge_context = ""
            if self._rag_pipeline is not None:
                try:
                    _, knowledge_context = self._rag_pipeline.retrieve_context(goal)
                except Exception:
                    logger.exception("Knowledge pre-retrieval failed for agent plan")

            if knowledge_context:
                planner.knowledge_context = knowledge_context

            agent = BaseAgent(
                name=name,
                role="executor",
                goal=goal,
                planner=planner,
                tool_registry=self._tools,
                event_bus=self.event_bus,
                assistant=self,
                system_prompt=agent_def.system_prompt,
                model_name=agent_def.model_name,
                tool_whitelist=agent_def.tool_whitelist,
                permission_profile=agent_def.permission_profile,
                enabled=agent_def.enabled,
                agent_id=agent_def.id,
                verifier=self._verifier,
                publish_fn=pub,
            )

            # Step 6: attach AgentMemory integration layer
            if self._memory is not None and agent_def.id is not None:
                from agent.memory import AgentMemory
                agent_memory = AgentMemory(
                    memory_manager=self._memory,
                    agent_id=agent_def.id,
                    agent_name=name,
                    memory_enabled=self._memory_enabled(),
                )
                agent.set_agent_memory(agent_memory)

            logger.info("Agent '%s' selected for goal (Step 3): %s", name, goal)

            if agent_def is not None and agent_def.id is not None:
                self.set_project_agent_state(AgentRuntimeState.ACTIVE, goal)

            failed = False
            try:
                result = agent.run(goal, max_steps=max_steps, cancel_event=cancel_event)
            except Exception:
                logger.exception("Agent '%s' run failed", name)
                failed = True
                result = ""

            if agent_def is not None and agent_def.id is not None:
                if failed:
                    self.set_project_agent_state(AgentRuntimeState.ERROR, goal)
                else:
                    self.set_project_agent_state(AgentRuntimeState.TASK_COMPLETED, goal)

            # Step 6: controlled memory creation from execution result
            # Only create memory if there were no failures and Memory is ON.
            if (
                agent._agent_memory is not None
                and agent._agent_memory.is_enabled
                and agent_def.id is not None
            ):
                done_count = len([
                    t for t in agent._tasks if t.status.value == "done"
                ])
                if done_count > 0 and not any(
                    t.status.value == "failed" for t in agent._tasks
                ):
                    summary = agent.summarize()
                    agent.remember_memory(
                        content=f"Task completed: {goal}\nResult: {summary}",
                        mem_type="project_info",
                        importance=0.7,
                    )

            # Step 8: publish verification result
            if agent.verification_result is not None:
                vr = agent.verification_result
                pub(
                    "AGENT_VERIFICATION",
                    data={
                        "agent_name": name,
                        "agent_id": agent_def.id,
                        "status": vr.status.value,
                        "summary": vr.summary,
                        "issues": vr.issues,
                    },
                )

            return result
        else:
            planner = self._planner or (
                LLMPlanner(self._engine, tool_registry=self._tools, profile=self.get_effective_profile(), generation_config=self._build_generation_config())
                if self._engine is not None
                else StubPlanner(tool_registry=self._tools)
            )
            if self._planner is not None:
                self._planner.profile = self.get_effective_profile()
                if hasattr(self._planner, "_generation_config"):
                    self._planner._generation_config = self._build_generation_config()

            # Pre-retrieve Knowledge (RAG) context and inject into planner
            if self._rag_pipeline is not None:
                try:
                    _, knowledge_context = self._rag_pipeline.retrieve_context(goal)
                    if knowledge_context:
                        planner.knowledge_context = knowledge_context
                except Exception:
                    logger.exception("Knowledge pre-retrieval failed for agent plan")

            # Inject project context (if any) into the planner
            project_context = self._build_project_context_prompt()
            if project_context:
                planner.project_context = project_context

            agent = BaseAgent(
                name="assistant-agent",
                role="executor",
                goal=goal,
                planner=planner,
                tool_registry=self._tools,
                event_bus=self.event_bus,
                assistant=self,
                verifier=self._verifier,
                publish_fn=pub,
            )
        result = agent.run(goal, max_steps=max_steps, cancel_event=cancel_event)
        if agent.verification_result is not None:
            vr = agent.verification_result
            pub(
                "AGENT_VERIFICATION",
                data={
                    "agent_name": "assistant-agent",
                    "agent_id": None,
                    "status": vr.status.value,
                    "summary": vr.summary,
                    "issues": vr.issues,
                },
            )
        return result

    def run_multi_agent(
        self,
        goal: str,
        agent_names: list[str] | None = None,
        publish_fn: EventCallback | None = None,
    ) -> str:
        """Coordinate multiple agents via the orchestrator (research -> execution).

        When *publish_fn* is supplied (e.g. from ``AgentRunWorker``), all events
        produced by the orchestrator are routed through it, preserving Qt
        GUI-thread affinity (NEXT-D-66 contract extended to multi-agent).
        """
        if self._orchestrator is None or self._tools is None:
            return self.run_agent_plan(goal, publish_fn=publish_fn)
        from agent.base import BaseAgent
        from agent.planner import LLMPlanner, StubPlanner

        planner = (
            LLMPlanner(self._engine, tool_registry=self._tools, profile=self.get_effective_profile(), generation_config=self._build_generation_config())
            if self._engine
            else StubPlanner(tool_registry=self._tools, profile=self.get_effective_profile())
        )

        # Inject memory context for the orchestrator's agents
        memory_context = ""
        if self._memory is not None and self._memory_enabled():
            relevant_memories = self._memory.search_memories(goal, limit=5)
            if relevant_memories:
                memory_context = "\n".join(
                    f"[{getattr(m, 'type', 'fact')}] {getattr(m, 'content', str(m))}"
                    for m in relevant_memories
                )
        if memory_context:
            planner.memory_context = memory_context

        # Inject project context for the orchestrator's agents
        project_context = self._build_project_context_prompt()
        if project_context:
            planner.project_context = project_context

        # Pre-retrieve Knowledge (RAG) context for the orchestrator's agents
        if self._rag_pipeline is not None:
            try:
                _, knowledge_context = self._rag_pipeline.retrieve_context(goal)
                if knowledge_context:
                    planner.knowledge_context = knowledge_context
            except Exception:
                logger.exception("Knowledge pre-retrieval failed for multi-agent plan")

        if not self._orchestrator.agent_names and not agent_names:
            self._orchestrator.register(
                BaseAgent(
                    name="assistant-agent",
                    role="executor",
                    goal=goal,
                    planner=planner,
                    tool_registry=self._tools,
                    event_bus=self.event_bus,
                    assistant=self,
                    verifier=self._verifier,
                )
            )
        return self._orchestrator.run(goal, agent_names=agent_names, publish_fn=publish_fn)

    # ------------------------------------------------------------------ #
    # Automation Engine — Phase 10
    # ------------------------------------------------------------------ #
    def run_workflow(self, name: str, publish_fn: EventCallback | None = None) -> str:
        """Run a named automation workflow (through the secured tool registry).

        *publish_fn* — optional callable that replaces ``self.event_bus.publish``
        for the ``WORKFLOW_RAN`` event.  When supplied (e.g. by
        :meth:`_handle_slash_command` running on a worker QThread), the event
        is routed through it so it reaches the GUI thread via Qt signals
        instead of being called directly on the worker thread.
        """
        if self._automation is None:
            return "Automation manager is not configured"
        result = self._automation.run_workflow(name)
        if publish_fn is not None:
            publish_fn("WORKFLOW_RAN", {"workflow": name})
        else:
            self.event_bus.publish("WORKFLOW_RAN", data={"workflow": name})
        return result

    def run_scheduled(self) -> list[str]:
        """Tick the scheduler and execute all due tasks."""
        if self._automation is None:
            return []
        return self._automation.run_scheduled()

    def list_workflows(self) -> list[str]:
        if self._automation is None:
            return []
        return self._automation.list_workflows()

    def _handle_slash_command(
        self, text: str, publish_fn: EventCallback | None = None
    ) -> str | None:
        """Route chat slash-commands (/automation run, /agent plan, /plugin …).

        *publish_fn* — optional callable that replaces ``self.event_bus.publish``
        for events emitted by this method and downstream command handlers.
        When supplied (e.g. by :meth:`process_message` running on a worker
        QThread), all publications are routed through it so they reach the GUI
        thread via Qt signals instead of being called directly on the worker
        thread.
        """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                self.event_bus.publish(event_type, data=data)

        lowered = text.strip().lower()
        if lowered.startswith("/automation run"):
            name = lowered.removeprefix("/automation run").strip()
            pub("COMMAND_EXECUTED", data={"command": "automation_run", "arg": name})
            return self.run_workflow(name, publish_fn=publish_fn)
        if lowered.startswith("/agent plan"):
            goal = lowered.removeprefix("/agent plan").strip()
            if not goal:
                return "Provide a goal after /agent plan"
            pub("COMMAND_EXECUTED", data={"command": "agent_plan", "arg": goal})
            return self.run_agent_plan(goal, publish_fn=publish_fn)
        return self._handle_plugin_command(lowered)

    def _handle_plugin_command(self, lowered: str) -> str | None:
        """Route ``/_plugins`` and ``/plugin <id> <action> [args]`` to the manager."""
        if self._plugin_manager is None:
            return None
        if lowered.startswith("/_plugins"):
            return self._plugin_manager.list_summary()
        if lowered.startswith("/plugin"):
            rest = lowered.removeprefix("/plugin").strip()
            parts = rest.split(None, 2)
            plugin_id = parts[0] if parts else ""
            action = parts[1] if len(parts) > 1 else ""
            args = parts[2] if len(parts) > 2 else ""
            return self._plugin_manager.handle_plugin_command(plugin_id, action, args)
        return None

    def tool_categories(self) -> list[dict]:
        """Return tools with their security category + risk for UI inspection."""
        if self._tools is None:
            return []
        out = []
        for t in self._tools.list_tools():
            tool = self._tools.get(t["name"])
            cat = getattr(tool, "category", None)
            out.append(
                {
                    "name": t["name"],
                    "category": cat.value if cat else "general",
                    "risk_level": t["risk_level"],
                     "requires_confirmation": tool.requires_confirmation() if tool else False,
                }
            )
        return out

    # ------------------------------------------------------------------ #
    # Memory intent integration (Phase 2)
    # ------------------------------------------------------------------ #
    def _memory_enabled(self) -> bool:
        """Whether long-term persistent memory is enabled at runtime."""
        if self._memory is None:
            return False
        return bool(self.config.get("memory.enabled", True))

    def _memories_for_prompt(self, user_input: str) -> list[dict[str, Any]]:
        """Relevant long-term memories to inject into the prompt.

        Returns an empty list when Memory is disabled, so short-term
        conversation history still works regardless of the toggle.
        """
        memory = self._memory
        if memory is None or not self._memory_enabled():
            return []
        context = memory.build_context(
            user_input,
            max_memories=self.config.get("memory.max_context_memories", 5),
        )
        return context.get("relevant_memories", [])

    def _handle_memory_intent(self, text: str) -> str | None:
        """Detect an explicit request to remember something.

        Returns a confirmation prompt when intent is detected, an
        informational notice when Memory is disabled, or ``None`` to fall
        through to normal generation.  Nothing is persisted here — that
        happens only after the user confirms (see ``_maybe_resolve_pending_memory``).
        """
        fact = _extract_memory_fact(text)
        if fact is None:
            return None
        if not self._memory_enabled():
            logger.info("Memory disabled — ignoring remember request")
            return (
                "Memory is disabled; remembering this is not possible until you "
                "enable 'Memory enabled' in the settings."
            )
        self._pending_memory = fact
        return (
            f"This can be saved to memory:\n\n'{fact}'\n\n"
            "Do you want me to remember it?"
        )

    def _maybe_resolve_pending_memory(
        self, text: str, publish_fn: EventCallback | None = None
    ) -> str | None:
        """Resolve an outstanding memory-confirmation from the previous turn.

        Returns the confirmation/decline reply when a pending memory exists and
        the user replies with a clear affirmative or negative, otherwise
        ``None`` (and abandons any stale pending on an ambiguous reply).

        *publish_fn* — optional callable that replaces ``self.event_bus.publish``
        for events emitted by this method.  When supplied (e.g. by
        :meth:`process_message` running on a worker QThread), all publications
        are routed through it so they reach the GUI thread via Qt signals instead
        of being called directly on the worker thread.
        """
        if publish_fn is not None:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                publish_fn(event_type, dict(data) if data else {})
        else:
            def pub(event_type: str, data: dict[str, Any] | None = None) -> None:
                self.event_bus.publish(event_type, data=data)

        pending = self._pending_memory
        memory = self._memory
        if pending is None or memory is None:
            return None
        intent = _classify_confirmation(text)
        if intent is None:
            self._pending_memory = None
            return None
        self._pending_memory = None
        if intent == "negative":
            logger.info("User declined to save memory")
            return "All right, I will not save that to memory."
        if not self._memory_enabled():
            return "Memory is disabled — nothing was saved."
        memory.save_memory(content=pending, mem_type=_classify_memory_type(pending))
        pub("MEMORY_UPDATED", data={"type": "memory_add"})
        logger.info("Memory saved from chat (%s)", pending[:80])
        return "Saved to memory."
