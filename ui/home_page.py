"""Home / status hub page — according to the workspace design.

Uses design components (ui/design) — no hardcoded colors.
Layout per the design:
- "Your Assistant" title + status
- Assistant hero card (✦ name + status + Start Conversation primary button)
- "Assistant Snapshot" 2×2 grid (Identity, AI Engine, Capabilities, Privacy)
- "Quick Actions" 2×2 grid (Chat, Memory, Knowledge, Capabilities)
"""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ui.design.components import Card, make_primary_button, make_section_title
from ui.theme_manager import ThemeManager


class StatusCard(Card):
    """Status card (#card) with title/value/detail labels."""

    def __init__(self, title: str, value: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title_label = QLabel(title.upper())
        self._title_label.setObjectName("card_title")
        self._value_label = QLabel(value)
        self._value_label.setObjectName("card_value")
        self._value_label.setWordWrap(True)

        self.card_layout.addWidget(self._title_label)
        self.card_layout.addWidget(self._value_label)

    def set_value(self, text: str) -> None:
        self._value_label.setText(text)

    @property
    def value_label(self) -> QLabel:
        return self._value_label


class AssistantHeroCard(Card):
    """Assistant hero card: ✦ name, description, status + Start Conversation."""

    def __init__(
        self,
        assistant_name: str,
        on_start_conversation=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("assistant_card")
        self.card_layout.setContentsMargins(24, 20, 24, 20)
        self.card_layout.setSpacing(8)

        icon = QLabel("✦")
        icon.setObjectName("assistant_name")
        icon.setStyleSheet("font-size: 30pt; background: transparent;")
        self.card_layout.addWidget(icon)

        self._name_label = QLabel(assistant_name)
        self._name_label.setObjectName("assistant_name")
        self.card_layout.addWidget(self._name_label)

        self._desc_label = QLabel("Your Personal AI Assistant")
        self._desc_label.setObjectName("sidebar_subtitle")
        self.card_layout.addWidget(self._desc_label)

        self._status_label = QLabel("● Ready   🔒 Local AI")
        self._status_label.setObjectName("status_local")
        self._status_label.setWordWrap(True)
        self.card_layout.addWidget(self._status_label)

        self.card_layout.addSpacing(6)

        if on_start_conversation is not None:
            btn = make_primary_button("Start Conversation")
            btn.clicked.connect(on_start_conversation)
            self.card_layout.addWidget(btn)
            self.card_layout.setAlignment(btn, Qt.AlignmentFlag.AlignLeft)

        self.card_layout.addStretch()

    def set_status(self, ready: bool) -> None:
        self._status_label.setText("● Ready   🔒 Local AI" if ready else "○ No model   🔒 Local AI")


class HomePage(QWidget):
    """Application status hub following the workspace design."""

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

        title = QLabel("Your Assistant")
        title.setObjectName("page_title")
        subtitle = QLabel(
            "This is your personal AI workspace. "
            "Everything here adapts to the way you use your assistant."
        )
        subtitle.setObjectName("page_subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Hero card
        self._hero = AssistantHeroCard(
            assistant_name=self._assistant_name,
            on_start_conversation=lambda: self._open("Chat"),
        )
        layout.addWidget(self._hero)

        # Assistant Snapshot grid
        layout.addWidget(make_section_title("Assistant Snapshot"))
        snapshot = QGridLayout()
        snapshot.setSpacing(12)

        self._ai_card = StatusCard("AI Engine", "No model loaded")
        self._system_card = StatusCard("System", "Checking…")
        self._memory_card = StatusCard("Memory", "No conversations")
        self._privacy_card = StatusCard("Privacy", "Local processing · Local data")

        snapshot.addWidget(self._ai_card, 0, 0)
        snapshot.addWidget(self._system_card, 0, 1)
        snapshot.addWidget(self._memory_card, 1, 0)
        snapshot.addWidget(self._privacy_card, 1, 1)
        layout.addLayout(snapshot)

        # Quick Actions grid
        layout.addWidget(make_section_title("Quick Actions"))
        quick_grid = QGridLayout()
        quick_grid.setSpacing(12)

        actions = [
            ("💬 Chat", "Start a new conversation.", "Chat"),
            ("🧠 Memory", "See what your assistant remembers.", "Memory"),
            ("📚 Knowledge", "Manage your local knowledge sources.", "Knowledge"),
            ("🧩 Capabilities", "Choose what your assistant can do.", "Capabilities"),
        ]
        for idx, (title_text, desc_text, route) in enumerate(actions):
            card = Card()
            t = QLabel(title_text)
            t.setObjectName("card_value")
            d = QLabel(desc_text)
            d.setObjectName("card_detail")
            d.setWordWrap(True)
            card.add(t)
            card.add(d)

            btn = make_primary_button("Open")
            btn.clicked.connect(lambda _, r=route: self._open(r))
            card.add(btn)
            card.add_stretch()

            quick_grid.addWidget(card, idx // 2, idx % 2)

        layout.addLayout(quick_grid)
        layout.addStretch()

    def _open(self, route: str) -> None:
        if self._navigator is not None:
            self._navigator(route)

    def _refresh_status(self) -> None:
        try:
            cpu = psutil.cpu_percent(interval=0.1)
            ram = psutil.virtual_memory().percent
            self._system_card.set_value(f"CPU {cpu:.0f}% · RAM {ram:.0f}%")
        except Exception:
            pass

        model_ready = False
        try:
            if self._assistant is not None:
                model_name = getattr(self._assistant, "model_name", None) or "No model loaded"
                if model_name in ("stub", "No model loaded", "N/A"):
                    model_name = "No model loaded"
                    status_hint = getattr(self._assistant, "engine_status", "")
                    if status_hint in ("runtime_unavailable", "not_configured"):
                        model_name = "No AI runtime (install llama-cpp-python)"
                    elif status_hint == "stub_mode":
                        model_name = "No model loaded (stub mode)"
                self._ai_card.set_value(model_name)
                model_ready = (
                    model_name not in (
                        "No model loaded", "No model loaded (stub mode)",
                        "No AI runtime (install llama-cpp-python)",
                    )
                    and getattr(self._assistant, "is_model_ready", False)
                )
        except Exception:
            pass

        try:
            if self._assistant is not None:
                memory = getattr(self._assistant, "_memory", None)
                if memory is not None:
                    histories = getattr(getattr(memory, "_short_term", None), "get_history", list)()
                    self._memory_card.set_value(f"{len(histories)} recent messages")
        except Exception:
            pass

        try:
            self._hero.set_status(model_ready)
        except Exception:
            pass
