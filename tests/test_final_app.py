"""Tests for Finalna Aplikacija standalone foundation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication, QWidget

# Ensure the standalone app root is importable when running tests from the
# ``tests/`` directory without installing the package.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ui.app_shell import AppShell
from ui.home_page import HomePage


class _FakeModel:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeModelManager:
    def __init__(self, models=None, default=None):
        self._models = models or []
        self._default = default
        self.selected = False

    def list_models(self):
        return self._models

    def select_default(self):
        self.selected = True
        return self._default


class _FakeEngine:
    def configure(self, model_manager) -> None:
        pass


class TestStartupModelLoadWorker:
    """Tests for _StartupModelLoadWorker thread lifecycle and signal handling."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def _run_worker(self, model_manager, engine):
        """Start the worker, wait for it to finish, process queued signals."""
        from app.application import _StartupModelLoadWorker

        worker = _StartupModelLoadWorker(model_manager, engine)
        result: list[tuple[str, str]] = []
        worker.success.connect(lambda name: result.append(("success", name)))
        worker.failure.connect(lambda err: result.append(("failure", err)))
        worker.start()
        assert worker.wait(5000), "worker thread did not finish within 5s"
        for _ in range(10):
            QCoreApplication.processEvents()
        worker.deleteLater()
        return worker, result

    def test_worker_emits_success_when_model_loaded(self) -> None:
        """Worker emits success(model_name) when a model is selected and
        the engine configures successfully."""
        mm = _FakeModelManager(
            models=[_FakeModel("test_model")],
            default=_FakeModel("test_model"),
        )
        _worker, result = self._run_worker(mm, _FakeEngine())
        assert ("success", "test_model") in result

    def test_worker_emits_failure_when_no_models(self) -> None:
        """Worker emits failure('No models available') when the model
        list is empty — the app should start in stub mode."""
        mm = _FakeModelManager(models=[])
        _worker, result = self._run_worker(mm, _FakeEngine())
        assert ("failure", "No models available") in result

    def test_worker_emits_failure_when_no_default_model(self) -> None:
        """Worker emits failure('No model loaded') when models exist
        but none is selected as default."""
        mm = _FakeModelManager(
            models=[_FakeModel("test_model")],
            default=None,
        )
        _worker, result = self._run_worker(mm, _FakeEngine())
        assert ("failure", "No model loaded") in result

    def test_worker_catches_exception_and_emits_failure(self) -> None:
        """Exceptions in run() are caught and emitted as failure signals —
        never swallowed, never crash the worker thread."""

        class _ExplodingModelManager:
            def list_models(self):
                raise RuntimeError("list_models exploded")

        _worker, result = self._run_worker(_ExplodingModelManager(), _FakeEngine())
        assert ("failure", "list_models exploded") in result

    def test_worker_emits_failure_on_engine_configure_error(self) -> None:
        """If engine.configure raises, the worker emits failure."""

        class _FailingEngine:
            def configure(self, model_manager):
                raise RuntimeError("configure failed")

        mm = _FakeModelManager(
            models=[_FakeModel("test_model")],
            default=_FakeModel("test_model"),
        )
        _worker, result = self._run_worker(mm, _FailingEngine())
        assert any(r[0] == "failure" for r in result)

    def test_worker_selects_default_before_configure(self) -> None:
        """The worker calls select_default() before engine.configure()."""
        mm = _FakeModelManager(
            models=[_FakeModel("test_model")],
            default=_FakeModel("test_model"),
        )
        engine = _FakeEngine()
        self._run_worker(mm, engine)
        assert mm.selected is True

    def test_worker_connects_finished_to_delete_later(self) -> None:
        """H1 contract: _start_model_load_worker must connect
        finished → deleteLater so the parentless QThread is reclaimed only
        after the thread fully exits.  The success/failure slots must NOT
        clear _model_load_worker (the reference stays owned until stop())."""
        import inspect

        from app.application import ApplicationManager

        source = (
            Path(__file__).resolve().parents[1] / "app" / "application.py"
        ).read_text(encoding="utf-8")
        assert "worker.finished.connect(worker.deleteLater)" in source
        # The slots no longer drop the only reference (H1 fix); only
        # stop() clears it.
        for slot in (
            ApplicationManager._on_startup_model_loaded,
            ApplicationManager._on_startup_model_load_failed,
        ):
            slot_source = inspect.getsource(slot)
            assert "_model_load_worker = None" not in slot_source


class TestStopWaitsForRunningWorker:
    """Shutdown ordering: stop() must fully join the startup worker before
    model/engine teardown proceeds."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_stop_waits_for_running_worker(self) -> None:
        """A running worker is waited for and has exited by the time stop()
        returns — teardown never proceeds under a live thread."""
        from PySide6.QtCore import QThread

        from app.application import ApplicationManager

        class _ShortWorker(QThread):
            # Deterministic, fast: sleep briefly so isRunning() is True
            # when stop() first checks.
            def run(self) -> None:
                import time

                time.sleep(0.05)

        mgr = ApplicationManager()
        mgr._started = True
        worker = _ShortWorker()
        worker.start()
        mgr._model_load_worker = worker

        mgr.stop()  # must not raise, must wait

        assert worker.isRunning() is False
        assert mgr._model_load_worker is None
        worker.wait(1000)  # belt-and-suspenders for the test itself


class TestStartupSlotsNoopDuringShutdown:
    """Late worker signals must not publish lifecycle events once
    shutdown has started."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_startup_slots_noop_during_shutdown(self) -> None:
        from app.application import ApplicationManager

        class _RecordingBus:
            def __init__(self) -> None:
                self.published: list[tuple[str, dict]] = []

            def publish(self, event_type: str, data: dict | None = None) -> None:
                self.published.append((event_type, data or {}))

        mgr = ApplicationManager()
        mgr._event_bus = _RecordingBus()
        mgr._model_load_worker = object()  # sentinel: must stay untouched
        sentinel = mgr._model_load_worker
        mgr._shutting_down = True

        mgr._on_startup_model_loaded("test_model")
        mgr._on_startup_model_load_failed("boom")

        assert mgr._event_bus.published == []
        assert mgr._model_load_worker is sentinel


class _CleanupCallRecorder:
    """Minimal manager-section test double for M3 isolation tests."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def close(self) -> None:
        self.calls.append("close")
        if self.fail:
            raise RuntimeError("close exploded")

    def stop(self) -> None:
        self.calls.append("stop")
        if self.fail:
            raise RuntimeError("stop exploded")

    def unload(self) -> None:
        self.calls.append("unload")
        if self.fail:
            raise RuntimeError("unload exploded")


class TestStopCleanupIsolation:
    """M3: one failing cleanup section must not truncate the rest of
    shutdown."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    @staticmethod
    def _make_manager():
        from app.application import ApplicationManager

        mgr = ApplicationManager()
        mgr._started = True
        return mgr

    def test_stop_survives_memory_close_failure(self) -> None:
        """memory.close() raising must not skip assistant/db/voice/window
        cleanup."""
        from app.application import ApplicationManager

        mgr: ApplicationManager = self._make_manager()

        class _RaisingMemory:
            def close(self) -> None:
                raise RuntimeError("memory close exploded")

        assistant = _CleanupCallRecorder()
        db = _CleanupCallRecorder()
        voice = _CleanupCallRecorder()
        window_calls: list[str] = []

        class _WindowStub:
            def _unsubscribe_all_events(self) -> None:
                window_calls.append("unsubscribe")

            # _voice attribute break is exercised via close()
            _voice = object()

            def close(self) -> None:
                window_calls.append("close")

        mgr._memory = _RaisingMemory()
        mgr._assistant = assistant
        mgr._db_manager = db
        mgr._voice = voice
        mgr._window = _WindowStub()

        mgr.stop()  # must not raise

        assert assistant.calls == ["stop"]
        assert db.calls == ["close"]
        assert voice.calls == ["stop"]
        assert window_calls == ["unsubscribe", "close"]

    def test_stop_survives_db_close_failure(self) -> None:
        """db.close() raising must not skip voice/window cleanup."""
        from app.application import ApplicationManager

        mgr: ApplicationManager = self._make_manager()

        class _RaisingDb:
            def close(self) -> None:
                raise RuntimeError("db close exploded")

        voice = _CleanupCallRecorder()
        window_calls: list[str] = []

        class _WindowStub:
            def _unsubscribe_all_events(self) -> None:
                window_calls.append("unsubscribe")

            _voice = object()

            def close(self) -> None:
                window_calls.append("close")

        mgr._memory = _CleanupCallRecorder()
        mgr._db_manager = _RaisingDb()
        mgr._voice = voice
        mgr._window = _WindowStub()

        mgr.stop()  # must not raise

        assert voice.calls == ["stop"]
        assert window_calls == ["unsubscribe", "close"]


class TestCoordinatorDoubleShutdown:
    """The already-audited contract: coordinator shutdown is safe twice
    (AppShell.closeEvent + ApplicationManager.stop() both call it)."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_coordinator_double_shutdown_idempotent(self) -> None:
        """Two consecutive shutdown() calls: no exception, unwired, no
        subscription IDs left, second call is a no-op."""
        from core.event_bus import EventBus
        from ui.chat_voice_coordinator import ChatVoiceCoordinator
        from ui.chat_widget import ChatWidget

        bus = EventBus()
        chat = ChatWidget()
        coordinator = ChatVoiceCoordinator(
            chat=chat,
            assistant=None,
            voice_manager=None,
            event_bus=bus,
        )
        coordinator.wire()
        assert coordinator._wired is True
        assert coordinator._sub_ids  # wired: has subscriptions

        coordinator.shutdown()
        first_state = (coordinator._wired, list(coordinator._sub_ids))

        coordinator.shutdown()  # second call — must be a no-op

        assert first_state == (False, [])
        assert coordinator._wired is False
        assert coordinator._sub_ids == []
        assert coordinator._generation_worker is None


class TestApplicationFinalLifecycle:
    """Tests for application_final.main() exception-driven cleanup."""

    def test_main_calls_stop_on_startup_failure(self) -> None:
        """If start() raises, the finally block calls stop() before the
        exception propagates — resources are not leaked."""
        from app.application_final import main

        with patch("app.application_final.ApplicationManager") as MockMgr:
            instance = MockMgr.return_value
            instance.start.side_effect = RuntimeError("startup failed")
            instance.stop = MagicMock()

            with pytest.raises(RuntimeError, match="startup failed"):
                main()

            instance.stop.assert_called_once()

    def test_main_calls_stop_on_nonzero_exit(self) -> None:
        """If start() returns non-zero, the finally block calls stop()."""
        from app.application_final import main

        with patch("app.application_final.ApplicationManager") as MockMgr:
            instance = MockMgr.return_value
            instance.start.return_value = 1
            instance.stop = MagicMock()

            result = main()

            assert result == 1
            instance.stop.assert_called_once()

    def test_main_has_try_finally_structure(self) -> None:
        """main() source must contain a try/finally for cleanup."""
        source = (
            Path(__file__).resolve().parents[1] / "app" / "application_final.py"
        ).read_text(encoding="utf-8")
        assert "finally:" in source
        assert source.count("manager.stop()") >= 2  # aboutToQuit + finally


class TestAppShell:
    """Verify AppShell instantiates and navigates."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_shell_creates_with_defaults(self) -> None:
        shell = AppShell(theme=None, pages=[("Home", QWidget())])
        assert shell is not None
        assert shell._default_route == "Home"

    def test_shell_default_route(self) -> None:
        page = QWidget()
        shell = AppShell(theme=None, pages=[("Home", page)], default_route="Home")
        assert shell._pages_widget.currentWidget() is page

    def test_shell_navigate_changes_page(self) -> None:
        home = QWidget()
        chat = QWidget()
        shell = AppShell(theme=None, pages=[("Home", home), ("Chat", chat)])
        shell._navigate("Chat")
        assert shell._pages_widget.currentWidget() is chat

    def test_shell_navigate_unknown_route(self) -> None:
        home = QWidget()
        shell = AppShell(theme=None, pages=[("Home", home)])
        shell._navigate("Nonexistent")
        assert shell._pages_widget.currentWidget() is home


class TestHomePage:
    """Verify HomePage instantiates and displays."""

    @pytest.fixture(autouse=True)
    def _qapp(self, qapp: QApplication) -> None:
        self.qapp = qapp

    def test_home_page_creates(self) -> None:
        page = HomePage(theme=None, assistant_name="Test")
        assert page is not None

    def test_home_page_has_cards(self) -> None:
        page = HomePage(theme=None, assistant_name="Test")
        assert page._ai_card is not None
        assert page._system_card is not None
        assert page._memory_card is not None
        assert page._privacy_card is not None
