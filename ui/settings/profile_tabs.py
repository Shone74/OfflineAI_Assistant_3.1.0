"""Profile subtabs for the Settings dialog — assistant personality configuration.

Each tab manages one section of the assistant profile (identity, communication,
personality, expertise, behavior, boundaries). All tabs share a common
load_profile/get_* interface for integration with SettingsDialog.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ProfileTab(QWidget):
    """Tab for editing identity section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._name_edit = QLineEdit()
        layout.addRow(QLabel("<b>Name</b> (optional)"), self._name_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("Short assistant description...")
        self._desc_edit.setFixedHeight(80)
        layout.addRow(QLabel("<b>Description</b>"), self._desc_edit)

    def load_profile(self, profile: dict[str, Any]) -> None:
        identity = profile.get("identity", {})
        self._name_edit.setText(identity.get("name") or "")
        self._desc_edit.setPlainText(identity.get("description") or "")

    def get_identity(self) -> dict[str, Any]:
        name = self._name_edit.text().strip() or None
        return {
            "name": name,
            "description": self._desc_edit.toPlainText().strip(),
        }


class CommunicationTab(QWidget):
    """Tab for editing communication section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._language_combo = QComboBox()
        self._language_combo.addItems(["auto", "English"])
        layout.addRow(QLabel("<b>Language</b>"), self._language_combo)

        self._tone_combo = QComboBox()
        self._tone_combo.addItems(["neutral", "friendly", "professional", "casual", "humorous", "formal"])
        layout.addRow(QLabel("<b>Tone</b>"), self._tone_combo)

        self._formality_combo = QComboBox()
        self._formality_combo.addItems(["neutral", "informal", "formal"])
        layout.addRow(QLabel("<b>Formality</b>"), self._formality_combo)

        self._response_style_combo = QComboBox()
        self._response_style_combo.addItems(["balanced", "concise", "verbose", "technical", "casual"])
        layout.addRow(QLabel("<b>Response Style</b>"), self._response_style_combo)

    def load_profile(self, profile: dict[str, Any]) -> None:
        comm = profile.get("communication", {})
        self._language_combo.setCurrentText(comm.get("language", "auto"))
        self._tone_combo.setCurrentText(comm.get("tone", "neutral"))
        self._formality_combo.setCurrentText(comm.get("formality", "neutral"))
        self._response_style_combo.setCurrentText(comm.get("response_style", "balanced"))

    def get_communication(self) -> dict[str, Any]:
        return {
            "language": self._language_combo.currentText(),
            "tone": self._tone_combo.currentText(),
            "formality": self._formality_combo.currentText(),
            "response_style": self._response_style_combo.currentText(),
        }


class PersonalityTab(QWidget):
    """Tab for editing personality section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._humor_slider = QSlider(Qt.Horizontal)
        self._humor_slider.setRange(0, 100)
        self._humor_label = QLabel("0.5")
        humor_layout = QHBoxLayout()
        humor_layout.addWidget(self._humor_slider)
        humor_layout.addWidget(self._humor_label)
        layout.addRow(QLabel("<b>Humor</b>"), humor_layout)

        self._proactivity_slider = QSlider(Qt.Horizontal)
        self._proactivity_slider.setRange(0, 100)
        self._proactivity_label = QLabel("0.5")
        proact_layout = QHBoxLayout()
        proact_layout.addWidget(self._proactivity_slider)
        proact_layout.addWidget(self._proactivity_label)
        layout.addRow(QLabel("<b>Proactivity</b>"), proact_layout)

        self._traits_edit = QLineEdit()
        self._traits_edit.setPlaceholderText("e.g. friendly, knowledgeable, empathetic")
        layout.addRow(QLabel("<b>Traits</b> (comma-separated)"), self._traits_edit)

        self._humor_slider.valueChanged.connect(self._on_humor_changed)
        self._proactivity_slider.valueChanged.connect(self._on_proactivity_changed)

    def _on_humor_changed(self, val: int) -> None:
        self._humor_label.setText(f"{val / 100:.2f}")

    def _on_proactivity_changed(self, val: int) -> None:
        self._proactivity_label.setText(f"{val / 100:.2f}")

    def load_profile(self, profile: dict[str, Any]) -> None:
        personality = profile.get("personality", {})
        humor = personality.get("humor", 0.5)
        self._humor_slider.setValue(int(humor * 100))
        self._humor_label.setText(f"{humor:.2f}")

        proact = personality.get("proactivity", 0.3)
        self._proactivity_slider.setValue(int(proact * 100))
        self._proactivity_label.setText(f"{proact:.2f}")

        traits = personality.get("traits", [])
        self._traits_edit.setText(", ".join(traits))

    def get_personality(self) -> dict[str, Any]:
        traits_text = self._traits_edit.text().strip()
        traits = [t.strip() for t in traits_text.split(",") if t.strip()]
        return {
            "humor": self._humor_slider.value() / 100,
            "proactivity": self._proactivity_slider.value() / 100,
            "traits": traits,
        }


class ExpertiseTab(QWidget):
    """Tab for editing expertise section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._areas_edit = QLineEdit()
        self._areas_edit.setPlaceholderText("e.g. programming, medicine, finance")
        layout.addRow(QLabel("<b>Expertise areas</b> (comma-separated)"), self._areas_edit)

    def load_profile(self, profile: dict[str, Any]) -> None:
        expertise = profile.get("expertise", {})
        areas = expertise.get("areas", [])
        self._areas_edit.setText(", ".join(areas))

    def get_expertise(self) -> dict[str, Any]:
        areas_text = self._areas_edit.text().strip()
        areas = [a.strip() for a in areas_text.split(",") if a.strip()]
        return {"areas": areas}


class BehaviorTab(QWidget):
    """Tab for editing behavior section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._approach_combo = QComboBox()
        self._approach_combo.addItems(["direct", "educational", "collaborative"])
        layout.addRow(QLabel("<b>Approach</b>"), self._approach_combo)

        self._uncertainty_combo = QComboBox()
        self._uncertainty_combo.addItems(["ask_clarify", "guess", "hedge"])
        layout.addRow(QLabel("<b>Uncertainty handling</b>"), self._uncertainty_combo)

        self._question_combo = QComboBox()
        self._question_combo.addItems(["open_ended", "closed", "optional"])
        layout.addRow(QLabel("<b>Question style</b>"), self._question_combo)

    def load_profile(self, profile: dict[str, Any]) -> None:
        behavior = profile.get("behavior", {})
        self._approach_combo.setCurrentText(behavior.get("response_approach", "direct"))
        self._uncertainty_combo.setCurrentText(behavior.get("uncertainty_handling", "ask_clarify"))
        self._question_combo.setCurrentText(behavior.get("question_style", "open_ended"))

    def get_behavior(self) -> dict[str, Any]:
        return {
            "response_approach": self._approach_combo.currentText(),
            "uncertainty_handling": self._uncertainty_combo.currentText(),
            "question_style": self._question_combo.currentText(),
        }


class BoundariesTab(QWidget):
    """Tab for editing boundaries section of assistant profile."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QFormLayout(self)

        self._custom_instructions = QTextEdit()
        self._custom_instructions.setPlaceholderText("Additional constraints or instructions...")
        self._custom_instructions.setFixedHeight(100)
        layout.addRow(QLabel("<b>Custom instructions</b>"), self._custom_instructions)

    def load_profile(self, profile: dict[str, Any]) -> None:
        boundaries = profile.get("boundaries", {})
        self._custom_instructions.setPlainText(boundaries.get("custom_instructions", ""))

    def get_boundaries(self) -> dict[str, Any]:
        return {
            "custom_instructions": self._custom_instructions.toPlainText().strip(),
        }