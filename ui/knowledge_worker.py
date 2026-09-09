"""Off-GUI-thread knowledge base operations (Phase 10 Task 4, H3).

Knowledge search (embedding + full vector scan) and indexing (recursive
directory walk + chunk + embed per chunk) are far too expensive to run
on the GUI thread.  These QThread workers run them off-thread and
deliver results back through queued signals, mirroring the established
worker patterns in this codebase (generation/download/automation
workers).

The MainWindow handlers and the AppShell dashboard wiring both use
these workers, so the heavy knowledge operations never block the UI
regardless of which surface initiated them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QThread, Signal, Slot

from core.logger import get_logger

logger = get_logger("ui.knowledge_worker")


class KnowledgeSearchWorker(QThread):
    """Run a knowledge-base search off the GUI thread.

    Emits ``search_completed(context, results)`` on completion (queued
    to the GUI thread by Qt automatically) or ``search_failed(error)``.
    """

    search_completed = Signal(str, list)
    search_failed = Signal(str)

    def __init__(self, runner: Callable[[str], tuple[str, list]], query: str, parent=None) -> None:
        super().__init__(parent)
        self._runner = runner
        self._query = query

    def run(self) -> None:
        try:
            context, results = self._runner(self._query)
        except Exception as exc:
            logger.warning("Knowledge search failed: %s", exc, exc_info=True)
            self.search_failed.emit(str(exc))
            return
        self.search_completed.emit(context, list(results))


class KnowledgeIndexWorker(QThread):
    """Run a knowledge-base indexing operation off the GUI thread.

    ``operation`` is one of "index_directory", "index_document", or
    "rebuild".  Emits ``index_completed(count, message)`` or
    ``index_failed(error)``.
    """

    index_completed = Signal(int, str)
    index_failed = Signal(str)

    def __init__(
        self,
        knowledge: Any,
        operation: str,
        target: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._knowledge = knowledge
        self._operation = operation
        self._target = target

    def run(self) -> None:
        fn = getattr(self._knowledge, self._operation, None)
        if fn is None:
            self.index_failed.emit(f"unknown knowledge operation: {self._operation}")
            return
        try:
            count = fn(self._target)
        except Exception as exc:
            logger.warning("Knowledge %s failed: %s", self._operation, exc, exc_info=True)
            self.index_failed.emit(str(exc))
            return
        self.index_completed.emit(int(count), self._operation)


@Slot()
def start_knowledge_search(
    assistant: Any,
    query: str,
    on_completed: Callable[[str, list], None],
    on_failed: Callable[[str], None],
    holder: list,
) -> None:
    """Create, start, and track a :class:`KnowledgeSearchWorker`.

    ``holder`` is a list the worker is appended to so the caller can keep
    a Python reference (preventing premature GC) and wait on close.
    """
    knowledge = getattr(assistant, "knowledge", None)
    if knowledge is None:
        on_failed("knowledge base unavailable")
        return

    def _run(q: str) -> tuple[str, list]:
        return assistant.run_knowledge_search(q)

    worker = KnowledgeSearchWorker(_run, query)
    worker.search_completed.connect(on_completed)
    worker.search_failed.connect(on_failed)
    holder.append(worker)
    worker.start()


@Slot()
def start_knowledge_index(
    knowledge: Any,
    operation: str,
    target: str,
    on_completed: Callable[[int, str], None],
    on_failed: Callable[[str], None],
    holder: list,
) -> None:
    """Create, start, and track a :class:`KnowledgeIndexWorker`."""
    worker = KnowledgeIndexWorker(knowledge, operation, target)
    worker.index_completed.connect(on_completed)
    worker.index_failed.connect(on_failed)
    holder.append(worker)
    worker.start()
