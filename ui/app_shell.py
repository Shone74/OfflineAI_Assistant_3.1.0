"""Reference-based application shell for the final standalone build.

Redizajn prema zvaničnom workspace dizajnu (Izgled Aplikaccije/
assistant_workspace_preview.py + docs/design_system.md):

- Topbar: ☰ (toggle sidebar) · ime asistenta · "● Local" · Context (toggle) · ⚙
- Sidebar: ime asistenta, "+ New Conversation", navigacija sa selected
  stanjem, "👤 My Profile" + "⚙ Settings" na dnu
- Stranice: QStackedWidget
- Context panel: Assistant / AI Model / Capabilities / Memory + 🔒 footer

Stilovi se NE primenjuju lokalno — dolaze iz ThemeManager-a (ui/design).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ui.theme_manager import ThemeManager


class AppShell(QMainWindow):
    """Main application shell matching the official workspace design."""

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
        self._nav_buttons: dict[str, QPushButton] = {}
        self._assistant = assistant
        self._model_name = model_name
        self._capabilities = capabilities or []
        self._memory_count = memory_count

        self.setWindowTitle("Offline AI Assistant")
        self.resize(1500, 900)
        self.setObjectName("shell")

        self._build_ui()
        # Označi aktivnu stranicu (default route) u navigaciji
        self._mark_active_nav(self._default_route)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("page_root")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)

        # Stranice prve — _build_sidebar cita self._pages za ADVANCED sekciju
        self._pages_widget = QStackedWidget()
        for name, page in self._pages:
            self._page_map[name] = page
            self._pages_widget.addWidget(page)
        self._splitter.addWidget(self._pages_widget)

        self._sidebar = self._build_sidebar()
        self._splitter.insertWidget(0, self._sidebar)

        self._context_panel = self._build_context_panel()
        self._splitter.addWidget(self._context_panel)

        self._splitter.setSizes([240, 980, 280])
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(2, False)
        body.addWidget(self._splitter)

        target = self._page_map.get(self._default_route)
        if target is not None:
            self._pages_widget.setCurrentWidget(target)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topbar")
        bar.setFixedHeight(52)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self._menu_button = QPushButton("☰")
        self._menu_button.setObjectName("topbar_button")
        self._menu_button.setToolTip("Prikaži/sakrij navigaciju")
        self._menu_button.clicked.connect(self.toggle_sidebar)
        layout.addWidget(self._menu_button)

        self._topbar_title = QLabel(self._assistant_name)
        self._topbar_title.setObjectName("topbar_title")
        layout.addWidget(self._topbar_title)

        layout.addStretch()

        local_status = QLabel("● Local")
        local_status.setObjectName("status_local")
        layout.addWidget(local_status)

        self._context_button = QPushButton("Context")
        self._context_button.setObjectName("topbar_button")
        self._context_button.setToolTip("Prikaži/sakrij context panel")
        self._context_button.clicked.connect(self.toggle_context_panel)
        layout.addWidget(self._context_button)

        self._settings_button = QPushButton("⚙")
        self._settings_button.setObjectName("topbar_button")
        self._settings_button.setToolTip("Settings")
        self._settings_button.clicked.connect(lambda: self._navigate("Settings"))
        layout.addWidget(self._settings_button)

        return bar

    def _build_sidebar(self) -> QWidget:
        container = QFrame()
        container.setObjectName("sidebar")
        container.setMinimumWidth(200)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 18, 12, 12)
        layout.setSpacing(6)

        name = QLabel(self._assistant_name)
        name.setObjectName("sidebar_assistant_name")
        name.setWordWrap(True)
        layout.addWidget(name)

        subtitle = QLabel("Your Personal Assistant")
        subtitle.setObjectName("sidebar_subtitle")
        layout.addWidget(subtitle)

        layout.addSpacing(14)

        new_chat = QPushButton("＋  New Conversation")
        new_chat.setObjectName("new_conversation")
        new_chat.setCursor(Qt.CursorShape.PointingHandCursor)
        new_chat.clicked.connect(self._on_new_conversation)
        layout.addWidget(new_chat)

        layout.addSpacing(10)

        nav_items = [
            ("Home", "🏠"),
            ("Chat", "💬"),
            ("Memory", "🧠"),
            ("Knowledge", "📚"),
            ("Capabilities", "🧩"),
            ("Projects", "🗂"),
        ]

        for route, icon in nav_items:
            btn = QPushButton(f"{icon}  {route}")
            btn.setObjectName("nav_button")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, r=route: self._navigate(r))
            self._nav_buttons[route] = btn
            layout.addWidget(btn)

        # Stranice van primarne navigacije (iz final bootstrap-a):
        # Agents, Tools, Voice, Automation, Workflow, Models → "Advanced"
        advanced_routes = [
            ("Models", "📦"),
            ("Agents", "🤖"),
            ("Tools", "🔧"),
            ("Voice", "🎤"),
            ("Automation", "⚡"),
            ("Workflow", "🧪"),
        ]
        has_advanced = any(r in self._page_map for r, _ in advanced_routes)
        if has_advanced:
            section = QLabel("ADVANCED")
            section.setObjectName("sidebar_section")
            layout.addSpacing(8)
            layout.addWidget(section)
            for route, icon in advanced_routes:
                if route in self._page_map:
                    btn = QPushButton(f"{icon}  {route}")
                    btn.setObjectName("nav_button")
                    btn.setCursor(Qt.CursorShape.PointingHandCursor)
                    btn.setCheckable(True)
                    btn.clicked.connect(lambda _, r=route: self._navigate(r))
                    self._nav_buttons[route] = btn
                    layout.addWidget(btn)

        layout.addStretch()

        profile = QPushButton("👤  My Profile")
        profile.setObjectName("nav_button")
        profile.setCursor(Qt.CursorShape.PointingHandCursor)
        profile.clicked.connect(lambda: self._navigate("Settings"))
        layout.addWidget(profile)

        settings = QPushButton("⚙  Settings")
        settings.setObjectName("nav_button")
        settings.setCursor(Qt.CursorShape.PointingHandCursor)
        settings.clicked.connect(lambda: self._navigate("Settings"))
        layout.addWidget(settings)

        return container

    def _build_context_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("context_panel")
        panel.setMinimumWidth(220)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(6)

        def section_title(text: str) -> QLabel:
            label = QLabel(text.upper())
            label.setObjectName("context_section_title")
            return label

        def value(text: str) -> QLabel:
            label = QLabel(text)
            label.setObjectName("context_value")
            label.setWordWrap(True)
            return label

        # Assistant
        layout.addWidget(section_title("Assistant"))
        layout.addWidget(value(f"{self._assistant_name}\nBalanced · Serbian"))

        layout.addSpacing(10)

        # AI Model
        layout.addWidget(section_title("AI Model"))
        self._context_model_label = value(self._format_model_text())
        layout.addWidget(self._context_model_label)

        layout.addSpacing(10)

        # Capabilities
        layout.addWidget(section_title("Capabilities"))
        cap_text = (
            "\n".join(f"✓ {c}" for c in self._capabilities[:6])
            if self._capabilities
            else "No capabilities available"
        )
        self._context_caps_label = value(cap_text)
        layout.addWidget(self._context_caps_label)

        layout.addSpacing(10)

        # Memory
        layout.addWidget(section_title("Memory"))
        self._context_memory_label = value(f"{self._memory_count} recent messages")
        layout.addWidget(self._context_memory_label)

        layout.addStretch()

        privacy = QLabel("🔒 Local AI\nYour data stays on this device.")
        privacy.setObjectName("context_privacy")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        return panel

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, name: str) -> None:
        target = self._page_map.get(name)
        if target is not None:
            self._pages_widget.setCurrentWidget(target)
            self._mark_active_nav(name)

    def _mark_active_nav(self, route: str) -> None:
        for name, btn in self._nav_buttons.items():
            btn.setChecked(name == route)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def toggle_sidebar(self) -> None:
        self._sidebar_visible = not self._sidebar_visible
        self._sidebar.setVisible(self._sidebar_visible)

    def toggle_context_panel(self) -> None:
        self._context_visible = not self._context_visible
        self._context_panel.setVisible(self._context_visible)

    def set_assistant_name(self, name: str) -> None:
        self._assistant_name = name
        self._topbar_title.setText(name)

    def update_model_status(self, model_name: str | None) -> None:
        self._model_name = model_name or "No model loaded"
        if hasattr(self, "_context_model_label"):
            self._context_model_label.setText(self._format_model_text())

    def update_memory_count(self, count: int) -> None:
        self._memory_count = count
        if hasattr(self, "_context_memory_label"):
            self._context_memory_label.setText(f"{count} recent messages")

    # ------------------------------------------------------------------
    # Interni helperi
    # ------------------------------------------------------------------

    def _format_model_text(self) -> str:
        if self._model_name and self._model_name != "No model loaded":
            return f"{self._model_name}\n● Ready · Local"
        return "No model loaded"

    def _on_new_conversation(self) -> None:
        # TODO (faza 3.4): povezati na EventBus NEW_CHAT_REQUESTED event
        # (Assistant cisti ShortTermMemory). Za sada direktan poziv ako
        # asistent postoji, inace samo navigacija na Chat.
        if self._assistant is not None and hasattr(self._assistant, "_memory"):
            memory = getattr(self._assistant, "_memory", None)
            if memory is not None and hasattr(memory, "start_conversation"):
                try:
                    memory.start_conversation()
                except Exception:
                    pass
        self._navigate("Chat")
