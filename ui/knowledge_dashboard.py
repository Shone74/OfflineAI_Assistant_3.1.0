from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from knowledge.models import Document
from ui.design.components import Banner


class KnowledgeDashboard(QWidget):
    """Dashboard for knowledge base overview and management."""

    search_requested = Signal(str)
    delete_requested = Signal(str)
    rebuild_requested = Signal(str)

    def __init__(
        self,
        parent: QWidget | None = None,
        navigator=None,
        assistant: Any = None,
    ) -> None:
        super().__init__(parent)
        self._navigator = navigator
        self._assistant = assistant
        self._documents: dict[str, Document] = {}
        self._stats: dict[str, Any] = {}
        self._setup_ui()
        self.refresh_embedding_status()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)

        self._embedding_warning = Banner(
            "Semantic search is limited: using stub embeddings (no real semantic "
            "model). Results may not be meaningful. Install a real embedding "
            "model for better search.",
            variant="warning",
        )
        self._embedding_warning.setVisible(False)
        root.addWidget(self._embedding_warning)

        layout = QHBoxLayout()

        top_left = QVBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search knowledge...")
        self._search_input.returnPressed.connect(self._on_search_requested)
        top_left.addWidget(self._search_input)

        self._btn_search = QPushButton("Search")
        self._btn_search.clicked.connect(self._on_search_requested)
        top_left.addWidget(self._btn_search)

        self._doc_list = QListWidget()
        self._doc_list.itemClicked.connect(self._on_document_selected)
        top_left.addWidget(QLabel("Documents"))
        top_left.addWidget(self._doc_list)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_home = QPushButton("Home")
        self._btn_index = QPushButton("Index Directory")
        self._btn_index_file = QPushButton("Index File")
        self._btn_rebuild = QPushButton("Rebuild Index")
        self._btn_delete = QPushButton("Delete")
        self._btn_export = QPushButton("Export")
        btn_layout.addWidget(self._btn_home)
        btn_layout.addWidget(self._btn_index)
        btn_layout.addWidget(self._btn_index_file)
        btn_layout.addWidget(self._btn_rebuild)
        btn_layout.addWidget(self._btn_delete)
        btn_layout.addWidget(self._btn_export)
        top_left.addLayout(btn_layout)

        self._btn_home.clicked.connect(self._on_home)
        self._btn_index.clicked.connect(self._on_index_directory)
        self._btn_index_file.clicked.connect(self._on_index_file)
        self._btn_rebuild.clicked.connect(self._on_rebuild)
        self._btn_delete.clicked.connect(self._on_delete_selected)
        self._btn_export.clicked.connect(self._on_export)

        layout.addLayout(top_left, stretch=1)

        right = QVBoxLayout()
        self._preview = QTextEdit()
        self._preview.setReadOnly(True)
        right.addWidget(QLabel("Results"))
        right.addWidget(self._preview)

        self._stats_box = QGroupBox("Statistics")
        stats_layout = QVBoxLayout(self._stats_box)
        self._stats_labels: dict[str, QLabel] = {}
        for key in ("total_documents", "total_chunks", "last_indexed"):
            label = QLabel(f"{key}: N/A")
            self._stats_labels[key] = label
            stats_layout.addWidget(label)
        right.addWidget(self._stats_box)

        layout.addLayout(right, stretch=2)
        root.addLayout(layout)

    def refresh_embedding_status(self) -> None:
        """Show a warning banner when the embedding backend is a stub.

        Stub embeddings have no real semantics, so semantic search quality
        is degraded.  Never raises: the dashboard works without an assistant.
        """
        try:
            memory = getattr(self._assistant, "memory", None)
            if memory is None:
                memory = getattr(self._assistant, "_memory", None)
            info = (
                memory.get_embedding_model_info()
                if memory is not None
                else None
            )
            is_stub = bool(info.get("is_stub")) if info else False
        except Exception:
            is_stub = False
        self._embedding_warning.setVisible(is_stub)

    def _on_search_requested(self) -> None:
        query = self._search_input.text().strip()
        if query:
            self.search_requested.emit(query)

    def set_documents(self, documents: dict[str, Document]) -> None:
        self._documents = documents
        self._doc_list.clear()
        if not documents:
            item = QListWidgetItem("No knowledge documents added.")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._doc_list.addItem(item)
        else:
            for doc in documents.values():
                item = QListWidgetItem(f"{doc.title} ({doc.format})")
                item.setData(1000, doc.id)
                self._doc_list.addItem(item)

    def set_statistics(self, stats: dict[str, Any]) -> None:
        self._stats = stats
        for key, label in self._stats_labels.items():
            value = stats.get(key, "N/A")
            if isinstance(value, dict):
                value = ", ".join(f"{k}: {v}" for k, v in value.items())
            label.setText(f"{key}: {value}")

    def display_search_results(self, context: str, results: list) -> None:
        """Display knowledge search results in the preview area."""
        lines = ["<b>Search Results</b>", ""]
        lines.append(context if context else "(no relevant context found)")
        lines.append("")
        if results:
            lines.append(f"<b>Matched {len(results)} result(s):</b>")
            for i, r in enumerate(results, 1):
                source = r.doc_title if hasattr(r, "doc_title") else "unknown"
                lines.append(f"{i}. Source: {source}")
        self._preview.setText("<br>".join(lines))

    def _on_document_selected(self, item: QListWidgetItem) -> None:
        doc_id = item.data(1000)
        doc = self._documents.get(doc_id)
        if doc is None:
            return
        preview_text = "\n\n".join(chunk.text[:500] for chunk in doc.chunks[:3])
        self._preview.setText(preview_text or "No content available.")

    def _on_index_directory(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(self, "Select Directory to Index")
        if directory:
            self._index_requested.emit(directory)

    def _on_index_file(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select File to Index",
            "",
            "Documents (*.txt *.md *.pdf);;All Files (*)",
        )
        if file_path:
            self._index_file_requested.emit(file_path)

    def _on_export(self) -> None:
        self._export_requested.emit()

    def _on_delete_selected(self) -> None:
        selected_items = self._doc_list.selectedItems()
        if not selected_items:
            return
        item = selected_items[0]
        doc_id = item.data(1000)
        if doc_id:
            self.delete_requested.emit(doc_id)

    def _on_rebuild(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            self, "Select Directory to Rebuild"
        )
        if directory:
            self.rebuild_requested.emit(directory)

    def _on_home(self) -> None:
        if self._navigator is not None:
            self._navigator("Home")
        elif self.parent() is not None and hasattr(self.parent(), "_stack"):
            self.parent()._stack.setCurrentWidget(self.parent()._chat_page)

    index_requested = Signal(str)
    index_file_requested = Signal(str)
    export_requested = Signal()
