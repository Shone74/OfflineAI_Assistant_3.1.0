"""OpenAI-compatible API engine — online model provider (e.g. OpenRouter).

Implements the :class:`LLMEngine` protocol over an HTTP endpoint that
speaks the OpenAI Chat Completions API (``/v1/chat/completions``), which
OpenRouter, Groq, Mistral, and many other providers expose.

This engine is **opt-in**: it is only constructed when the user explicitly
configures ``api.enabled = true`` and stores their personal API key in
``settings.json`` (key ``api.api_key``).  The application remains
offline-first — no request is ever made unless an agent is explicitly
routed to an ``openrouter:<model>`` / ``api:<model>`` identifier.

Security notes:
  * The API key is read from configuration only — never hardcoded, never
    logged, and never committed (settings.json lives outside the repo).
  * Tool schemas are exported through the same
    :class:`ToolSchemaExporter` used by the local engine, so the
    SecurityLayer confirmation gates remain the single execution path —
    the remote model can only *propose* tool calls, never execute them.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from ai.engine.llm_engine import GenerationConfig, LLMEngine
from ai.models.model_loader import ModelCapabilities
from core.logger import get_logger

logger = get_logger("api_engine")

#: Shared JSON-style capabilities for all chat models served through the
#: OpenAI-compatible API.  Per-model refinement happens in
#: :meth:`model_capabilities` (name-based heuristics shared with the
#: local GGUF path keep the feature parity honest).
_API_CHAT_CAPS = ModelCapabilities(
    text_generation=True,
    streaming=True,
    tool_calling=True,
    function_calling=True,
    json_output=True,
    structured_output=True,
)

_VISION_HINTS = ("vl", "vision", "omni", "multimodal", "gemma-4", "qwen3.5")
_REASONING_HINTS = ("think", "reasoning", "r1", "inkling")


class APIEngineError(RuntimeError):
    """Raised for configuration problems (missing key/URL/model)."""


class OpenAICompatibleEngine(LLMEngine):
    """LLMEngine backed by an OpenAI-compatible HTTP endpoint.

    Parameters
    ----------
    api_key:
        The provider API key (``sk-or-v1-...`` for OpenRouter).
    base_url:
        Root endpoint, e.g. ``https://openrouter.ai/api/v1``.  The engine
        posts to ``{base_url}/chat/completions``.
    model:
        Provider model identifier, e.g. ``z-ai/glm-5.2:free``.
    timeout:
        Per-request timeout in seconds (default 120 — free models can
        queue under load).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        model: str = "",
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise APIEngineError("API key is required for the online engine")
        if not base_url:
            raise APIEngineError("API base URL is required for the online engine")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._model_name_override: str | None = None
        self._last_error: str | None = None

    # ------------------------------------------------------------------ #
    # Configuration
    # ------------------------------------------------------------------ #
    def configure(self, model_manager: Any) -> None:
        """API engines are configured directly — no local ModelManager."""

    def unload(self) -> None:
        """Nothing to release — stateless HTTP engine."""

    # ------------------------------------------------------------------ #
    # Transport
    # ------------------------------------------------------------------ #
    @property
    def _endpoint(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _payload(
        self,
        messages: list[dict[str, Any]],
        config: GenerationConfig | None,
        stream: bool,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        cfg = config or GenerationConfig()
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "top_p": cfg.top_p,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        import requests

        try:
            resp = requests.post(
                self._endpoint,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            self._last_error = str(exc)
            raise APIEngineError(f"API request failed: {exc}") from exc
        if resp.status_code == 401:
            self._last_error = "Unauthorized (401) — check your API key"
            raise APIEngineError(self._last_error)
        if resp.status_code == 429:
            self._last_error = "Rate limited (429) — free-tier daily limit may be reached"
            raise APIEngineError(self._last_error)
        if resp.status_code != 200:
            self._last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            raise APIEngineError(self._last_error)
        try:
            return resp.json()
        except ValueError as exc:
            self._last_error = "Invalid JSON in API response"
            raise APIEngineError(self._last_error) from exc

    def _post_stream(self, payload: dict[str, Any]) -> Iterator[str]:
        """Yield content deltas from an SSE stream."""
        import requests

        try:
            resp = requests.post(
                self._endpoint,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
                stream=True,
            )
        except requests.RequestException as exc:
            self._last_error = str(exc)
            raise APIEngineError(f"API request failed: {exc}") from exc
        if resp.status_code != 200:
            self._last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
            raise APIEngineError(self._last_error)
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = (choices[0] or {}).get("delta") or {}
            token = delta.get("content")
            if token:
                yield token

    # ------------------------------------------------------------------ #
    # LLMEngine protocol
    # ------------------------------------------------------------------ #
    def generate(self, prompt: str, config: GenerationConfig | None = None) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.generate_chat(messages, config)

    def generate_stream(
        self, prompt: str, config: GenerationConfig | None = None
    ) -> Iterator[str]:
        messages = [{"role": "user", "content": prompt}]
        yield from self.generate_chat_stream(messages, config)

    def generate_chat(
        self,
        messages: list[dict[str, Any]],
        config: GenerationConfig | None = None,
    ) -> str:
        if not self._model:
            raise APIEngineError("No API model configured")
        data = self._post(self._payload(messages, config, stream=False))
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise APIEngineError(f"Unexpected API response shape: {data}") from exc

    def generate_chat_stream(
        self,
        messages: list[dict[str, Any]],
        config: GenerationConfig | None = None,
    ) -> Iterator[str]:
        if not self._model:
            raise APIEngineError("No API model configured")
        yield from self._post_stream(self._payload(messages, config, stream=True))

    def count_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate token count for the budget enforcer (char/4)."""
        total_chars = sum(len(str(m.get("content", ""))) for m in messages)
        return max(1, total_chars // 4)

    # ------------------------------------------------------------------ #
    # Native tool calling (OpenAI-style tool_calls)
    # ------------------------------------------------------------------ #
    def generate_with_tools(
        self,
        prompt: str,
        tools: list[dict[str, Any]] | None = None,
        config: GenerationConfig | None = None,
    ):
        """Generate with native tool schemas; parse ``tool_calls`` deltas.

        Uses the shared :class:`ToolCallResponse` contract from
        :mod:`ai.engine.tool_calling` so the local and online engines are
        interchangeable for the Assistant's native-tool path.
        """
        from ai.engine.tool_calling import ToolCall, ToolCallResponse

        if not self._model:
            raise APIEngineError("No API model configured")
        messages = [{"role": "user", "content": prompt}]
        data = self._post(
            self._payload(messages, config, stream=False, tools=tools)
        )
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise APIEngineError(f"Unexpected API response shape: {data}") from exc

        text = message.get("content") or ""
        tool_calls: list[ToolCall] = []
        for i, tc in enumerate(message.get("tool_calls") or []):
            fn = (tc or {}).get("function") or {}
            name = fn.get("name")
            args_raw = fn.get("arguments")
            try:
                args = json.loads(args_raw) if args_raw else {}
            except (TypeError, json.JSONDecodeError):
                args = {"_raw": str(args_raw)}
            if name:
                tool_calls.append(
                    ToolCall(id=f"call_{i + 1}", name=name, arguments=args)
                )
        return ToolCallResponse(text=text, tool_calls=tool_calls)

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    @property
    def model_name(self) -> str:
        if self._model_name_override:
            return self._model_name_override
        return self._model or "api-model"

    @property
    def is_ready(self) -> bool:
        return bool(self._api_key and self._base_url and self._model)

    @property
    def load_status(self) -> str:
        if not (self._api_key and self._base_url):
            return "not_configured"
        if not self._model:
            return "not_configured"
        if self._last_error:
            return "error"
        return "ready"

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def supports_tool_calling(self) -> bool:
        return True

    @property
    def supports_vision(self) -> bool:
        return False  # images are not forwarded to the online path (v1)

    @property
    def model_capabilities(self) -> ModelCapabilities:
        caps = _API_CHAT_CAPS
        name = self._model.lower()
        if any(h in name for h in _VISION_HINTS):
            caps = ModelCapabilities(
                **{**caps.to_dict(), "vision": True, "multimodal": True}
            )
        if any(h in name for h in _REASONING_HINTS):
            caps = ModelCapabilities(
                **{**caps.to_dict(), "reasoning": True}
            )
        return caps


# ------------------------------------------------------------------ #
# Multi-provider support
# ------------------------------------------------------------------ #
#: Built-in provider presets.  Each user stores their personal key under
#: ``api.providers.<id>.api_key`` in settings.json — models from every
#: configured provider are then available to agents via ``<id>:<model>``.
PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "key_hint": "sk-or-v1-...",
        "key_url": "https://openrouter.ai/keys",
    },
    "groq": {
        "label": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "key_hint": "gsk_...",
        "key_url": "https://console.groq.com/keys",
    },
    "google": {
        "label": "Google AI Studio (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "key_hint": "AIza...",
        "key_url": "https://aistudio.google.com/apikey",
    },
    "mistral": {
        "label": "Mistral (La Plateforme)",
        "base_url": "https://api.mistral.ai/v1",
        "key_hint": "...",
        "key_url": "https://console.mistral.ai/api-keys",
    },
    "cerebras": {
        "label": "Cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "key_hint": "csk-...",
        "key_url": "https://cloud.cerebras.ai/",
    },
    "together": {
        "label": "Together AI",
        "base_url": "https://api.together.xyz/v1",
        "key_hint": "...",
        "key_url": "https://api.together.ai/settings/api-keys",
    },
}

#: Provider id aliases accepted in agent model names (``openrouter`` and
#: ``api`` both route to the default provider; ``or`` is a convenience alias).
_PROVIDER_ALIASES: dict[str, str] = {
    "openrouter": "openrouter",
    "or": "openrouter",
    "api": "",  # empty → the configured default provider
    "groq": "groq",
    "google": "google",
    "gemini": "google",
    "mistral": "mistral",
    "cerebras": "cerebras",
    "together": "together",
}

#: Curated free OpenRouter models (tools-capable, verified via /api/v1/models).
FREE_OPENROUTER_MODELS: list[str] = [
    "z-ai/glm-5.2:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "minimax/minimax-m3:free",
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "poolside/laguna-s-2.1:free",
    "poolside/laguna-xs-2.1:free",
    "cohere/north-mini-code:free",
    "dots-studio/dots-3-note-preview:free",
    "liquid/lfm-2.5-2.6b:free",
    "inclusionai/ling-3.0-flash-sante:free",
    "inclusionai/ling-3.0-flash-fin:free",
]


def parse_online_model_spec(spec: str) -> tuple[str, str]:
    """Split ``"<provider>:<model>"`` into ``(provider_id, model)``.

    Accepts built-in aliases (``or``/``openrouter``/``api``/``gemini``...).
    A bare ``<model>`` (no colon prefix) resolves to the default provider
    (``""``) so the caller applies ``api.default_provider``.
    """
    text = (spec or "").strip()
    if not text:
        return "", ""
    if ":" not in text:
        return "", text
    prefix, _, model = text.partition(":")
    key = prefix.strip().lower()
    if key in _PROVIDER_ALIASES:
        return _PROVIDER_ALIASES[key], model.strip()
    # Unknown prefix but looks like "vendor/model" (OpenRouter ids contain
    # a slash, not a colon) — treat the whole string as a model id.
    if "/" in text and ":" not in text.split("/")[0]:
        return "", text
    # Custom provider name registered by the user (see
    # ``register_custom_provider``) — validated by the caller.
    return prefix.strip().lower(), model.strip()


def get_provider_config(config: Any, provider_id: str) -> dict[str, Any] | None:
    """Return the merged provider settings dict or ``None``.

    Reads ``api.providers.<id>`` (the multi-provider store), falling back to
    the legacy flat ``api.api_key``/``api.base_url`` values for
    ``openrouter``/the default provider (backward compatible migration).
    """
    if config is None:
        return None
    pid = provider_id or str(config.get("api.default_provider", "") or "").strip() or "openrouter"
    providers = config.get("api.providers", {}) or {}
    entry = providers.get(pid, {}) if isinstance(providers, dict) else {}
    if entry:
        base_url = str(entry.get("base_url", "") or "").strip()
        if not base_url:
            # Fall back to the preset (built-ins) or the registered custom
            # endpoint before giving up.
            base_url = PROVIDER_PRESETS.get(pid, {}).get("base_url", "")
        if not base_url:
            custom = config.get("api.custom_providers", {}) or {}
            base_url = str(
                (custom.get(pid, {}) or {}).get("base_url", "") or ""
            ).strip()
        return {
            "provider_id": pid,
            "api_key": str(entry.get("api_key", "") or "").strip(),
            "base_url": base_url,
            "model": str(entry.get("model", "") or "").strip(),
            "timeout": entry.get("timeout", config.get("api.timeout", 120)),
        }
    # Legacy flat config (single-provider era) — only for the default provider.
    legacy_key = str(config.get("api.api_key", "") or "").strip()
    if legacy_key and pid in ("openrouter", str(config.get("api.default_provider", "") or "")):
        return {
            "provider_id": pid,
            "api_key": legacy_key,
            "base_url": str(config.get("api.base_url", "") or "").strip()
            or PROVIDER_PRESETS.get(pid, {}).get("base_url", ""),
            "model": str(config.get("api.model", "") or "").strip(),
            "timeout": config.get("api.timeout", 120),
        }
    return None


def set_provider_config(
    config: Any,
    provider_id: str,
    api_key: str,
    base_url: str = "",
    model: str = "",
    timeout: Any = None,
) -> None:
    """Persist one provider entry into ``api.providers.<id>`` (and keep the
    legacy flat mirror in sync for the default provider)."""
    if config is None:
        return
    pid = (provider_id or "").strip().lower()
    providers = dict(config.get("api.providers", {}) or {})
    entry: dict[str, Any] = {
        "api_key": (api_key or "").strip(),
        "base_url": (base_url or "").strip(),
        "model": (model or "").strip(),
    }
    if timeout is not None:
        entry["timeout"] = timeout
    providers[pid] = entry
    config.set("api.providers", providers)
    default = str(config.get("api.default_provider", "") or "").strip() or "openrouter"
    if pid == default:
        # Legacy mirror so older code paths (single-provider) keep working.
        config.set("api.api_key", entry["api_key"])
        config.set("api.base_url", entry["base_url"] or PROVIDER_PRESETS.get(pid, {}).get("base_url", ""))
        config.set("api.model", entry["model"])


def register_custom_provider(config: Any, provider_id: str, base_url: str) -> None:
    """Register a user-defined OpenAI-compatible provider (any id)."""
    if config is None:
        return
    pid = (provider_id or "").strip().lower()
    if not pid:
        return
    custom = dict(config.get("api.custom_providers", {}) or {})
    custom[pid] = {"base_url": (base_url or "").strip()}
    config.set("api.custom_providers", custom)


def provider_is_configured(config: Any, provider_id: str) -> bool:
    """True when the provider has a stored, non-empty API key."""
    entry = get_provider_config(config, provider_id)
    return bool(entry and entry.get("api_key"))


def build_provider_engine(
    config: Any,
    provider_id: str,
    model: str,
) -> OpenAICompatibleEngine | None:
    """Build an engine for *model* on the given provider (or the default).

    Returns ``None`` when the provider is not configured (no key) so callers
    can fall back to the local engine.  Never raises.
    """
    try:
        if not config.get("api.enabled", False):
            return None
        entry = get_provider_config(config, provider_id)
        if entry is None or not entry.get("api_key"):
            return None
        pid = entry["provider_id"]
        base_url = (
            entry.get("base_url")
            or PROVIDER_PRESETS.get(pid, {}).get("base_url", "")
        )
        timeout = float(entry.get("timeout") or 120)
        if not model or not base_url:
            return None
        engine = OpenAICompatibleEngine(
            api_key=entry["api_key"], base_url=base_url,
            model=model, timeout=timeout,
        )
        engine._model_name_override = f"{pid}:{model}"
        return engine
    except Exception:
        logger.warning("Could not build online engine for %s", provider_id, exc_info=True)
        return None


def fetch_provider_models(config: Any, provider_id: str) -> list[str]:
    """Live-fetch the provider's model catalogue via ``GET /models``.

    Returns a sorted id list; empty on failure (the caller shows curated
    presets instead).  Requires the provider key.
    """
    return [m["id"] for m in fetch_provider_model_details(config, provider_id)]


def fetch_provider_model_details(
    config: Any, provider_id: str
) -> list[dict[str, Any]]:
    """Live-fetch the provider's model catalogue with metadata.

    Returns a list of dicts ``{"id": str, "free": bool}`` sorted by id;
    empty on failure (the caller shows curated presets instead).
    Requires the provider key.  Free detection:

    * OpenRouter — the catalogue entry's ``pricing.prompt``/
      ``pricing.completion`` strings are ``"0"`` for free models (and
      ids conventionally end with ``:free``).
    * Other providers — name heuristics (``free``/``:free`` in the id).
    """
    import requests

    entry = get_provider_config(config, provider_id)
    if entry is None or not entry.get("api_key"):
        return []
    pid = entry["provider_id"]
    base_url = (
        entry.get("base_url")
        or PROVIDER_PRESETS.get(pid, {}).get("base_url", "")
    ).rstrip("/")
    if not base_url:
        return []
    try:
        resp = requests.get(
            f"{base_url}/models",
            headers={"Authorization": f"Bearer {entry['api_key']}"},
            timeout=20,
        )
        if resp.status_code != 200:
            logger.info("Model catalogue fetch failed (%s): HTTP %s", pid, resp.status_code)
            return []
        data = resp.json()
        models = data.get("data", data) if isinstance(data, dict) else data
        seen: dict[str, dict[str, Any]] = {}
        for m in models or []:
            if not isinstance(m, dict) or not m.get("id"):
                continue
            mid = str(m["id"])
            seen[mid] = {
                "id": mid,
                "free": _catalogue_entry_is_free(pid, m),
            }
        return [seen[k] for k in sorted(seen)]
    except Exception:
        logger.debug("Model catalogue fetch failed for %s", pid, exc_info=True)
        return []


def _catalogue_entry_is_free(pid: str, entry: dict[str, Any]) -> bool:
    """True when a raw catalogue entry looks like a zero-cost model."""
    mid = str(entry.get("id", ""))
    if mid.endswith(":free") or ":free" in mid:
        return True
    pricing = entry.get("pricing")
    if isinstance(pricing, dict):
        prompt = str(pricing.get("prompt", ""))
        completion = str(pricing.get("completion", ""))
        if prompt or completion:
            try:
                return (
                    float(prompt or "0") == 0.0
                    and float(completion or "0") == 0.0
                )
            except ValueError:
                pass
    return False


def get_selected_free_models(config: Any) -> list[str]:
    """Return the user's selected free-model pool as full specs.

    Reads ``api.selected_free_models`` (a list of ``<provider>:<model>``
    strings filled by the Settings → Online API page).  Falls back to the
    curated OpenRouter free list (default provider prefixed) when the
    user has not picked anything yet but auto-selection is enabled.
    """
    if config is None:
        return []
    selected = config.get("api.selected_free_models", []) or []
    out: list[str] = []
    for spec in selected:
        text = str(spec).strip()
        if not text:
            continue
        provider_id, model = parse_online_model_spec(text)
        if not provider_id or not model:
            continue
        out.append(f"{provider_id}:{model}")
    return out


def select_free_model_for_task(
    config: Any, task_text: str
) -> tuple[str, str] | None:
    """Pick the best model from the free pool for *task_text*.

    Returns ``(provider_id, model)`` or ``None``.  Heuristics mirror the
    app's local capability detection: coder/code → coding models, 
    think/reason/math → reasoning models, vision/image → vision-capable,
    otherwise general/flash-class models.
    """
    pool = get_selected_free_models(config)
    if not pool:
        return None
    text = (task_text or "").lower()

    def score(spec: str) -> int:
        s = 0
        m = spec.split(":", 1)[1].lower() if ":" in spec else spec.lower()
        if any(k in text for k in ("code", "program", "debug", "script", "repo")) and \
                any(k in m for k in ("coder", "code")):
            s += 4
        if any(k in text for k in ("think", "reason", "math", "logic", "analyze")) and \
                any(k in m for k in ("think", "reason", "r1", "inkling")):
            s += 4
        if any(k in text for k in ("image", "vision", "picture", "screenshot", "ocr")) and \
                any(k in m for k in ("vision", "vl", "omni")):
            s += 4
        if any(k in text for k in ("write", "document", "summary", "translate")) and \
                any(k in m for k in ("flash", "instant", "small", "mini")):
            s += 2
        return s

    best = max(pool, key=score)
    provider_id, model = parse_online_model_spec(best)
    if not provider_id or not model:
        return None
    return provider_id, model


def build_api_engine_from_config(config: Any) -> OpenAICompatibleEngine | None:
    """Construct an engine for the default provider's default model.

    Returns ``None`` when the API is disabled or misconfigured.  Never
    raises — callers fall back to the local engine.
    """
    try:
        if not config.get("api.enabled", False):
            return None
        entry = get_provider_config(config, "")
        if entry is None or not entry.get("api_key"):
            return None
        model = entry.get("model") or ""
        if not model:
            logger.info("Online API enabled but default model missing — inactive")
            return None
        return build_provider_engine(config, entry["provider_id"], model)
    except Exception:
        logger.warning("Could not build online API engine", exc_info=True)
        return None
