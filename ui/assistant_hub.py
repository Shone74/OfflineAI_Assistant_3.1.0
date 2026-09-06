"""Assistant Hub — home/dashboard page with profile snapshot cards.

Shows a quick overview of the assistant identity, active model, and
quick-action buttons.  Registered as the ``home`` route in
:class:`ui.main_window.MainWindow`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.design import WORKSPACE as _PALETTE

_GRAPHITE = _PALETTE.surface
_GRAPHITE_CARD = _PALETTE.surface_card
_GRAPHITE_DARK_CARD = _PALETTE.surface_dark
_GRAPHITE_BORDER = _PALETTE.border
_GRAPHITE_BORDER_SIDEBAR = _PALETTE.border_soft
_EMERALD = _PALETTE.emerald
_EMERGENCY_HOVER = _PALETTE.emerald_hover
_EMERALD_TEXT = _PALETTE.emerald_text
_EMERALD_BG_TINT = _PALETTE.tint(0.08)
_EMERALD_BORDER_TINT = _PALETTE.tint(0.25)
_EMERALD_SUCCESS = _PALETTE.success_bg
_TEXT_PRIMARY = _PALETTE.text_primary
_TEXT_SECONDARY = _PALETTE.text_secondary
_TEXT_MUTED = _PALETTE.text_muted


class AssistantHub(QWidget):
    """Home page widget — assistant profile snapshot + quick actions."""

    def __init__(
        self,
        assistant: Any = None,
        parent: QWidget | None = None,
        navigator: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._navigator = navigator
        self._content_layout: QVBoxLayout | None = None
        self._profile_card: QFrame | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Assistant Hub")
        title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 24px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        status_label = QLabel("100% Local • Offline")
        status_label.setStyleSheet(
            f"color: {_EMERALD_TEXT}; font-size: 15px; font-weight: 600;"
        )
        header.addWidget(status_label)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_GRAPHITE}; }}"
            f"QScrollBar:vertical {{ background: {_GRAPHITE_DARK_CARD}; "
            f"border: none; width: 8px; margin: 0px; }}"
            f"QScrollBar::handle:vertical {{ background: {_GRAPHITE_BORDER}; "
            f"border-radius: 4px; }}"
        )

        content = QFrame()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(14)
        self._content_layout = content_layout

        self._profile_card = self._build_profile_card()
        content_layout.addWidget(self._profile_card)
        content_layout.addWidget(self._build_model_card())

        quick_actions = self._build_quick_actions()
        content_layout.addWidget(quick_actions)

        content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        """Rebuild the profile card to reflect the current assistant profile."""
        if self._content_layout is not None and self._profile_card is not None:
            self._content_layout.removeWidget(self._profile_card)
            self._profile_card.deleteLater()
        self._profile_card = self._build_profile_card()
        if self._content_layout is not None:
            self._content_layout.insertWidget(0, self._profile_card)

    def _build_profile_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 10px; padding: 18px 20px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        icon = QLabel("🤖")
        icon.setStyleSheet("font-size: 24px;")
        title_row.addWidget(icon)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = "Offline AI Assistant"
        desc = "Your local AI assistant."
        traits: list[str] = []
        if self._assistant is not None:
            profile = self._assistant.get_assistant_profile()
            if isinstance(profile, dict):
                identity = profile.get("identity", {})
                if isinstance(identity, dict):
                    profile_name = identity.get("name")
                    if isinstance(profile_name, str) and profile_name:
                        name = profile_name
                    profile_desc = identity.get("description")
                    if isinstance(profile_desc, str) and profile_desc:
                        desc = profile_desc
                personality = profile.get("personality", {})
                if isinstance(personality, dict):
                    raw_traits = personality.get("traits", [])
                    if isinstance(raw_traits, list):
                        traits = [str(t) for t in raw_traits[:4]]

        name_label = QLabel(str(name))
        name_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 17px; font-weight: 600;")
        desc_label = QLabel(str(desc))
        desc_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 13px;")
        desc_label.setWordWrap(True)
        title_col.addWidget(name_label)
        title_col.addWidget(desc_label)
        title_row.addLayout(title_col)
        title_row.addStretch()

        badges = QHBoxLayout()
        badges.setSpacing(6)

        for trait in traits[:4]:
            badge = QLabel(trait)
            badge.setStyleSheet(
                f"background: {_EMERALD_BG_TINT}; color: {_EMERALD_TEXT};"
                f"border: 1px solid {_EMERALD_BORDER_TINT};"
                f"border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 600;"
            )
            badges.addWidget(badge)
        if not traits:
            badge = QLabel("neutral")
            badge.setStyleSheet(
                f"background: {_EMERALD_BG_TINT}; color: {_EMERALD_TEXT};"
                f"border: 1px solid {_EMERALD_BORDER_TINT};"
                f"border-radius: 10px; padding: 3px 9px; font-size: 11px; font-weight: 600;"
            )
            badges.addWidget(badge)
        title_row.addLayout(badges)

        layout.addLayout(title_row)

        info_grid = QHBoxLayout()
        info_grid.setSpacing(12)

        items = [
            ("Language", self._get_profile_field("communication.language", "auto")),
            ("Tone", self._get_profile_field("communication.tone", "neutral")),
            ("Style", self._get_profile_field("communication.response_style", "balanced")),
            ("Expertise", self._get_expertise()),
        ]

        for label_text, value in items:
            col = QVBoxLayout()
            col.setSpacing(2)
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
            val = QLabel(value)
            val.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 13px; font-weight: 600;")
            col.addWidget(lbl)
            col.addWidget(val)
            info_grid.addLayout(col)

        layout.addLayout(info_grid)

        return card

    def _get_profile_field(self, path: str, default: str) -> str:
        if self._assistant is None:
            return default
        profile = self._assistant.get_assistant_profile()
        if not isinstance(profile, dict):
            return default
        keys = path.split(".")
        val: Any = profile
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                return default
            if val is None:
                return default
        return str(val)

    def _get_expertise(self) -> str:
        if self._assistant is None:
            return "general"
        profile = self._assistant.get_assistant_profile()
        areas = profile.get("expertise", {}).get("areas", [])
        return ", ".join(areas) if areas else "general"

    def _build_model_card(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 10px; padding: 18px 20px;"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        model_name = "N/A"
        if self._assistant is not None:
            model_name = str(getattr(self._assistant, "model_name", "N/A"))

        left = QVBoxLayout()
        left.setSpacing(4)
        title = QLabel("Active Model")
        title.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 13px; text-transform: uppercase;")
        name = QLabel(str(model_name))
        name.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
        status = QLabel("Ready")
        status.setStyleSheet(f"color: {_EMERGENCY_HOVER}; font-size: 13px; font-weight: 600;")
        left.addWidget(title)
        left.addWidget(name)
        left.addWidget(status)

        layout.addLayout(left)
        layout.addStretch()

        caps = self._get_model_capabilities()
        if caps:
            cap_text = " · ".join(caps)
            caps_label = QLabel(cap_text)
            caps_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 13px;")
            caps_label.setWordWrap(True)
            layout.addWidget(caps_label)

        return card

    def _get_model_capabilities(self) -> list[str]:
        if self._assistant is None:
            return []
        caps = getattr(self._assistant, "model_capabilities", None)
        if caps is None:
            return []
        result: list[str] = []
        for attr in ("supports_text", "supports_code", "supports_documents"):
            if getattr(caps, attr, False):
                label = attr.replace("supports_", "").capitalize()
                result.append(label)
        return result

    def _build_quick_actions(self) -> QFrame:
        frame = QFrame()
        frame.setStyleSheet("border: none;")
        layout = QHBoxLayout(frame)
        layout.setSpacing(10)

        actions = [
            ("💬 New conversation", "chat"),
            ("🧠 Search memory", "memory"),
            ("📚 Browse knowledge", "knowledge"),
            ("📦 Models", "models"),
        ]

        for label_text, route in actions:
            btn = QPushButton(label_text)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"background: {_GRAPHITE_DARK_CARD}; color: {_TEXT_SECONDARY};"
                f"border: 1px solid {_GRAPHITE_BORDER}; border-radius: 7px;"
                f"padding: 10px 16px; font-size: 13px; text-align: left;"
            )
            btn.setProperty("route", route)
            btn.setFixedHeight(42)
            btn.clicked.connect(self._on_quick_action_clicked)
            layout.addWidget(btn)

        return frame

    def _on_quick_action_clicked(self) -> None:
        sender = self.sender()
        if sender is None:
            return
        route = sender.property("route")
        if route and self._navigator is not None:
            self._navigator(route)
