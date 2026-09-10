"""Chat widget — message list plus a text-input bar with a send button."""

from __future__ import annotations

import base64
import mimetypes
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QResizeEvent, QTextDocument
from PySide6.QtWidgets import (
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


class _ChatInputEdit(QTextEdit):
    """Multiline chat input with chat-style Enter handling.

    * ``Enter`` / ``Return`` — emits :attr:`submit_requested` (the widget
      never inserts a newline for a bare Enter).
    * ``Shift+Enter`` / ``Shift+Return`` — inserts a newline (default
      QTextEdit behaviour).
    * ``Ctrl+Enter`` — also inserts a newline (common alternative users
      expect when Enter is bound to sending).
    * ``Ctrl+A/V/C/X/Z/...`` keep their standard editor shortcuts.
    """

    submit_requested = Signal()

    def keyPressEvent(self, event) -> None:
        from PySide6.QtCore import Qt

        key = event.key()
        modifiers = event.modifiers()
        enter_like = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)

        if enter_like and not (modifiers & (Qt.KeyboardModifier.ShiftModifier | Qt.KeyboardModifier.ControlModifier)):
            # Bare Enter submits — do NOT insert a newline.
            self.submit_requested.emit()
            event.accept()
            return
        if enter_like:
            # Shift/Ctrl+Enter: strip the Shift/Ctrl so QTextEdit inserts
            # a plain newline (default action for Return).
            from PySide6.QtGui import QKeyEvent

            newline_event = QKeyEvent(
                event.type(),
                key,
                Qt.KeyboardModifier.NoModifier,
                event.text() or "\n",
            )
            super().keyPressEvent(newline_event)
            event.accept()
            return
        super().keyPressEvent(event)


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
    automatic_listening_toggled = Signal(bool)
    send_with_images_requested = Signal(str, list)

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

        self._header_title = QLabel()
        self._header_title.setObjectName("chat_assistant_name")
        self._header_status = QLabel("● Local AI")
        self._header_status.setObjectName("status_local")

        # Online indicator: shown while the assistant is generating through
        # the opt-in Online API instead of a local model (agent routing).
        self._online_label = QLabel("🌐 Online")
        self._online_label.setObjectName("status_local")
        self._online_label.setToolTip(
            "This turn is served by an online model via the configured API"
        )
        self._online_label.setVisible(False)

        # Capability buttons per the design. Vision is active only when
        # the current model supports multimodal inference (see
        # set_vision_available). Files opens the attach dialog.
        self._btn_files = QPushButton("📎 Files")
        self._btn_files.setObjectName("capability_button")
        self._btn_files.setToolTip("Attach a text file to the message")
        self._btn_files.clicked.connect(self._on_files_clicked)
        self._btn_vision = QPushButton("🖼 Vision")
        self._btn_vision.setObjectName("capability_button")
        self._btn_vision.setEnabled(False)
        self._btn_vision.setToolTip(
            "Attach an image for analysis (requires a vision-capable model)"
        )
        self._btn_vision.clicked.connect(self._on_vision_clicked)
        self._pending_images: list[str] = []
        self._btn_memory = QPushButton("🧠 Memory")
        self._btn_memory.setObjectName("capability_button")

        self._btn_new_chat = QPushButton("New Chat")
        self._btn_new_chat.setObjectName("secondary_button")
        self._btn_export = QPushButton("Export")
        self._btn_export.setObjectName("secondary_button")
        self._btn_export_selected = QPushButton("Export Selected")
        self._btn_export_selected.setObjectName("secondary_button")
        self._btn_search = QPushButton("Search Memory")
        self._btn_search.setObjectName("secondary_button")
        self._project_label = QLabel()
        self._project_label.setObjectName("status_local")
        self._project_label.setVisible(False)

        layout.addWidget(self._header_title)
        layout.addWidget(self._header_status)
        layout.addWidget(self._online_label)
        layout.addSpacing(12)
        layout.addWidget(self._btn_files)
        layout.addWidget(self._btn_vision)
        layout.addWidget(self._btn_memory)
        layout.addSpacing(12)
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

    def set_assistant_display_name(self, name: str) -> None:
        """Set the assistant name in the chat header (workspace design)."""
        self._header_title.setText(name)

    def set_online_active(self, active: bool) -> None:
        """Show/hide the 🌐 Online indicator for the current turn."""
        self._online_label.setVisible(bool(active))

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
    # Multiline input sizing: at least MIN_INPUT_LINES lines are always
    # visible; the box grows up to MAX_INPUT_LINES and then scrolls.
    _MIN_INPUT_LINES = 4
    _MAX_INPUT_LINES = 8
    _LINE_HEIGHT_PX = 24  # single row height incl. spacing at the app font size

    def _build_input_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        self._input = _ChatInputEdit()
        self._input.setPlaceholderText(
            "Type a message... (Enter to send, Shift+Enter for a new line)"
        )
        self._input.textChanged.connect(self._on_text_changed)
        self._input.setAccessibleName("Chat message input")
        self._input.setTabChangesFocus(True)
        # Enter submits; Shift+Enter inserts a newline (handled inside
        # _ChatInputEdit.keyPressEvent — the reliable interception point).
        self._input.submit_requested.connect(self._submit_input)
        layout.addWidget(self._input, stretch=1)

        self._apply_input_size()
        self._send_btn = QPushButton("➤")
        self._send_btn.setObjectName("send_button")
        self._send_btn.setEnabled(False)
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._send_btn.setAccessibleName("Send message")
        layout.addWidget(self._send_btn)

        self._stop_btn = QPushButton("■")
        self._stop_btn.setObjectName("danger_button")
        self._stop_btn.setToolTip("Stop generation")
        self._stop_btn.setAccessibleName("Stop generation")
        self._stop_btn.setFixedSize(38, 38)
        self._stop_btn.clicked.connect(self.stop_generation)
        self._stop_btn.setVisible(False)
        layout.addWidget(self._stop_btn)

        # Voice controls: a state-driven REC/STOP/PROCESSING toggle plus a PLAY
        # button that replays the most recent captured WAV.
        self._voice_btn = QPushButton("REC")
        self._voice_btn.setObjectName("capability_button")
        self._voice_btn.setToolTip("Voice input")
        self._voice_btn.setAccessibleName("Voice input toggle")
        self._voice_btn.clicked.connect(self._on_voice_clicked)
        self._voice_btn.setMinimumWidth(80)
        self._voice_btn.setFixedHeight(38)
        layout.addWidget(self._voice_btn)

        self._play_btn = QPushButton("PLAY")
        self._play_btn.setObjectName("capability_button")
        self._play_btn.setToolTip("Play latest recording")
        self._play_btn.setAccessibleName("Play latest recording")
        self._play_btn.clicked.connect(self._on_play_clicked)
        self._play_btn.setMinimumWidth(60)
        self._play_btn.setFixedHeight(38)
        self._play_btn.setVisible(False)
        layout.addWidget(self._play_btn)

        # Automatic Listening (continuous conversation) — user toggle.
        # Communicates the state clearly: "Automatic Listening" / "Automatic Listening: ON".
        self._auto_listen_btn = QPushButton("Automatic Listening")
        self._auto_listen_btn.setObjectName("capability_button")
        self._auto_listen_btn.setToolTip(
            "Continuous conversation: listen → transcribe → respond → "
            "speak → listen again (without pressing the microphone)"
        )
        self._auto_listen_btn.setAccessibleName("Automatic Listening toggle")
        self._auto_listen_btn.setCheckable(True)
        self._auto_listen_btn.clicked.connect(self._on_auto_listen_clicked)
        self._auto_listen_btn.setMinimumWidth(140)
        self._auto_listen_btn.setFixedHeight(38)
        layout.addWidget(self._auto_listen_btn)

        return layout

    def _on_auto_listen_clicked(self, checked: bool) -> None:
        self.automatic_listening_toggled.emit(bool(checked))

    def set_automatic_listening_ui(self, enabled: bool) -> None:
        """Updates the Automatic Listening button to reflect the actual state."""
        self._auto_listen_btn.blockSignals(True)
        self._auto_listen_btn.setChecked(enabled)
        if enabled:
            self._auto_listen_btn.setText("Automatic Listening: ON")
        else:
            self._auto_listen_btn.setText("Automatic Listening")
        self._auto_listen_btn.blockSignals(False)

    # ------------------------------------------------------------------ #
    def _on_text_changed(self) -> None:
        self._send_btn.setEnabled(bool(self._input.toPlainText().strip()))
        self._apply_input_size()

    # ------------------------------------------------------------------ #
    # Dynamic input height (min 4 / max 8 visible lines, then scroll)
    # ------------------------------------------------------------------ #
    def _apply_input_size(self) -> None:
        """Resize the input to fit its content between the min and max.

        The widget always shows at least ``_MIN_INPUT_LINES`` lines.  As the
        text wraps beyond that, the height grows line by line up to
        ``_MAX_INPUT_LINES``; further content is reached with the internal
        scrollbar.
        """
        doc = self._input.document()
        # Account for the document margin around the text block.
        margins = (
            doc.documentMargin() * 2
            + self._input.contentsMargins().top()
            + self._input.contentsMargins().bottom()
        )
        # Height the text actually needs at the current width.
        needed = int(doc.size().height() + margins)
        min_h = self._MIN_INPUT_LINES * self._LINE_HEIGHT_PX
        max_h = self._MAX_INPUT_LINES * self._LINE_HEIGHT_PX
        self._input.setMinimumHeight(min_h)
        self._input.setMaximumHeight(max(min_h, min(needed, max_h)))
        # Keep the caret visible when the content exceeds the box.
        sb = self._input.verticalScrollBar()
        if sb.isVisible():
            sb.setValue(sb.maximum())

    def _submit_input(self) -> None:
        """Enter/Return handler — send the message (Shift+Enter inserts a newline)."""
        text = self._input.toPlainText().strip()
        if text:
            self._on_send_clicked()

    def _on_files_clicked(self) -> None:
        """Attach a text file — its contents are appended to the input."""
        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Attach Text File",
            "",
            "Text Files (*.txt);;Markdown (*.md);;Python (*.py);;All Files (*)",
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except OSError as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "Attach File", f"Could not read file:\n{exc}")
            return
        header = f"[File: {Path(path).name}]\n"
        current = self._input.toPlainText()
        self._input.setPlainText(f"{current}\n{header}{content}".strip())
        self._on_text_changed()

    def _on_vision_clicked(self) -> None:
        """Attach images for multimodal analysis (vision models only)."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox

        if not self._btn_vision.isEnabled():
            return
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Attach Images",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp)",
        )
        if not paths:
            return
        added = 0
        for p in paths:
            try:
                data = Path(p).read_bytes()
            except OSError:
                continue
            if len(data) > 12 * 1024 * 1024:
                QMessageBox.warning(
                    self, "Vision", f"Image too large (>12 MB), skipped:\n{p}"
                )
                continue
            mime_type = mimetypes.guess_type(p)[0] or "image/png"
            encoded = base64.b64encode(data).decode("ascii")
            self._pending_images.append(f"data:{mime_type};base64,{encoded}")
            added += 1
        if added:
            self._btn_vision.setText(f"🖼 Vision ({len(self._pending_images)})")

    def set_vision_available(self, available: bool) -> None:
        """Enable/disable the Vision button based on the active model."""
        self._btn_vision.setEnabled(bool(available))

    def _clear_pending_images(self) -> None:
        self._pending_images.clear()
        self._btn_vision.setText("🖼 Vision")

    def _on_send_clicked(self) -> None:
        text = self._input.toPlainText().strip()
        if text or self._pending_images:
            if self._pending_images:
                self.send_with_images_requested.emit(text, list(self._pending_images))
            else:
                self.send_requested.emit(text)
            self._input.clear()
            self._clear_pending_images()

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
        # No event-loop pumping here: tokens arrive via queued
        # signals on the GUI thread — the event loop is already running;
        # pumping it per token caused redundant dispatch/re-layout.

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
