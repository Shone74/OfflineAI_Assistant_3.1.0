"""Tests for the opt-in Online API engine — multi-provider edition.

Covers: provider presets, per-provider key storage, agent routing with
``<provider>:<model>`` specs, custom providers, legacy single-provider
config migration, and the curated model catalogues.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OFFLINE_AI_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ai.engine.api_engine import (
    FREE_OPENROUTER_MODELS,
    PROVIDER_PRESETS,
    APIEngineError,
    OpenAICompatibleEngine,
    build_api_engine_from_config,
    build_provider_engine,
    fetch_provider_models,
    get_provider_config,
    parse_online_model_spec,
    provider_is_configured,
    register_custom_provider,
    set_provider_config,
)
from core.assistant import Assistant
from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.router import Router
from database.models import Agent


def _cfg(tmp_path, enabled=True) -> ConfigManager:
    c = ConfigManager(settings_path=tmp_path / "s.json")
    if enabled:
        c.set("api.enabled", True)
    return c


def _engine() -> OpenAICompatibleEngine:
    return OpenAICompatibleEngine(
        api_key="sk-test", base_url="https://openrouter.ai/api/v1",
        model="z-ai/glm-5.2:free",
    )


# ------------------------------------------------------------------ #
# Provider presets & spec parsing
# ------------------------------------------------------------------ #
class TestProviderPresets:
    def test_all_builtins_present(self):
        for pid in ("openrouter", "groq", "google", "mistral", "cerebras", "together"):
            assert pid in PROVIDER_PRESETS
            assert PROVIDER_PRESETS[pid]["base_url"].startswith("https://")
            assert PROVIDER_PRESETS[pid]["key_url"]

    def test_parse_openrouter(self):
        assert parse_online_model_spec("openrouter:z-ai/glm-5.2:free") == (
            "openrouter", "z-ai/glm-5.2:free",
        )

    def test_parse_or_alias(self):
        assert parse_online_model_spec("or:minimax/minimax-m3:free") == (
            "openrouter", "minimax/minimax-m3:free",
        )

    def test_parse_groq(self):
        assert parse_online_model_spec("groq:llama-3.3-70b-versatile") == (
            "groq", "llama-3.3-70b-versatile",
        )

    def test_parse_google_and_gemini_alias(self):
        assert parse_online_model_spec("google:gemini-2.5-flash")[0] == "google"
        assert parse_online_model_spec("gemini:gemini-2.5-pro")[0] == "google"

    def test_parse_api_means_default(self):
        # "api:" resolves to provider "" -> the caller applies default_provider
        pid, model = parse_online_model_spec("api:whatever-model")
        assert pid == ""
        assert model == "whatever-model"

    def test_parse_bare_model_is_default(self):
        assert parse_online_model_spec("just-a-model") == ("", "just-a-model")

    def test_parse_openrouter_style_id_without_prefix(self):
        # A raw OpenRouter "vendor/model" string has no colon before the
        # slash — treated as a default-provider model id.
        pid, model = parse_online_model_spec("z-ai/glm-5.2:free")
        assert pid == ""
        assert model == "z-ai/glm-5.2:free"

    def test_parse_custom_provider(self):
        assert parse_online_model_spec("myllm:house-model") == (
            "myllm", "house-model",
        )


# ------------------------------------------------------------------ #
# Per-provider key storage
# ------------------------------------------------------------------ #
class TestProviderConfigStorage:
    def test_set_and_get(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "groq", api_key="gsk-123", model="llama-3.3-70b-versatile")
        entry = get_provider_config(c, "groq")
        assert entry is not None
        assert entry["api_key"] == "gsk-123"
        assert entry["base_url"] == PROVIDER_PRESETS["groq"]["base_url"]
        assert entry["model"] == "llama-3.3-70b-versatile"

    def test_provider_is_configured(self, tmp_path):
        c = _cfg(tmp_path)
        assert provider_is_configured(c, "groq") is False
        set_provider_config(c, "groq", api_key="gsk-123")
        assert provider_is_configured(c, "groq") is True
        assert provider_is_configured(c, "mistral") is False

    def test_multiple_providers_coexist(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "openrouter", api_key="sk-or-1", model="m1")
        set_provider_config(c, "groq", api_key="gsk-2", model="m2")
        assert get_provider_config(c, "openrouter")["api_key"] == "sk-or-1"
        assert get_provider_config(c, "groq")["api_key"] == "gsk-2"

    def test_default_provider_mirror_synced(self, tmp_path):
        c = _cfg(tmp_path)
        c.set("api.default_provider", "groq")
        set_provider_config(c, "groq", api_key="gsk-x", model="m")
        # Legacy flat mirror stays in sync with the default provider:
        assert c.get("api.api_key") == "gsk-x"
        assert c.get("api.model") == "m"

    def test_legacy_flat_config_still_works(self, tmp_path):
        # Single-provider era config (flat api.api_key) must keep working.
        c = _cfg(tmp_path)
        c.set("api.api_key", "sk-legacy")
        c.set("api.model", "legacy-model")
        entry = get_provider_config(c, "openrouter")
        assert entry is not None
        assert entry["api_key"] == "sk-legacy"
        assert entry["model"] == "legacy-model"

    def test_missing_key_returns_none(self, tmp_path):
        c = _cfg(tmp_path)
        assert get_provider_config(c, "mistral") is None


class TestCustomProviders:
    def test_register_and_route(self, tmp_path):
        c = _cfg(tmp_path)
        register_custom_provider(c, "myllm", "https://my-endpoint.example/v1")
        set_provider_config(c, "myllm", api_key="house-key", model="house-model")
        entry = get_provider_config(c, "myllm")
        assert entry is not None
        assert entry["base_url"] == "https://my-endpoint.example/v1"
        assert entry["api_key"] == "house-key"
        e = build_provider_engine(c, "myllm", "house-model")
        assert e is not None
        assert e.model_name == "myllm:house-model"

    def test_custom_requires_registration_for_url(self, tmp_path):
        # An unregistered custom provider has no base_url -> engine None.
        c = _cfg(tmp_path)
        set_provider_config(c, "unknown", api_key="k", model="m")
        assert build_provider_engine(c, "unknown", "m") is None


# ------------------------------------------------------------------ #
# Engine building
# ------------------------------------------------------------------ #
class TestBuildProviderEngine:
    def test_disabled_api_returns_none(self, tmp_path):
        c = _cfg(tmp_path, enabled=False)
        set_provider_config(c, "groq", api_key="gsk-1", model="m")
        assert build_provider_engine(c, "groq", "m") is None

    def test_no_key_returns_none(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "groq", api_key="", model="m")
        assert build_provider_engine(c, "groq", "m") is None

    def test_default_provider_resolution(self, tmp_path):
        c = _cfg(tmp_path)
        c.set("api.default_provider", "groq")
        set_provider_config(c, "groq", api_key="gsk-1", model="fallback-model")
        e = build_provider_engine(c, "", "some-model")
        assert e is not None
        assert e.model_name == "groq:some-model"

    def test_build_api_engine_from_config(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "openrouter", api_key="sk-or-1", model="z-ai/glm-5.2:free")
        e = build_api_engine_from_config(c)
        assert e is not None and e.is_ready

    def test_build_default_none_without_model(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "openrouter", api_key="sk-or-1", model="")
        assert build_api_engine_from_config(c) is None


# ------------------------------------------------------------------ #
# Agent routing (Assistant)
# ------------------------------------------------------------------ #
class TestAgentRouting:
    def _assistant(self, tmp_path, enabled=True):
        cfg = _cfg(tmp_path, enabled=enabled)
        return Assistant(config=cfg, event_bus=EventBus(), router=Router())

    def test_groq_routing(self, tmp_path):
        a = self._assistant(tmp_path)
        set_provider_config(a.config, "groq", api_key="gsk-1", model="m")
        agent = Agent(name="bot", model_name="groq:llama-3.3-70b-versatile")
        engine = a._resolve_agent_engine(agent)
        assert engine is not None
        assert engine.model_name == "groq:llama-3.3-70b-versatile"
        assert engine.is_ready

    def test_google_routing(self, tmp_path):
        a = self._assistant(tmp_path)
        set_provider_config(a.config, "google", api_key="AIza-x", model="m")
        agent = Agent(name="bot", model_name="google:gemini-2.5-flash")
        engine = a._resolve_agent_engine(agent)
        assert engine.model_name == "google:gemini-2.5-flash"

    def test_custom_provider_routing(self, tmp_path):
        a = self._assistant(tmp_path)
        register_custom_provider(a.config, "myllm", "https://my.example/v1")
        set_provider_config(a.config, "myllm", api_key="k", model="hm")
        agent = Agent(name="bot", model_name="myllm:house-model")
        engine = a._resolve_agent_engine(agent)
        assert engine is not None
        assert engine.model_name == "myllm:house-model"

    def test_unconfigured_provider_falls_back_to_local(self, tmp_path):
        a = self._assistant(tmp_path)
        agent = Agent(name="bot", model_name="groq:some-model")
        engine = a._resolve_agent_engine(agent)
        assert engine is a._engine

    def test_openrouter_still_routes(self, tmp_path):
        a = self._assistant(tmp_path)
        set_provider_config(a.config, "openrouter", api_key="sk-or-1", model="m")
        agent = Agent(name="bot", model_name="openrouter:z-ai/glm-5.2:free")
        engine = a._resolve_agent_engine(agent)
        assert engine.model_name == "openrouter:z-ai/glm-5.2:free"

    def test_local_model_name_still_local(self, tmp_path):
        a = self._assistant(tmp_path)
        agent = Agent(name="bot", model_name="qwen-8b")
        assert a._resolve_agent_engine(agent) is a._engine


# ------------------------------------------------------------------ #
# Transport / engine behaviour (unchanged core, re-verified)
# ------------------------------------------------------------------ #
class TestAPIEngineTransport:
    def test_requires_key(self):
        with pytest.raises(APIEngineError):
            OpenAICompatibleEngine(api_key="", model="m")

    def test_is_ready(self):
        assert _engine().is_ready is True

    def test_generate_chat_parses_response(self):
        e = _engine()
        fake = {"choices": [{"message": {"content": "hello"}}]}
        with patch.object(e, "_post", return_value=fake):
            assert e.generate_chat([{"role": "user", "content": "hi"}]) == "hello"

    def test_error_paths_recorded(self):
        e = _engine()

        class FakeResp:
            status_code = 429
            text = "rate limited"

            def json(self):
                return {}

        with patch("requests.post", return_value=FakeResp()), pytest.raises(APIEngineError):
            e.generate_chat([{"role": "user", "content": "hi"}])
        assert "429" in (e.last_error or "")
        assert e.load_status == "error"

    def test_tool_calls_parsed(self):
        e = _engine()
        fake = {
            "choices": [{
                "message": {
                    "content": "",
                    "tool_calls": [{
                        "function": {"name": "calculate",
                                     "arguments": '{"expression": "1+1"}'},
                    }],
                }
            }]
        }
        with patch.object(e, "_post", return_value=fake):
            resp = e.generate_with_tools("calc", tools=[])
        assert resp.has_tool_calls
        assert resp.tool_calls[0].name == "calculate"

    def test_vision_hint_capabilities(self):
        e = OpenAICompatibleEngine(api_key="k", model="google/gemma-4-31b-it:free")
        assert e.model_capabilities.vision is True


# ------------------------------------------------------------------ #
# Catalogue fetch (mocked — no network in tests)
# ------------------------------------------------------------------ #
class TestFetchModels:
    def test_no_key_returns_empty(self, tmp_path):
        c = _cfg(tmp_path)
        assert fetch_provider_models(c, "groq") == []

    def test_malformed_response_returns_empty(self, tmp_path):
        c = _cfg(tmp_path)
        set_provider_config(c, "groq", api_key="gsk-1")

        class FakeResp:
            status_code = 200

            def json(self):
                return {"data": [{"id": "model-a"}, {"id": "model-b"}, {"id": "model-a"}]}

        with patch("requests.get", return_value=FakeResp()):
            models = fetch_provider_models(c, "groq")
        assert models == ["model-a", "model-b"]


class TestFetchModelDetails:
    def _fetch(self, tmp_path, payload):
        c = _cfg(tmp_path)
        set_provider_config(c, "openrouter", api_key="sk-1")

        class FakeResp:
            status_code = 200

            def json(self):
                return payload

        with patch("requests.get", return_value=FakeResp()):
            from ai.engine.api_engine import fetch_provider_model_details

            return fetch_provider_model_details(c, "openrouter")

    def test_free_flag_from_pricing(self, tmp_path):
        details = self._fetch(tmp_path, {"data": [
            {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "paid/model-x", "pricing": {"prompt": "0.001", "completion": "0.002"}},
        ]})
        by_id = {d["id"]: d["free"] for d in details}
        assert by_id["z-ai/glm-5.2:free"] is True
        assert by_id["paid/model-x"] is False

    def test_free_flag_from_id_suffix(self, tmp_path):
        details = self._fetch(tmp_path, {"data": [
            {"id": "vendor/m:free"},
            {"id": "vendor/m"},
        ]})
        by_id = {d["id"]: d["free"] for d in details}
        assert by_id["vendor/m:free"] is True
        assert by_id["vendor/m"] is False

    def test_sorted_and_deduplicated(self, tmp_path):
        details = self._fetch(tmp_path, {"data": [
            {"id": "b"}, {"id": "a"}, {"id": "a"},
        ]})
        assert [d["id"] for d in details] == ["a", "b"]


class TestFreeModelPool:
    def _pool_cfg(self, tmp_path, models):
        from ai.engine.api_engine import set_provider_config

        c = _cfg(tmp_path)
        set_provider_config(c, "openrouter", api_key="sk-1")
        c.set("api.selected_free_models", [
            f"openrouter:{m}" for m in models
        ])
        return c

    def test_selected_models_roundtrip(self, tmp_path):
        from ai.engine.api_engine import get_selected_free_models

        c = self._pool_cfg(tmp_path, ["z-ai/glm-5.2:free", "minimax/minimax-m3:free"])
        assert set(get_selected_free_models(c)) == {
            "openrouter:z-ai/glm-5.2:free",
            "openrouter:minimax/minimax-m3:free",
        }

    def test_invalid_specs_dropped(self, tmp_path):
        from ai.engine.api_engine import get_selected_free_models

        c = _cfg(tmp_path)
        c.set("api.selected_free_models", ["", "bare-model", "or:good/model:free"])
        assert get_selected_free_models(c) == ["openrouter:good/model:free"]

    def test_empty_selection_returns_none(self, tmp_path):
        from ai.engine.api_engine import select_free_model_for_task

        c = _cfg(tmp_path)
        assert select_free_model_for_task(c, "write code") is None

    def test_coding_task_picks_coder_model(self, tmp_path):
        from ai.engine.api_engine import select_free_model_for_task

        c = self._pool_cfg(tmp_path, [
            "thinkingmachines/inkling:free",
            "cohere/north-mini-code:free",
        ])
        assert select_free_model_for_task(c, "debug this python script") == (
            "openrouter", "cohere/north-mini-code:free",
        )

    def test_reasoning_task_picks_thinking_model(self, tmp_path):
        from ai.engine.api_engine import select_free_model_for_task

        c = self._pool_cfg(tmp_path, [
            "cohere/north-mini-code:free",
            "thinkingmachines/inkling:free",
        ])
        assert select_free_model_for_task(c, "think step by step and analyze") == (
            "openrouter", "thinkingmachines/inkling:free",
        )

    def test_general_task_picks_any_model(self, tmp_path):
        from ai.engine.api_engine import select_free_model_for_task

        c = self._pool_cfg(tmp_path, ["liquid/lfm-2.5-2.6b:free"])
        assert select_free_model_for_task(c, "hello there") == (
            "openrouter", "liquid/lfm-2.5-2.6b:free",
        )


class TestAutoFreeAgentRouting:
    def _assistant(self, tmp_path, auto=True):
        cfg = _cfg(tmp_path, enabled=True)
        cfg.set("api.auto_free_models", auto)
        set_provider_config(cfg, "openrouter", api_key="sk-1")
        cfg.set("api.selected_free_models", [
            "openrouter:cohere/north-mini-code:free",
            "openrouter:thinkingmachines/inkling:free",
        ])
        return Assistant(config=cfg, event_bus=EventBus(), router=Router())

    def test_auto_free_routes_when_no_model_set(self, tmp_path):
        a = self._assistant(tmp_path)
        agent = Agent(name="bot", description="debug python script")
        engine = a._resolve_agent_engine(agent)
        assert engine is not None
        assert engine.model_name == "openrouter:cohere/north-mini-code:free"

    def test_auto_free_disabled_falls_back(self, tmp_path):
        a = self._assistant(tmp_path, auto=False)
        agent = Agent(name="bot")
        assert a._resolve_agent_engine(agent) is a._engine

    def test_explicit_model_still_wins(self, tmp_path):
        a = self._assistant(tmp_path)
        agent = Agent(name="bot", model_name="openrouter:z-ai/glm-5.2:free")
        engine = a._resolve_agent_engine(agent)
        assert engine.model_name == "openrouter:z-ai/glm-5.2:free"


# ------------------------------------------------------------------ #
# UI
# ------------------------------------------------------------------ #
class TestAPISettingsTabMultiProvider:
    def _tab(self, qapp, tmp_path):
        from ui.settings import APISettingsTab

        cfg = _cfg(tmp_path)
        tab = APISettingsTab(config=cfg)
        return cfg, tab

    def test_all_presets_listed(self, qapp, tmp_path):
        _cfg_obj, tab = self._tab(qapp, tmp_path)
        labels = " ".join(tab._provider_combo.itemText(i)
                          for i in range(tab._provider_combo.count()))
        for name in ("OpenRouter", "Groq", "Google", "Mistral", "Cerebras", "Together"):
            assert name in labels

    def test_key_stored_per_provider(self, qapp, tmp_path):
        _cfg, tab = self._tab(qapp, tmp_path)
        # Select Groq, type a key, switch away and back — key persists.
        idx = tab._provider_combo.findData("groq")
        tab._provider_combo.setCurrentIndex(idx)
        tab._api_key_edit.setText("gsk-my-key")
        idx2 = tab._provider_combo.findData("openrouter")
        tab._provider_combo.setCurrentIndex(idx2)
        assert tab._api_key_edit.text() == ""
        tab._provider_combo.setCurrentIndex(idx)
        assert tab._api_key_edit.text() == "gsk-my-key"

    def test_custom_provider_added_to_combo(self, qapp, tmp_path):
        cfg, tab = self._tab(qapp, tmp_path)
        tab._custom_id_edit.setText("myllm")
        tab._custom_url_edit.setText("https://my.example/v1")
        tab._on_add_custom()
        assert tab._provider_combo.findData("myllm") >= 0
        assert cfg.get("api.custom_providers.myllm.base_url") == "https://my.example/v1"

    def test_key_field_masked(self, qapp, tmp_path):
        from PySide6.QtWidgets import QLineEdit

        _cfg_obj, tab = self._tab(qapp, tmp_path)
        assert tab._api_key_edit.echoMode() == QLineEdit.EchoMode.Password

    def test_curated_models_per_provider(self, qapp, tmp_path):
        _cfg_obj, tab = self._tab(qapp, tmp_path)
        assert any("llama" in m for m in tab._curated_models("groq"))
        assert any("gemini" in m for m in tab._curated_models("google"))
        assert len(tab._curated_models("openrouter")) == len(FREE_OPENROUTER_MODELS)


class TestFetchedModelsList:
    """The checkable catalogue list revealed by 'Fetch models'."""

    @staticmethod
    def _tab(qapp, tmp_path):
        from ui.settings import APISettingsTab

        cfg = _cfg(tmp_path)
        tab = APISettingsTab(config=cfg)
        return cfg, tab

    def _tab_with_catalogue(self, qapp, tmp_path, models):
        cfg, tab = self._tab(qapp, tmp_path)
        # Type the key into the form first — _on_fetch_models persists the
        # form fields before fetching, mirroring real usage.
        tab._api_key_edit.setText("sk-1")

        class FakeResp:
            status_code = 200

            def json(self):
                return {"data": models}

        with patch("requests.get", return_value=FakeResp()):
            tab._on_fetch_models()
        return cfg, tab

    def test_fetch_reveals_list(self, qapp, tmp_path):
        _cfg, tab = self._tab_with_catalogue(qapp, tmp_path, [
            {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "paid/model", "pricing": {"prompt": "0.001", "completion": "0"}},
        ])
        assert tab._models_group.isHidden() is False
        assert tab._models_list.count() == 2
        labels = [tab._models_list.item(i).text() for i in range(tab._models_list.count())]
        assert any("[FREE]" in l for l in labels)

    def test_fetch_failure_keeps_list_hidden(self, qapp, tmp_path):
        _cfg, tab = self._tab(qapp, tmp_path)
        # No key persisted -> fetch fails -> list stays hidden.
        tab._on_fetch_models()
        assert tab._models_group.isHidden() is True

    def test_select_all_free_ticks_only_free(self, qapp, tmp_path):
        cfg, tab = self._tab_with_catalogue(qapp, tmp_path, [
            {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"}},
            {"id": "paid/model", "pricing": {"prompt": "0.001", "completion": "0"}},
        ])
        tab._on_select_all_free()
        from PySide6.QtCore import Qt

        states = {}
        for i in range(tab._models_list.count()):
            item = tab._models_list.item(i)
            spec = str(item.data(Qt.ItemDataRole.UserRole))
            states[spec] = item.checkState() == Qt.CheckState.Checked
        assert states["openrouter:z-ai/glm-5.2:free"] is True
        assert states["openrouter:paid/model"] is False
        # And persisted:
        assert "openrouter:z-ai/glm-5.2:free" in cfg.get(
            "api.selected_free_models", []
        )

    def test_selection_persisted_across_provider_switch(self, qapp, tmp_path):
        cfg, tab = self._tab_with_catalogue(qapp, tmp_path, [
            {"id": "z-ai/glm-5.2:free", "pricing": {"prompt": "0", "completion": "0"}},
        ])
        tab._on_select_all_free()
        idx = tab._provider_combo.findData("groq")
        tab._provider_combo.setCurrentIndex(idx)
        assert cfg.get("api.selected_free_models") == [
            "openrouter:z-ai/glm-5.2:free"
        ]

    def test_auto_free_checkbox_persists(self, qapp, tmp_path):
        cfg, tab = self._tab(qapp, tmp_path)
        tab._btn_auto_free.setChecked(True)
        assert cfg.get("api.auto_free_models") is True
        tab._btn_auto_free.setChecked(False)
        assert cfg.get("api.auto_free_models") is False


class TestChatOnlineIndicator:
    def test_online_indicator_toggles(self, qapp):
        from ui.chat_widget import ChatWidget

        c = ChatWidget()
        assert c._online_label.isVisibleTo(c) is False
        c.set_online_active(True)
        assert c._online_label.isVisibleTo(c) is True
        c.set_online_active(False)
        assert c._online_label.isVisibleTo(c) is False


class TestFreeModelList:
    def test_curated_models_have_free_suffix(self):
        assert len(FREE_OPENROUTER_MODELS) >= 10
        assert all(m.endswith(":free") for m in FREE_OPENROUTER_MODELS)
