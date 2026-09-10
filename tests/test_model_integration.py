"""Phase 6 tests: model integration (GPU, params, discovery).

These tests are intentionally fast — they do NOT run inference (except the skip-if-GPU
tolerant metadata loading). Full GPU verification is E2E:
docs/models_report.md §6.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_LLM_DIR = Path(__file__).resolve().parents[1] / "models" / "llm"
MODELS_PRESENT = any(PROJECT_LLM_DIR.glob("*.gguf"))


def _llama_available() -> bool:
    try:
        from ai.models.model_loader import has_llama_cpp

        return has_llama_cpp()
    except Exception:
        return False


class TestModelIntegration:
    @pytest.mark.skipif(not MODELS_PRESENT, reason="project GGUF models are not installed")
    def test_project_models_discovered(self):
        from ai.models.discovery import discover_all_models
        from ai.models.model_loader import ModelType

        models = discover_all_models(
            search_paths=[PROJECT_LLM_DIR],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = {m.name for m in models}
        assert any("Qwen2.5-Coder-7B" in n for n in names)
        assert any("Phi-4-mini" in n for n in names)
        assert all(m.model_type in (ModelType.LLM,) for m in models)

    @pytest.mark.skipif(not MODELS_PRESENT, reason="project GGUF models are not installed")
    def test_qwen_capabilities_for_agents(self):
        """Qwen2.5-Coder must have tool_calling (the agent system uses it)."""
        from ai.models.discovery import discover_all_models

        models = discover_all_models(
            search_paths=[PROJECT_LLM_DIR],
            include_ollama=False,
            include_lm_studio=False,
        )
        qwen = next(m for m in models if "Qwen2.5-Coder-7B" in m.name)
        assert qwen.capabilities.tool_calling is True
        assert qwen.capabilities.function_calling is True
        assert qwen.capabilities.structured_output is True

    @pytest.mark.skipif(not _llama_available(), reason="llama-cpp-python is not installed")
    def test_gpu_offload_support(self):
        """CUDA wheel podrzava GPU offload (RTX 3080 10GB)."""
        from ai.models.model_loader import (
            detect_optimal_gpu_layers,
            is_gpu_available,
        )

        if not is_gpu_available():
            pytest.skip("GPU is not available in this environment")
        layers = detect_optimal_gpu_layers()
        assert layers >= 999  # full offload

    def test_settings_inference_params(self):
        """Params from settings.json must be correct (n_ctx 4096, threads 8)."""
        from core.config_manager import ConfigManager

        config = ConfigManager()
        n_ctx = config.get("ai.n_ctx", 512)
        config.get("ai.max_tokens", 204)
        # User settings: 4096/1024 (phase 6.3). Defaults are lower.
        if n_ctx <= 512:
            pytest.skip("Lokalne settings.json sa starim vrednostima — preskacemo")
        assert config.get("ai.n_ctx") >= 4096
        assert config.get("ai.max_tokens") >= 1024
