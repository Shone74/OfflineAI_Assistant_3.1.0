"""Performance profiling utilities for model inference."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger

logger = get_logger("performance")


@dataclass
class InferenceMetrics:
    """Metrics for a single inference run."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0.0
    load_time_seconds: float = 0.0
    inference_time_seconds: float = 0.0
    memory_usage_mb: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "tokens_per_second": round(self.tokens_per_second, 2),
            "load_time_seconds": round(self.load_time_seconds, 2),
            "inference_time_seconds": round(self.inference_time_seconds, 2),
            "memory_usage_mb": round(self.memory_usage_mb, 1),
            "error": self.error,
        }


class PerformanceProfiler:
    """Tracks performance metrics for model operations."""

    def __init__(self) -> None:
        self._load_start: float = 0.0
        self._inference_start: float = 0.0
        self._prompt_tokens: int = 0
        self._completion_tokens: int = 0

    def start_load_timer(self) -> None:
        self._load_start = time.perf_counter()

    def end_load_timer(self) -> float:
        elapsed = time.perf_counter() - self._load_start
        logger.debug("Model load time: %.2fs", elapsed)
        return elapsed

    def start_inference_timer(self) -> None:
        self._inference_start = time.perf_counter()

    def end_inference_timer(self, completion_tokens: int) -> InferenceMetrics:
        elapsed = time.perf_counter() - self._inference_start
        tokens_per_second = completion_tokens / elapsed if elapsed > 0 else 0.0
        metrics = InferenceMetrics(
            prompt_tokens=self._prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=self._prompt_tokens + completion_tokens,
            tokens_per_second=tokens_per_second,
            inference_time_seconds=elapsed,
        )
        logger.info(
            "Inference: %d tokens in %.2fs (%.1f tok/s)",
            completion_tokens, elapsed, tokens_per_second,
        )
        return metrics

    def set_prompt_tokens(self, count: int) -> None:
        self._prompt_tokens = count

    def get_memory_usage(self) -> float:
        try:
            import psutil
            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0
