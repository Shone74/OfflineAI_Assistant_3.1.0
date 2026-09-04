"""Capabilities page — shows what the assistant and model can do."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.design import WORKSPACE as _PALETTE

_GRAPHITE = _PALETTE.surface
_GRAPHITE_CARD = _PALETTE.surface_card
_GRAPHITE_DARK_CARD = _PALETTE.surface_dark
_GRAPHITE_BORDER = _PALETTE.border
_EMERALD = _PALETTE.emerald
_EMERGENCY_HOVER = _PALETTE.emerald_hover
_EMERALD_TEXT = _PALETTE.emerald_text
_EMERALD_BG_TINT = _PALETTE.tint(0.08)
_EMERALD_BORDER_TINT = _PALETTE.tint(0.25)
_TEXT_PRIMARY = _PALETTE.text_primary
_TEXT_SECONDARY = _PALETTE.text_secondary
_TEXT_MUTED = _PALETTE.text_muted

# Ordered list of (UI label, attribute name on ModelCapabilities, description)
_CAPABILITY_MAP: list[tuple[str, str, str]] = [
    ("Text Generation", "text_generation", "Generate human-quality text responses"),
    ("Streaming", "streaming", "Real-time token streaming"),
    ("Code Generation", "code_generation", "Write and understand code"),
    ("Document Processing", "function_calling", "Use external tools and plugins"),
    ("Tool Calling", "tool_calling", "Use external tools and plugins"),
    ("Function Calling", "function_calling", "Structured function/tool invocation"),
    ("Reasoning", "reasoning", "Step-by-step logical reasoning"),
    ("Multimodal", "multimodal", "Process images and multimodal input"),
    ("Vision", "vision", "Analyze and understand visual content"),
    ("JSON Output", "json_output", "Structured JSON response format"),
    ("Structured Output", "structured_output", "Schema-constrained response format"),
    ("Embeddings", "embeddings", "Text embedding generation"),
    ("Long Context", "long_context", "Extended conversation context (32K+ tokens)"),
]


class CapabilitiesPage(QWidget):
    """Display the assistant's technical and functional capabilities."""

    def __init__(self, assistant: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._model_name_label: QLabel | None = None
        self._model_status_label: QLabel | None = None
        self._no_model_label: QLabel | None = None
        self._caps_container: QFrame | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Capabilities")
        title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 22px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        self._model_name_label = QLabel("Model: N/A")
        self._model_name_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 13px;")
        header.addWidget(self._model_name_label)
        layout.addLayout(header)

        self._model_status_label = QLabel("Status: No model loaded")
        self._model_status_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self._model_status_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_GRAPHITE}; }}"
            f"QScrollBar:vertical {{ background: {_GRAPHITE_DARK_CARD};"
            f" border: none; width: 8px; margin: 0px; }}"
            f"QScrollBar::handle:vertical {{ background: {_GRAPHITE_BORDER};"
            f" border-radius: 4px; }}"
        )

        self._caps_container = QFrame()
        content_layout = QVBoxLayout(self._caps_container)
        content_layout.setSpacing(14)

        self._no_model_label = QLabel("No model is currently loaded.")
        self._no_model_label.setStyleSheet(
            f"color: {_TEXT_SECONDARY}; font-size: 14px; padding-top: 20px;"
        )
        self._no_model_label.hide()
        content_layout.addWidget(self._no_model_label)

        for label_text, attr, desc in _CAPABILITY_MAP:
            content_layout.addWidget(
                self._build_capability_card(label_text, desc, False)
            )

        content_layout.addStretch()
        scroll.setWidget(self._caps_container)
        layout.addWidget(scroll)

        self._refresh_capabilities()

    def _build_capability_card(self, name: str, desc: str, enabled: bool) -> QFrame:
        card = QFrame()
        color = _EMERALD if enabled else _GRAPHITE_BORDER
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {color};"
            f"border-radius: 8px; padding: 14px 16px;"
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        dot = QFrame()
        dot.setFixedSize(10, 10)
        dot.setStyleSheet(
            f"background: {color}; border-radius: 50%;"
        )
        layout.addWidget(dot)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)
        title = QLabel(name)
        title.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 14px; font-weight: 600;")
        desc_label = QLabel(desc)
        desc_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        desc_label.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(desc_label)
        layout.addLayout(text_layout)

        status = QLabel("Active" if enabled else "Inactive")
        status.setStyleSheet(
            f"color: {_EMERGENCY_HOVER if enabled else _TEXT_MUTED};"
            f" font-size: 11px; font-weight: 600;"
        )
        layout.addWidget(status)

        return card

    def _refresh_capabilities(self) -> None:
        """Rebuild capability cards from the current model state."""
        if self._no_model_label is None or self._caps_container is None:
            return

        caps_dict: dict[str, bool] | None = None
        model_name = "N/A"
        status_text = "No model loaded"

        if self._assistant is not None:
            model_name = getattr(self._assistant, "model_name", "N/A")
            caps_dict = getattr(self._assistant, "model_capabilities", None)
            engine = getattr(self._assistant, "_engine", None)
            if engine is not None:
                load_status = getattr(engine, "load_status", "")
                if load_status == "ready":
                    status_text = "Model loaded and ready"
                else:
                    status_text = f"Model status: {load_status}"

        if self._model_name_label is not None:
            self._model_name_label.setText(f"Model: {model_name}")

        if self._model_status_label is not None:
            self._model_status_label.setText(f"Status: {status_text}")

        # Remove all existing capability cards
        container_layout = self._caps_container.layout()
        if container_layout is not None:
            while container_layout.count():
                item = container_layout.takeAt(0)
                if item.widget():
                    item.widget().setParent(None)

        if caps_dict is None:
            self._no_model_label.setText(
                f"No model is currently loaded.\n\n"
                f"Loaded Model: {model_name}"
            )
            self._no_model_label.show()
            return

        self._no_model_label.hide()

        for label_text, attr, desc in _CAPABILITY_MAP:
            is_enabled = bool(caps_dict.get(attr, False)) if isinstance(caps_dict, dict) else bool(getattr(caps_dict, attr, False))
            container_layout.addWidget(
                self._build_capability_card(label_text, desc, is_enabled)
            )

        container_layout.addStretch()

    def refresh(self) -> None:
        """Public refresh — call when the active model changes."""
        self._refresh_capabilities()
