"""Inference state container.

Tracks the lifecycle of a single generation request.  In Phase 3 this is a
lightweight record-keeping helper; richer features (token budgeting,
interruption, partial results) arrive with the Agent System (Phase 9).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

from core.logger import get_logger

logger = get_logger("inference")


class InferenceStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class InferenceResult:
    """Captured result of a finished generation."""

    prompt: str
    response: str
    tokens_used: int = 0
    status: InferenceStatus = InferenceStatus.COMPLETED
    error: str | None = None


@dataclass
class InferenceSession:
    """Manages the state of one in-flight or completed generation."""

    prompt: str
    status: InferenceStatus = InferenceStatus.PENDING
    _tokens: list[str] = field(default_factory=list)
    _result: InferenceResult | None = None

    def start(self) -> None:
        self.status = InferenceStatus.RUNNING
        logger.debug("Inference session started (prompt=%d chars)", len(self.prompt))

    def add_token(self, token: str) -> None:
        self._tokens.append(token)

    @property
    def response(self) -> str:
        return "".join(self._tokens)

    @property
    def tokens_used(self) -> int:
        return len(self._tokens)

    def complete(self) -> InferenceResult:
        self.status = InferenceStatus.COMPLETED
        self._result = InferenceResult(
            prompt=self.prompt, response=self.response, tokens_used=self.tokens_used
        )
        logger.debug("Inference completed (%d tokens)", self.tokens_used)
        return self._result

    def fail(self, error: str) -> InferenceResult:
        self.status = InferenceStatus.ERROR
        self._result = InferenceResult(
            prompt=self.prompt, response="", status=InferenceStatus.ERROR, error=error
        )
        logger.error("Inference failed: %s", error)
        return self._result

    def stream(self, token_iter: Iterator[str]) -> str:
        """Consume a token iterator and assemble the final response."""
        self.start()
        try:
            for token in token_iter:
                self.add_token(token)
            return self.complete().response
        except Exception as exc:
            return self.fail(str(exc)).response
