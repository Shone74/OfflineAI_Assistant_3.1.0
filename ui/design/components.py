"""Reusable design components per the official design.

All components use the objectName conventions from the QSS builder
(ui/design/qss.py) and contain no inline hex values.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    """Basic card (#card) — surface + border + radius from the theme."""

    def __init__(self, parent: QWidget | None = None, hoverable: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        if not hoverable:
            # The QFrame#card:hover rule still applies; for non-hover
            # cards we would need a card_title variant without hover, which
            # is impossible via objectName alone, so hover is acceptable.
            pass
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 14, 14, 14)
        self._layout.setSpacing(6)

    @property
    def card_layout(self) -> QVBoxLayout:
        return self._layout

    def add(self, widget: QWidget, stretch: int = 0) -> None:
        self._layout.addWidget(widget, stretch)

    def add_stretch(self) -> None:
        self._layout.addStretch()


class Banner(QFrame):
    """Status banner (success / warning / error) per the wizard design."""

    def __init__(self, text: str = "", variant: str = "success",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        object_name = {
            "success": "banner",
            "info": "banner",
            "warning": "banner_warning",
            "error": "banner_error",
        }.get(variant, "banner")
        self.setObjectName(object_name)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self._label = QLabel(text)
        self._label.setWordWrap(True)
        layout.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)


class Badge(QLabel):
    """Small emerald badge (e.g. 'RECOMMENDED', '100% OFFLINE')."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class StatusChip(QLabel):
    """Status chip — emerald (ready) or warning (limited) text."""

    def __init__(self, text: str = "", status: str = "ready",
                 parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status = status
        self.apply_status(status)

    def apply_status(self, status: str) -> None:
        self._status = status
        # Colors are not hardcoded — we read them from tokens via the palette object
        from ui.design.tokens import get_palette

        p = get_palette("installer")
        color = p.warning if status == "warning" else p.error if status == "error" else p.emerald_text
        self.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;"
            " letter-spacing: 0.4px; background: transparent;"
        )

    @property
    def status(self) -> str:
        return self._status


class StorageBar(QProgressBar):
    """Thin progress bar for showing disk usage (#storage_bar)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("storage_bar")
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(4)


class InstallProgressBar(QProgressBar):
    """Installation progress bar (#install_progress)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("install_progress")
        self.setRange(0, 100)
        self.setTextVisible(True)
        self.setFixedHeight(7)


class CapabilityChip(QLabel):
    """Chip for the capability list: '✓ TEXT' (active) or '✕ IMAGES' (inactive)."""

    def __init__(self, label: str, active: bool = True,
                 parent: QWidget | None = None) -> None:
        mark = "✓" if active else "✕"
        super().__init__(f"{mark} {label.upper()}", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._active = active
        from ui.design.tokens import get_palette

        p = get_palette("installer")
        if active:
            self.setStyleSheet(
                f"background: {p.tint(0.14)}; color: {p.emerald_text};"
                " font-size: 11px; font-weight: 600; padding: 4px 8px;"
                " border-radius: 5px; letter-spacing: 0.3px;"
            )
        else:
            self.setStyleSheet(
                f"background: rgba(89, 98, 95, 0.12); color: {p.text_muted};"
                " font-size: 11px; font-weight: 600; padding: 4px 8px;"
                " border-radius: 5px; letter-spacing: 0.3px;"
            )

    @property
    def active(self) -> bool:
        return self._active


class StepIndicator(QWidget):
    """Wizard sidebar step list with default/completed/current states."""

    def __init__(self, steps: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps = list(steps)
        self._current = 0
        self._labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for step in self._steps:
            label = QLabel(step)
            label.setObjectName("wizard_step_default")
            label.setWordWrap(False)
            self._labels.append(label)
            layout.addWidget(label)
        layout.addStretch()
        self._refresh()

    def set_current(self, index: int) -> None:
        """Set the current step (0-based); previous steps become completed."""
        if 0 <= index < len(self._steps):
            self._current = index
            self._refresh()

    def _refresh(self) -> None:
        for i, label in enumerate(self._labels):
            if i < self._current:
                label.setObjectName("wizard_step_completed")
                label.setText(f"✓  {self._steps[i]}")
            elif i == self._current:
                label.setObjectName("wizard_step_current")
                label.setText(f"●  {self._steps[i]}")
            else:
                label.setObjectName("wizard_step_default")
                label.setText(f"○  {self._steps[i]}")
            # Force re-application of the QSS for the new objectName
            label.style().unpolish(label)
            label.style().polish(label)

    @property
    def current(self) -> int:
        return self._current


def make_section_title(text: str, parent: QWidget | None = None) -> QLabel:
    """Section title (#section_title) within a page."""
    label = QLabel(text, parent)
    label.setObjectName("section_title")
    return label


def make_primary_button(text: str, parent: QWidget | None = None) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setObjectName("primary_button")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def make_secondary_button(text: str, parent: QWidget | None = None) -> QPushButton:
    btn = QPushButton(text, parent)
    btn.setObjectName("secondary_button")
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn
