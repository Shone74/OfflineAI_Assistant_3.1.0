"""Reference-based application shell for the final standalone build."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.theme_manager import ThemeManager


class AppShell(QMainWindow):
    """Main application shell matching the reference visual direction."""

    def __init__(
        self,
        theme: ThemeManager,
        assistant_name: str = "Assistant",
        pages: list[tuple[str, QWidget]] | None = None,
        default_route: str = "Home",
        assistant=None,
        model_name: str = "No model loaded",
        capabilities: list[str] | None = None,
        memory_count: int = 0,
    ) -> None:
        super().__init__()
        self._theme = theme
        self._assistant_name = assistant_name
        self._pages = pages or []
        self._default_route = default_route
        self._sidebar_visible = True
        self._context_visible = True
        self._page_map: dict[str, QWidget] = {}
        self._assistant = assistant
        self._model_name = model_name
        self._capabilities = capabilities or []
        self._memory_count = memory_count

        self.setWindowTitle("Offline AI Assistant")
        self.resize(1200, 800)

        self._build_ui()
        self._apply_shell_style()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        sidebar = self._build_sidebar()
        splitter.addWidget(sidebar)

        self._pages_widget = QStackedWidget()
        for name, page in self._pages:
            self._page_map[name] = page
            self._pages_widget.addWidget(page)
        splitter.addWidget(self._pages_widget)

        context = self._build_context_panel()
        splitter.addWidget(context)

        splitter.setSizes([240, 900, 280])
        root.addWidget(splitter)

        target = self._page_map.get(self._default_route)
        if target is not None:
            self._pages_widget.setCurrentWidget(target)

    def _build_sidebar(self) -> QWidget:
        container = QFrame()
        container.setObjectName("sidebar")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(8)

        brand = QLabel(self._assistant_name)
        brand.setObjectName("assistant_name")
        brand.setStyleSheet("font-size: 12pt; font-weight: 600;")
        layout.addWidget(brand)

        subtitle = QLabel("Personal workspace")
        subtitle.setStyleSheet("color: #A8AFB5;")
        layout.addWidget(subtitle)

        layout.addSpacing(18)

        nav_items = [
            ("Home", "🏠"),
            ("Chat", "💬"),
            ("Memory", "🧠"),
            ("Knowledge", "📚"),
            ("Capabilities", "🧩"),
            ("Projects", "📁"),
            ("Settings", "⚙"),
        ]

        for name, icon in nav_items:
            btn = QToolButton()
            btn.setObjectName("nav_button")
            btn.setText(f"{icon}  {name}")
            btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda _, n=name: self._navigate(n))
            layout.addWidget(btn)

        layout.addStretch()
        return container

    def _build_context_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("context_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Context"))

        assistant = QLabel(f"{self._assistant_name}\nBalanced · Serbian")
        assistant.setStyleSheet("color: #A8AFB5;")
        layout.addWidget(assistant)

        model_text = self._model_name or "No model loaded"
        model = QLabel(f"{model_text}\n● Ready · GPU" if self._model_name else "No model loaded")
        model.setStyleSheet("color: #A8AFB5;")
        layout.addWidget(model)

        cap_text = "\n".join(f"✓ {c}" for c in self._capabilities) if self._capabilities else "No capabilities available"
        capabilities = QLabel(cap_text)
        capabilities.setStyleSheet("color: #A8AFB5;")
        layout.addWidget(capabilities)

        memory = QLabel(f"{self._memory_count} recent messages")
        memory.setStyleSheet("color: #A8AFB5;")
        layout.addWidget(memory)

        layout.addStretch()

        privacy = QLabel("🔒 Local AI\nYour data stays on this device.")
        privacy.setStyleSheet("color: #27C48A;")
        layout.addWidget(privacy)

        return panel

    def _navigate(self, name: str) -> None:
        target = self._page_map.get(name)
        if target is not None:
            self._pages_widget.setCurrentWidget(target)

    def _apply_shell_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow { background-color: #202326; color: #F1F3F4; }
            QFrame#sidebar { background-color: #181A1D; border-right: 1px solid #373C41; }
            QFrame#context_panel { background-color: #181A1D; border-left: 1px solid #373C41; }
            QToolButton#nav_button { background-color: transparent; border: none; border-radius: 6px; padding: 10px 12px; text-align: left; }
            QToolButton#nav_button:hover { background-color: #292D31; }
            QPushButton { background-color: #292D31; border: 1px solid #373C41; border-radius: 7px; padding: 8px 14px; }
            QPushButton:hover { border-color: #27C48A; }
            QPushButton#primary_button { background-color: #27C48A; color: #101513; border: none; font-weight: 600; }
            QPushButton#primary_button:hover { background-color: #1E9D70; }
            QLabel { font-family: "Segoe UI", Arial, sans-serif; font-size: 10pt; }
            QLabel#assistant_name { font-size: 12pt; font-weight: 600; }
            QTextEdit, QLineEdit, QComboBox { background-color: #292D31; border: 1px solid #373C41; border-radius: 7px; padding: 8px; }
            QTextEdit:focus, QLineEdit:focus, QComboBox:focus { border-color: #27C48A; }
            QSplitter::handle { background-color: #373C41; }
            QScrollArea { border: none; background-color: transparent; }
            """
        )
