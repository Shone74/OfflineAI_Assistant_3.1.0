"""Chat widget — message list plus a text-input bar with a send button."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent, QTextDocument
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class MessageRole:
    USER = "user"
    ASSISTANT = "assistant"


def _render_markdown(text: str) -> str:
    def _code_block(match: re.Match[str]) -> str:
        code = match.group(1)
        escaped = (
            code.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        return (
            "<pre>"
            f"<code>{escaped}</code>"
            "<button style='font-size:10px;padding:2px 6px;'>Copy</button>"
            "</pre>"
        )

    text = re.sub(r"```(.*?)```", _code_block, text, flags=re.DOTALL)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"`{1,3}(.+?)`{1,3}", r"<code>\1</code>", text)
    text = text.replace("\n", "<br>")
    return text


class RichTextDelegate(QStyledItemDelegate):
    """Delegate that renders HTML content in QListWidgetItem with word wrapping."""

    def displayText(self, value: Any, locale: Any) -> str:
        return str(value)

    def initStyleOption(self, option: Any, index: Any) -> None:
        super().initStyleOption(option, index)


    @staticmethod
    def _make_doc(text: str, width: int, font: Any) -> QTextDocument:
        """Create a QTextDocument with consistent configuration for both
        sizeHint and paint so heights match the rendered output exactly."""
        doc = QTextDocument()
        doc.setHtml(text)
        doc.setTextWidth(width)
        doc.setDocumentMargin(0)
        doc.setDefaultFont(font)
        return doc

    def sizeHint(self, option: Any, index: Any) -> QSize:
        if option.rect.width() <= 0:
            return QSize(50, 20)
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text:
            text = option.text
        doc = self._make_doc(str(text), option.rect.width(), option.font)
        height = int(doc.size().height()) + 12
        return QSize(option.rect.width(), height)

    def paint(self, painter: Any, option: Any, index: Any) -> None:
        painter.save()
        text = index.data(Qt.ItemDataRole.DisplayRole)
        if not text:
            text = option.text
        doc = self._make_doc(str(text), option.rect.width(), option.font)
        painter.translate(option.rect.left(), option.rect.top())
        doc.drawContents(painter)
        painter.restore()

    def updateEditorGeometry(self, editor: Any, option: Any, index: Any) -> None:
        editor.setGeometry(option.rect)


class ChatWidget(QWidget):
    """Central chat display with an input bar at the bottom."""

    MAX_MESSAGES = 500

    send_requested = Signal(str)
    voice_requested = Signal()
    play_requested = Signal()
    stop_generation = Signal()
    new_chat_requested = Signal()
    search_requested = Signal(str)
    message_deleted = Signal(int)

    def __init__(self) -> None:
        super().__init__()
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(8)

        self._header = self._build_header()
        self._layout.addLayout(self._header)

        self._message_list = QListWidget()
        self._message_list.setObjectName("messageList")
        self._message_list.setStyleSheet(
            "#messageList { border: none; border-radius: 0px; }"
        )
        self._message_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._message_list.customContextMenuRequested.connect(self._on_message_context_menu)
        self._message_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self._message_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._message_list.setWordWrap(True)
        self._message_list.setItemDelegate(RichTextDelegate(self._message_list))
        self._layout.addWidget(self._message_list)

        self._input_bar = self._build_input_bar()
        self._layout.addLayout(self._input_bar)

        self._streaming_item: QListWidgetItem | None = None
        self._streaming_text = ""
        self._streaming_timestamp = ""
        self._is_streaming = False
        self._last_response_streamed = False

        self.send_requested.connect(self._on_send)
        self.stop_generation.connect(self._on_stop_generation)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(50, self._recalc_all_size_hints_and_redraw)

    def _recalc_all_size_hints(self) -> None:
        """Recalculate and set sizeHint for every item based on current viewport width."""
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QStyleOptionViewItem
        width = self._message_list.viewport().width()
        if width <= 0:
            return
        delegate = self._message_list.itemDelegate()
        for i in range(self._message_list.count()):
            item = self._message_list.item(i)
            if item is None:
                continue
            option = QStyleOptionViewItem()
            option.rect = QRect(0, 0, width, 0)
            option.text = item.text()
            option.font = self._message_list.font()
            hint = delegate.sizeHint(option, self._message_list.model().index(i, 0))
            item.setSizeHint(QSize(width, hint.height()))

    def _recalc_all_size_hints_and_redraw(self) -> None:
        self._recalc_all_size_hints()
        self._message_list.update()
        self._message_list.viewport().update()
        from PySide6.QtCore import QModelIndex
        self._message_list.model().dataChanged.emit(QModelIndex(), QModelIndex())

    message_copied = Signal(str)
    message_edit_requested = Signal(int, str)

    # ------------------------------------------------------------------ #
    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self._btn_new_chat = QPushButton("New Chat")
        self._btn_export = QPushButton("Export")
        self._btn_export_selected = QPushButton("Export Selected")
        self._btn_search = QPushButton("Search Memory")
        self._project_label = QLabel()
        self._project_label.setStyleSheet("color: #1D8A68; font-size: 10px; font-weight: 600;")
        self._project_label.setVisible(False)

        layout.addWidget(self._btn_new_chat)
        layout.addWidget(self._btn_export)
        layout.addWidget(self._btn_export_selected)
        layout.addWidget(self._btn_search)
        layout.addWidget(self._project_label)
        layout.addStretch()

        self._btn_new_chat.clicked.connect(self._on_new_chat)
        self._btn_export.clicked.connect(self._on_export)
        self._btn_export_selected.clicked.connect(self._on_export_selected)
        self._btn_search.clicked.connect(self._on_search)

        return layout

    def set_project_context(self, project_name: str, project_id: str | None = None) -> None:
        """Display the active project context in the chat header."""
        self._project_label.setText(f"Project: {project_name}")
        self._project_label.setVisible(True)
        self._project_label.setToolTip(f"Active project: {project_name}" + (f" ({project_id})" if project_id else ""))

    def clear_project_context(self) -> None:
        """Clear the project context display from the chat header."""
        self._project_label.setVisible(False)
        self._project_label.setText("")

    def _on_new_chat(self) -> None:
        self.clear()
        self.new_chat_requested.emit()

    def _on_export(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Conversation",
            "conversation.txt",
            "Text Files (*.txt);;Markdown Files (*.md);;JSON Files (*.json)",
        )
        if not path:
            return
        if selected_filter == "JSON Files (*.json)" or path.endswith(".json"):
            text = self.export_conversation_json()
        elif selected_filter == "Markdown Files (*.md)" or path.endswith(".md"):
            text = self.export_conversation_markdown()
        else:
            text = self.export_conversation()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _on_export_selected(self) -> None:
        """Export only the currently selected messages."""
        from PySide6.QtWidgets import QMessageBox

        selected = self._message_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "No Selection", "Please select messages to export first.")
            return
        text = self.export_selected_messages()
        if not text:
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Selected Messages",
            "selected_messages.txt",
            "Text Files (*.txt)",
        )
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    def _on_search(self) -> None:
        from PySide6.QtWidgets import QInputDialog
        query, ok = QInputDialog.getText(self, "Search Memory", "Enter search query:")
        if not ok or not query.strip():
            return
        self.search_requested.emit(query)

    # ------------------------------------------------------------------ #
    def _build_input_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Enter message...")
        self._input.setFixedHeight(30)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.setAccessibleName("Chat message input")
        layout.addWidget(self._input, stretch=1)

        self._send_btn = QPushButton("Send")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._send_btn.setAccessibleName("Send message")
        self._send_btn.setStyleSheet(
            "QPushButton { padding: 4px 12px; border-radius: 6px; }"
            "QPushButton { background: #1D8A68; color: #EDF3F0; border: none; }"
            "QPushButton:hover { background: #249E78; }"
            "QPushButton:pressed { background: #245846; }"
        )
        layout.addWidget(self._send_btn)

        self._stop_btn = QPushButton("\u25a0")
        self._stop_btn.setToolTip("Stop generation")
        self._stop_btn.setAccessibleName("Stop generation")
        self._stop_btn.setFixedSize(30, 30)
        self._stop_btn.setStyleSheet(
            "QPushButton { border-radius: 15px; color: #D96565; border: none; }"
            "QPushButton:hover { background: #1C2221; }"
        )
        self._stop_btn.clicked.connect(self.stop_generation)
        self._stop_btn.setVisible(False)
        layout.addWidget(self._stop_btn)

        # Voice controls: a state-driven REC/STOP/PROCESSING toggle plus a PLAY
        # button that replays the most recent captured WAV.
        self._voice_btn = QPushButton("REC")
        self._voice_btn.setToolTip("Voice input")
        self._voice_btn.setAccessibleName("Voice input toggle")
        self._voice_btn.clicked.connect(self._on_voice_clicked)
        self._voice_btn.setMinimumWidth(80)
        self._voice_btn.setFixedHeight(30)
        self._voice_btn.setStyleSheet(
            "QPushButton { border-radius: 6px; color: #8C9692; "
            "border: 1px solid #3A3F3E; background: #2A2E2D; }"
            "QPushButton:hover { background: #1C2221; }"
            "QPushButton:disabled { color: #5A605F; background: #1F2221; }"
        )
        layout.addWidget(self._voice_btn)

        self._play_btn = QPushButton("PLAY")
        self._play_btn.setToolTip("Play latest recording")
        self._play_btn.setAccessibleName("Play latest recording")
        self._play_btn.clicked.connect(self._on_play_clicked)
        self._play_btn.setMinimumWidth(60)
        self._play_btn.setFixedHeight(30)
        self._play_btn.setStyleSheet(
            "QPushButton { border-radius: 6px; color: #8C9692; "
            "border: 1px solid #3A3F3E; background: #2A2E2D; }"
            "QPushButton:hover { background: #1C2221; }"
        )
        self._play_btn.setVisible(False)
        layout.addWidget(self._play_btn)

        return layout

    # ------------------------------------------------------------------ #
    def _on_text_changed(self) -> None:
        self._send_btn.setEnabled(bool(self._input.toPlainText().strip()))

    def _on_send_clicked(self) -> None:
        text = self._input.toPlainText().strip()
        if text:
            self.send_requested.emit(text)
            self._input.clear()

    def _on_voice_clicked(self) -> None:
        self.voice_requested.emit()

    def _on_play_clicked(self) -> None:
        self.play_requested.emit()

    def set_voice_state(self, state: str, error_msg: str | None = None) -> None:
        """Reflect the VoiceManager lifecycle on the mic button.

        ``state`` is one of ``"idle"``, ``"recording"``, ``"processing"``,
        ``"speaking"`` or ``"error"`` (the ``VoiceState`` enum value). The button
        text and tool-tip update immediately so the user never has to guess
        whether recording or processing is active.
        """
        recording = state == "recording"
        processing = state == "processing"
        speaking = state == "speaking"
        if processing:
            self._voice_btn.setText("PROCESSING...")
            self._voice_btn.setEnabled(False)
            self._voice_btn.setToolTip("Transcribing...")
        elif recording:
            self._voice_btn.setText("STOP")
            self._voice_btn.setEnabled(True)
            self._voice_btn.setToolTip("Stop recording")
        elif speaking:
            self._voice_btn.setText("SPEAKING")
            self._voice_btn.setEnabled(False)
            self._voice_btn.setToolTip("Speaking… microphone disabled")
        else:
            self._voice_btn.setText("REC")
            self._voice_btn.setEnabled(True)
            if error_msg:
                self._voice_btn.setToolTip(f"Voice error: {error_msg}")
            else:
                self._voice_btn.setToolTip("Voice input")

    def set_play_available(self, available: bool) -> None:
        """Show/enable the PLAY control only when a recording is retained."""
        self._play_btn.setVisible(bool(available))
        self._play_btn.setEnabled(bool(available))

    def set_voice_active(self, active: bool) -> None:
        """Backward-compatible shim mapping a boolean to a voice state."""
        self.set_voice_state("recording" if active else "idle")

    def _on_send(self, text: str) -> None:
        self.add_message(MessageRole.USER, text)

    # ------------------------------------------------------------------ #
    def _update_item_size_hint(self, item: QListWidgetItem) -> None:
        """Force the QListWidgetItem to recalculate its height from current text."""
        width = self._message_list.viewport().width()
        if width <= 0:
            width = self._message_list.width()
        delegate = self._message_list.itemDelegate()
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QStyleOptionViewItem
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, width, 0)
        option.text = item.text()
        option.font = self._message_list.font()
        hint = delegate.sizeHint(option, self._message_list.model().index(
            self._message_list.row(item), 0
        ))
        item.setSizeHint(QSize(width, hint.height()))

    def _create_item(self, role: str, text: str, message_id: int | None = None) -> QListWidgetItem:
        """Create a QListWidgetItem with consistent formatting.

        The full text (with timestamp and speaker prefix) is stored in
        Qt.UserRole for export purposes.  The visible display text contains
        only the rendered markdown content — no timestamp or speaker prefix.
        When *message_id* is provided it is stored in ``UserRole + 1`` so the
        context-menu Delete action can remove the exact message from the DB.
        """
        item = QListWidgetItem()
        timestamp = datetime.now(UTC).strftime("%H:%M")
        prefix = "You" if role == MessageRole.USER else "Assistant"
        item.setData(
            Qt.ItemDataRole.UserRole,
            f"[{timestamp}] {prefix}: {text}",
        )
        if message_id is not None:
            item.setData(Qt.ItemDataRole.UserRole + 1, message_id)
        rendered = _render_markdown(text)
        item.setText(rendered)
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignLeft if role == MessageRole.USER else Qt.AlignmentFlag.AlignRight
        )
        self._update_item_size_hint(item)
        return item

    def add_message(self, role: str, text: str, message_id: int | None = None) -> None:
        item = self._create_item(role, text, message_id)
        self._message_list.addItem(item)
        while self._message_list.count() > self.MAX_MESSAGES:
            self._message_list.takeItem(0)
        self._message_list.scrollToBottom()

    def start_streaming(self) -> None:
        """Begin a streaming assistant response."""
        self._is_streaming = True
        self._last_response_streamed = False
        self._streaming_text = ""
        item = QListWidgetItem()
        timestamp = datetime.now(UTC).strftime("%H:%M")
        self._streaming_timestamp = timestamp
        item.setData(
            Qt.ItemDataRole.UserRole,
            f"[{timestamp}] Assistant: ",
        )
        item.setText("")
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight)
        self._message_list.addItem(item)
        self._streaming_item = item
        self._send_btn.setEnabled(False)
        self._input.setEnabled(False)
        self._stop_btn.setVisible(True)
        self._message_list.scrollToBottom()

    def append_streaming_token(self, token: str) -> None:
        """Append a token to the current streaming response."""
        if not self._is_streaming or self._streaming_item is None:
            return
        self._last_response_streamed = True
        self._streaming_text += token
        rendered = _render_markdown(self._streaming_text)
        self._streaming_item.setText(rendered)
        self._streaming_item.setData(
            Qt.ItemDataRole.UserRole,
            f"[{self._streaming_timestamp}] Assistant: {self._streaming_text}",
        )
        self._update_item_size_hint(self._streaming_item)
        self._message_list.scrollToBottom()
        QApplication.processEvents()

    def finish_streaming(self) -> None:
        """Complete the streaming response.

        When no tokens were ever streamed (e.g. the native tool-calling path
        which builds the full response up-front and publishes
        ``AI_RESPONSE_RECEIVED``), the empty placeholder bubble created by
        :meth:`start_streaming` is discarded so the final response can be
        surfaced as a single message without leaving a blank item behind.
        """
        self._is_streaming = False
        if self._streaming_item is not None:
            if not self._last_response_streamed:
                # Non-streaming generation: no content was appended, so drop the
                # placeholder. The final response is added separately via
                # AI_RESPONSE_RECEIVED, keeping exactly one assistant message.
                self._message_list.takeItem(
                    self._message_list.row(self._streaming_item)
                )
            else:
                # Update UserRole with the complete streamed response so export
                # captures the full text, not the empty "[timestamp] Assistant: "
                # that was set in start_streaming().
                self._streaming_item.setData(
                    Qt.ItemDataRole.UserRole,
                    f"[{self._streaming_timestamp}] Assistant: {self._streaming_text}",
                )
                self._update_item_size_hint(self._streaming_item)
        self._send_btn.setEnabled(bool(self._input.toPlainText().strip()))
        self._input.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._streaming_item = None
        self._streaming_text = ""
        self._streaming_timestamp = ""

    def abort_streaming(self) -> None:
        """Abort the current streaming response."""
        if self._streaming_item is not None:
            self._message_list.takeItem(self._message_list.row(self._streaming_item))
        self._is_streaming = False
        self._last_response_streamed = False
        self._send_btn.setEnabled(bool(self._input.toPlainText().strip()))
        self._input.setEnabled(True)
        self._stop_btn.setVisible(False)
        self._streaming_item = None
        self._streaming_text = ""
        self._streaming_timestamp = ""

    def is_streaming(self) -> bool:
        return self._is_streaming

    def last_response_streamed(self) -> bool:
        """Whether the last response was delivered via streaming events."""
        return self._last_response_streamed

    def _on_stop_generation(self) -> None:
        self.abort_streaming()

    def set_input_placeholder(self, text: str) -> None:
        self._input.setPlaceholderText(text)

    def clear(self) -> None:
        """Clear all messages from the chat widget.

        Aborts any active streaming response first so that the streaming
        item is properly removed and streaming state is reset, preventing
        dangling-reference access when ``clear`` is called from
        ``_on_new_chat_requested`` or ``_on_conversation_selected`` during
        an active token stream.
        """
        self.abort_streaming()
        self._message_list.clear()

    def export_conversation(self) -> str:
        lines = []
        for idx in range(self._message_list.count()):
            item = self._message_list.item(idx)
            export_text = item.data(Qt.ItemDataRole.UserRole)
            lines.append(export_text if export_text is not None else item.text())
        return "\n".join(lines)

    def import_conversation(self, text: str) -> None:
        self.abort_streaming()
        self._message_list.clear()
        for line in text.splitlines():
            if not line.strip():
                continue
            item = QListWidgetItem(line)
            self._message_list.addItem(item)
        self._message_list.scrollToBottom()

    def _on_message_context_menu(self, pos: Any) -> None:
        item = self._message_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu()
        copy_action = menu.addAction("Copy")
        edit_action = menu.addAction("Edit")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self._message_list.mapToGlobal(pos))
        if action == copy_action:
            export_text = item.data(Qt.ItemDataRole.UserRole)
            if export_text is None:
                export_text = item.text()
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(export_text)
            self.message_copied.emit(export_text)
        elif action == edit_action:
            idx = self._message_list.row(item)
            export_text = item.data(Qt.ItemDataRole.UserRole)
            if export_text is None:
                export_text = item.text()
            self.message_edit_requested.emit(idx, export_text)
        elif action == delete_action:
            msg_id = item.data(Qt.ItemDataRole.UserRole + 1)
            self._message_list.takeItem(self._message_list.row(item))
            if msg_id is not None:
                self.message_deleted.emit(msg_id)

    def export_conversation_json(self) -> str:
        import json
        messages = []
        for idx in range(self._message_list.count()):
            item = self._message_list.item(idx)
            export_text = item.data(Qt.ItemDataRole.UserRole)
            messages.append({"index": idx, "text": export_text if export_text is not None else item.text()})
        return json.dumps(messages, ensure_ascii=False, indent=2)

    def export_conversation_markdown(self) -> str:
        lines = []
        for idx in range(self._message_list.count()):
            item = self._message_list.item(idx)
            export_text = item.data(Qt.ItemDataRole.UserRole)
            text = export_text if export_text is not None else item.text()
            lines.append(f"## Message {idx + 1}\n\n{text}\n")
        return "\n".join(lines)

    def export_selected_messages(self) -> str:
        items = self._message_list.selectedItems()
        if not items:
            return ""
        lines = []
        for item in items:
            export_text = item.data(Qt.ItemDataRole.UserRole)
            lines.append(export_text if export_text is not None else item.text())
        return "\n".join(lines)
