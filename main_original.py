"""Entry point for the Offline AI Assistant.

Starts the Qt application via :class:`ApplicationManager`.

Usage:
    python main.py              # Start the GUI application
    python main.py --test-runtime  # Run real GGUF runtime acceptance test
"""

from __future__ import annotations

import argparse
import sys

from core.exceptions import AssistantError
from core.logger import get_logger


def _test_runtime() -> int:
    """Run the real GGUF runtime acceptance test.

    This verifies that:
    1. Models are discovered from local storage
    2. llama-cpp-python is importable
    3. A model can be activated and loaded
    4. Real inference produces a non-stub response
    5. GGUFModelLoader is used (not StubModelLoader)
    """
    logger = get_logger("main")
    logger.info("=" * 60)
    logger.info("REAL GGUF RUNTIME TEST — starting")
    logger.info("=" * 60)

    try:

        from ai.engine.llm_engine import GenerationConfig, LlamaCppEngine
        from ai.models.discovery import discover_all_models
        from ai.models.model_loader import GGUFModelLoader, has_llama_cpp
        from ai.models.model_manager import ModelManager
        from core.exceptions import ModelError

        if not has_llama_cpp():
            logger.error("llama-cpp-python is NOT installed — cannot test real runtime")
            print("FAIL: llama-cpp-python is not installed")
            return 1

        models = discover_all_models()
        logger.info("Discovered %d model(s)", len(models))

        if not models:
            logger.error("No models discovered")
            print("FAIL: No models discovered")
            return 1

        for m in models:
            logger.info(
                "  Model: %s [source=%s] path=%s size=%.1fMB",
                m.name, m.source.value, m.path, m.size_mb,
            )

        target = models[0]
        logger.info("Activating model: %s", target.name)

        mm = ModelManager(
            models_dir=target.path.parent,
            search_paths=[target.path.parent],
            auto_gpu_layers=True,
            include_ollama=False,
            include_lm_studio=False,
        )
        mm._models = [target]

        try:
            mm.activate_model(target.name)
        except ModelError as exc:
            logger.error("Model activation failed: %s", exc)
            print(f"FAIL: Model activation failed: {exc}")
            return 1

        loader = mm.get_loader()
        if loader.is_stub:
            logger.error("StubModelLoader was used — FAIL")
            print("FAIL: StubModelLoader was used instead of GGUFModelLoader")
            return 1

        if not isinstance(loader, GGUFModelLoader):
            logger.error("Loader is not GGUFModelLoader")
            print("FAIL: Loader is not GGUFModelLoader")
            return 1

        logger.info("Model loaded successfully — loader=%s", type(loader).__name__)

        engine = LlamaCppEngine()
        engine.configure(mm)

        if not engine.is_ready:
            logger.error("Engine is not ready")
            print("FAIL: Engine is not ready")
            return 1

        logger.info("Engine ready — model=%s gpu_layers=%d", engine.model_name, engine.gpu_layers)

        logger.info("Sending real prompt to model...")
        response = engine.generate(
            "Hello. What is 2+2?",
            config=GenerationConfig(max_tokens=32),
        )

        real_response = response.strip()
        logger.info("REAL GGUF RUNTIME SUCCESS: %s", target.name)
        logger.info("GPU layers: %d", mm.active_gpu_layers)
        logger.info("Response: %s", real_response[:200])

        print(f"REAL GGUF RUNTIME SUCCESS: {target.name}")
        print(f"GPU layers: {mm.active_gpu_layers}")
        print(f"Response: {real_response[:200]}")

        if "placeholder" in real_response.lower() or "stub" in real_response.lower():
            logger.error("Response contains stub/placeholder text")
            print("FAIL: Response contains stub/placeholder text")
            return 1

        return 0

    except Exception as exc:
        logger.exception("Runtime test failed with exception")
        print(f"FAIL: Exception: {exc}")
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline AI Assistant")
    parser.add_argument(
        "--test-runtime",
        action="store_true",
        help="Run real GGUF runtime acceptance test and exit",
    )
    args = parser.parse_args()

    if args.test_runtime:
        return _test_runtime()

    logger = get_logger("main")
    logger.info("=" * 60)
    logger.info("Offline AI Assistant — starting (Phase 13.1)")
    logger.info("=" * 60)

    try:
        from app.application import ApplicationManager

        manager = ApplicationManager()
        return manager.run()
    except AssistantError as exc:
        logger.error("Assistant error: %s", exc)
        return 1
    except Exception:
        logger.exception("Unexpected error during startup")
        return 1


if __name__ == "__main__":
    sys.exit(main())
