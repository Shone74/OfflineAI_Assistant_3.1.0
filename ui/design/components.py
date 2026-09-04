"""Reusable design komponente prema zvaničnom dizajnu.

Sve komponente koriste objectName konvencije iz QSS builder-a
(ui/design/qss.py) i ne sadrže inline hex vrednosti.
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
    """Osnovna kartica (#card) — površina + border + radius iz teme."""

    def __init__(self, parent: QWidget | None = None, hoverable: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        if not hoverable:
            # QFrame#card:hover pravilo se i dalje primenjuje; za ne-hover
            # kartice koristimo card_title varijantu bez hovera je nemoguca
            # cistim objectName-om, pa je hover prihvatljiv.
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
    """Status banner (success / warning / error) po wizard dizajnu."""

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
    """Mali emerald badge (npr. 'RECOMMENDED', '100% OFFLINE')."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class StatusChip(QLabel):
    """Status chip — emerald (ready) ili warning (limited) tekst."""

    def __init__(self, text: str = "", status: str = "ready",
                 parent: QWidget | None = None) -> None:
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status = status
        self.apply_status(status)

    def apply_status(self, status: str) -> None:
        self._status = status
        # Boje se ne hardcodiraju — citamo iz tokena preko palette objekta
        from ui.design.tokens import get_palette

        p = get_palette("installer")
        color = p.warning if status == "warning" else p.error if status == "error" else p.emerald_text
        self.setStyleSheet(
            f"color: {color}; font-size: 9px; font-weight: 600;"
            " letter-spacing: 0.4px; background: transparent;"
        )

    @property
    def status(self) -> str:
        return self._status


class StorageBar(QProgressBar):
    """Tanki progress bar za prikaz popunjenosti diska (#storage_bar)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("storage_bar")
        self.setRange(0, 100)
        self.setTextVisible(False)
        self.setFixedHeight(4)


class InstallProgressBar(QProgressBar):
    """Progress bar instalacije (#install_progress)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("install_progress")
        self.setRange(0, 100)
        self.setTextVisible(True)
        self.setFixedHeight(7)


class CapabilityChip(QLabel):
    """Chip za capability listu: '✓ TEXT' (aktivan) ili '✕ IMAGES' (neaktivan)."""

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
                " font-size: 9px; font-weight: 600; padding: 4px 8px;"
                " border-radius: 5px; letter-spacing: 0.3px;"
            )
        else:
            self.setStyleSheet(
                f"background: rgba(89, 98, 95, 0.12); color: {p.text_muted};"
                " font-size: 9px; font-weight: 600; padding: 4px 8px;"
                " border-radius: 5px; letter-spacing: 0.3px;"
            )

    @property
    def active(self) -> bool:
        return self._active


class StepIndicator(QWidget):
    """Wizard sidebar step lista sa default/completed/current stanjima."""

    def __init__(self, steps: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._steps = list(steps)
        self._current = 0
        self._labels: list[QLabel] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        for step in self._steps:
            label = QLabel(f"✓  {step}" if False else step)
            label.setObjectName("wizard_step_default")
            label.setWordWrap(False)
            self._labels.append(label)
            layout.addWidget(label)
        layout.addStretch()
        self._refresh()

    def set_current(self, index: int) -> None:
        """Postavi trenutni korak (0-based); prethodni postaju completed."""
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
            # Forsira re-primenu QSS-a za novi objectName
            label.style().unpolish(label)
            label.style().polish(label)

    @property
    def current(self) -> int:
        return self._current


def make_section_title(text: str, parent: QWidget | None = None) -> QLabel:
    """Sekcija naslov (#section_title) unutar stranice."""
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
