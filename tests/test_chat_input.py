"""Tests for the chat input bar — multiline sizing and Enter/Shift+Enter UX.

Requirements covered:
  * At least 4 lines are always visible in the message input.
  * The input grows up to 8 lines; further text is reachable via scrollbar.
  * Enter / keypad Enter sends the message (no stray newline).
  * Shift+Enter (and Ctrl+Enter) insert a newline without sending.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("OFFLINE_AI_TEST_MODE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

from ui.chat_widget import ChatWidget


def _press(qapp: QApplication, edit, key: Qt.Key, modifier: Qt.KeyboardModifier) -> None:
    """Deliver a KeyPress event directly to the input widget."""
    ev = QKeyEvent(QEvent.Type.KeyPress, key, modifier)
    QApplication.sendEvent(edit, ev)
    qapp.processEvents()


class TestInputSizing:
    def test_minimum_four_lines_visible(self, qapp):
        c = ChatWidget()
        min_h = ChatWidget._MIN_INPUT_LINES * ChatWidget._LINE_HEIGHT_PX
        assert ChatWidget._MIN_INPUT_LINES == 4
        assert ChatWidget._MAX_INPUT_LINES == 8
        assert c._input.minimumHeight() == min_h

    def test_grows_with_content_within_bounds(self, qapp):
        c = ChatWidget()
        c.resize(900, 700)
        c.show()
        qapp.processEvents()
        min_h = ChatWidget._MIN_INPUT_LINES * ChatWidget._LINE_HEIGHT_PX
        max_h = ChatWidget._MAX_INPUT_LINES * ChatWidget._LINE_HEIGHT_PX
        c._input.setPlainText("l1\nl2\nl3\nl4\nl5\nl6")
        qapp.processEvents()
        assert min_h <= c._input.height() <= max_h

    def test_caps_at_eight_lines_then_scrolls(self, qapp):
        c = ChatWidget()
        c.resize(900, 700)
        c.show()
        qapp.processEvents()
        max_h = ChatWidget._MAX_INPUT_LINES * ChatWidget._LINE_HEIGHT_PX
        c._input.setPlainText("\n".join(f"row {i}" for i in range(40)))
        qapp.processEvents()
        assert c._input.maximumHeight() == max_h
        assert c._input.height() <= max_h


class TestEnterToSend:
    def test_bare_enter_sends_and_clears(self, qapp):
        c = ChatWidget()
        captured: list[str] = []
        c.send_requested.connect(lambda t: captured.append(t))
        c._input.setPlainText("hello world")
        qapp.processEvents()
        _press(qapp, c._input, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        assert captured == ["hello world"]
        assert c._input.toPlainText() == ""

    def test_keypad_enter_sends(self, qapp):
        c = ChatWidget()
        captured: list[str] = []
        c.send_requested.connect(lambda t: captured.append(t))
        c._input.setPlainText("numpad")
        _press(qapp, c._input, Qt.Key.Key_Enter, Qt.KeyboardModifier.NoModifier)
        assert captured == ["numpad"]

    def test_shift_enter_newline_without_sending(self, qapp):
        c = ChatWidget()
        captured: list[str] = []
        c.send_requested.connect(lambda t: captured.append(t))
        c._input.setPlainText("first")
        _press(qapp, c._input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert "\n" in c._input.toPlainText()
        assert captured == []  # nothing sent

    def test_ctrl_enter_newline_without_sending(self, qapp):
        c = ChatWidget()
        captured: list[str] = []
        c.send_requested.connect(lambda t: captured.append(t))
        c._input.setPlainText("ctrl-line")
        _press(qapp, c._input, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        assert "\n" in c._input.toPlainText()
        assert captured == []

    def test_empty_input_enter_is_noop(self, qapp):
        c = ChatWidget()
        captured: list[str] = []
        c.send_requested.connect(lambda t: captured.append(t))
        c._input.clear()
        qapp.processEvents()
        _press(qapp, c._input, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)
        assert captured == []
        assert not c._send_btn.isEnabled()

    def test_send_button_disabled_for_whitespace_only(self, qapp):
        c = ChatWidget()
        c._input.setPlainText("   \n  ")
        qapp.processEvents()
        assert not c._send_btn.isEnabled()


class TestPlaceholder:
    def test_placeholder_mentions_enter(self, qapp):
        c = ChatWidget()
        ph = c._input.placeholderText()
        assert "Enter" in ph and "Shift" in ph
