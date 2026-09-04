"""Home / status hub page for the final application."""

from __future__ import annotations

import psutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui.theme_manager import ThemeManager


class StatusCard(QFrame):
    """Reusable status card."""

    def __init__(self, title: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)

        title_label = QLabel(title)
        title_label.setStyleSheet("color: #8C9692; font-size: 9pt; font-weight: 600; text-transform: uppercase;")
        value_label = QLabel(value)
        value_label.setStyleSheet("color: #EDF3F0; font-size: 11pt; font-weight: 600;")
        value_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(value_label)
        self.setStyleSheet(
            "QFrame { background-color: #1C2221; border: 1px solid #29302E; border-radius: 10px; }"
        )


class HomePage(QWidget):
    """Application status hub."""

    def __init__(
        self,
        theme: ThemeManager,
        assistant_name: str = "Assistant",
        navigator=None,
        assistant=None,
    ) -> None:
        super().__init__()
        self._theme = theme
        self._assistant_name = assistant_name
        self._navigator = navigator
        self._assistant = assistant

        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title = QLabel("Your Assistant")
        title.setStyleSheet("font-size: 22pt; font-weight: 600;")
        subtitle = QLabel(
            "This is your personal AI workspace. Everything here adapts to the way you use your assistant."
        )
        subtitle.setStyleSheet("color: #8C9692; font-size: 10pt;")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        layout.addLayout(header)

        status_row = QHBoxLayout()
        status = QLabel("● Ready     🔒 Local AI")
        status.setStyleSheet("color: #27C48A; font-size: 10pt; font-weight: 600;")
        status_row.addWidget(status)
        status_row.addStretch()
        layout.addLayout(status_row)

        cards = QGridLayout()
        cards.setSpacing(12)

        self._ai_card = StatusCard("AI Engine", "No model loaded")
        self._system_card = StatusCard("System", "Checking…")
        self._memory_card = StatusCard("Memory", "No conversations")
        self._privacy_card = StatusCard("Privacy", "Local processing · Local data")

        cards.addWidget(self._ai_card, 0, 0)
        cards.addWidget(self._system_card, 0, 1)
        cards.addWidget(self._memory_card, 1, 0)
        cards.addWidget(self._privacy_card, 1, 1)
        layout.addLayout(cards)

        quick = QVBoxLayout()
        quick_title = QLabel("Quick Actions")
        quick_title.setStyleSheet("font-size: 12pt; font-weight: 600;")
        quick.addWidget(quick_title)

        quick_grid = QGridLayout()
        quick_grid.setSpacing(12)

        actions = [
            ("💬 Chat", "Start a new conversation.", "Chat"),
            ("🧠 Memory", "See what your assistant remembers.", "Memory"),
            ("📚 Knowledge", "Manage your local knowledge sources.", "Knowledge"),
            ("🧩 Capabilities", "Choose what your assistant can do.", "Capabilities"),
        ]
        for idx, (title_text, desc_text, route) in enumerate(actions):
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            card.setStyleSheet(
                "QFrame { background-color: #1C2221; border: 1px solid #29302E; border-radius: 10px; }"
            )
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(16, 14, 16, 14)
            t = QLabel(title_text)
            t.setStyleSheet("font-size: 11pt; font-weight: 600;")
            d = QLabel(desc_text)
            d.setStyleSheet("color: #8C9692;")
            d.setWordWrap(True)
            c_layout.addWidget(t)
            c_layout.addWidget(d)

            btn = QPushButton("Open")
            btn.setObjectName("primary_button")
            btn.clicked.connect(lambda _, r=route: self._open(r))
            c_layout.addWidget(btn)

            row = idx // 2
            col = idx % 2
            quick_grid.addWidget(card, row, col)

        quick.addLayout(quick_grid)
        layout.addLayout(quick)
        layout.addStretch()

    def _open(self, route: str) -> None:
        if self._navigator is not None:
            self._navigator(route)

    def _refresh_status(self) -> None:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            self._system_card.findChildren(QLabel)[1].setText(f"CPU {cpu:.0f}% · RAM {ram:.0f}%")
        except Exception:
            pass

        try:
            if self._assistant is not None:
                model_name = getattr(self._assistant, "model_name", None) or "No model loaded"
                self._ai_card.findChildren(QLabel)[1].setText(model_name)
        except Exception:
            pass

        try:
            if self._assistant is not None:
                memory = getattr(self._assistant, "_memory", None)
                if memory is not None:
                    histories = getattr(getattr(memory, "_short_term", None), "get_history", lambda: [])()
                    self._memory_card.findChildren(QLabel)[1].setText(f"{len(histories)} recent messages")
        except Exception:
            pass
