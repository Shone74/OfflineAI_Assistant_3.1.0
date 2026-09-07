import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ============================================================
# CONFIGURATION
# ============================================================

APP_NAME = "Offline AI Assistant"

GRAPHITE = "#202326"
GRAPHITE_LIGHT = "#292D31"
GRAPHITE_DARK = "#181A1D"

EMERALD = "#27C48A"
EMERALD_DARK = "#1E9D70"

TEXT_PRIMARY = "#F1F3F4"
TEXT_SECONDARY = "#A8AFB5"
BORDER = "#373C41"

RED = "#E35D6A"
YELLOW = "#D9B44A"


# ============================================================
# GLOBAL STYLE
# ============================================================

APP_STYLE = f"""
QMainWindow {{
    background-color: {GRAPHITE};
    color: {TEXT_PRIMARY};
}}

QWidget {{
    color: {TEXT_PRIMARY};
    font-family: "Segoe UI";
    font-size: 10pt;
}}

QFrame#sidebar {{
    background-color: {GRAPHITE_DARK};
    border-right: 1px solid {BORDER};
}}

QFrame#topbar {{
    background-color: {GRAPHITE};
    border-bottom: 1px solid {BORDER};
}}

QFrame#context_panel {{
    background-color: {GRAPHITE_DARK};
    border-left: 1px solid {BORDER};
}}

QLabel#assistant_name {{
    font-size: 16pt;
    font-weight: 600;
}}

QLabel#assistant_subtitle {{
    color: {TEXT_SECONDARY};
}}

QLabel#section_title {{
    font-size: 12pt;
    font-weight: 600;
}}

QLabel#page_title {{
    font-size: 22pt;
    font-weight: 600;
}}

QLabel#page_subtitle {{
    color: {TEXT_SECONDARY};
    font-size: 10pt;
}}

QLabel#status_local {{
    color: {EMERALD};
    font-weight: 600;
}}

QPushButton {{
    background-color: {GRAPHITE_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px 14px;
}}

QPushButton:hover {{
    border-color: {EMERALD};
}}

QPushButton#primary_button {{
    background-color: {EMERALD};
    color: #101513;
    border: none;
    font-weight: 600;
}}

QPushButton#primary_button:hover {{
    background-color: {EMERALD_DARK};
}}

QToolButton {{
    background-color: transparent;
    border: none;
    border-radius: 6px;
    padding: 8px;
}}

QToolButton:hover {{
    background-color: {GRAPHITE_LIGHT};
}}

QToolButton#nav_button {{
    text-align: left;
    padding: 10px 12px;
}}

QToolButton#nav_button:hover {{
    background-color: {GRAPHITE_LIGHT};
}}

QLineEdit, QTextEdit, QComboBox {{
    background-color: {GRAPHITE_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 8px;
}}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
    border-color: {EMERALD};
}}

QListWidget {{
    background-color: transparent;
    border: none;
}}

QListWidget::item {{
    padding: 9px;
    border-radius: 6px;
}}

QListWidget::item:hover {{
    background-color: {GRAPHITE_LIGHT};
}}

QListWidget::item:selected {{
    background-color: {GRAPHITE_LIGHT};
    color: {EMERALD};
}}

QCheckBox {{
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
}}

QSplitter::handle {{
    background-color: {BORDER};
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}
"""


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_label(text, object_name=None):
    label = QLabel(text)

    if object_name:
        label.setObjectName(object_name)

    return label


def create_nav_button(text):
    button = QToolButton()
    button.setObjectName("nav_button")
    button.setText(text)
    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    button.setCursor(Qt.PointingHandCursor)
    return button


def create_card(title, description, callback=None):
    card = QFrame()
    card.setStyleSheet(
        f"""
        QFrame {{
            background-color: {GRAPHITE_LIGHT};
            border: 1px solid {BORDER};
            border-radius: 10px;
        }}
        """
    )

    layout = QVBoxLayout(card)
    layout.setContentsMargins(16, 14, 16, 14)

    title_label = create_label(title)
    title_label.setStyleSheet(
        "font-size: 11pt; font-weight: 600;"
    )

    description_label = create_label(description)
    description_label.setWordWrap(True)
    description_label.setStyleSheet(
        f"color: {TEXT_SECONDARY};"
    )

    layout.addWidget(title_label)
    layout.addWidget(description_label)

    if callback:
        button = QPushButton("Open")
        button.clicked.connect(callback)
        layout.addWidget(button)

    return card


# ============================================================
# ASSISTANT HUB
# ============================================================

class AssistantHub(QWidget):

    def __init__(self, main_window):
        super().__init__()

        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(22)

        title = create_label("Your Assistant", "page_title")
        subtitle = create_label(
            "This is your personal AI workspace. "
            "Everything here adapts to the way you use your assistant.",
            "page_subtitle",
        )

        layout.addWidget(title)
        layout.addWidget(subtitle)

        # Assistant Card
        assistant_card = QFrame()
        assistant_card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {GRAPHITE_LIGHT};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
            """
        )

        card_layout = QVBoxLayout(assistant_card)
        card_layout.setContentsMargins(28, 28, 28, 28)
        card_layout.setAlignment(Qt.AlignCenter)

        self.assistant_icon = QLabel("✦")
        self.assistant_icon.setAlignment(Qt.AlignCenter)
        self.assistant_icon.setStyleSheet(
            f"""
            color: {EMERALD};
            font-size: 30pt;
            """
        )

        self.assistant_name = create_label(
            self.main_window.assistant_name,
            "assistant_name",
        )
        self.assistant_name.setAlignment(Qt.AlignCenter)

        self.assistant_subtitle = create_label(
            "Your Personal AI Assistant",
            "assistant_subtitle",
        )
        self.assistant_subtitle.setAlignment(Qt.AlignCenter)

        self.status = create_label(
            "● Ready     🔒 Local AI",
            "status_local",
        )
        self.status.setAlignment(Qt.AlignCenter)

        start_button = QPushButton("Start Conversation")
        start_button.setObjectName("primary_button")
        start_button.clicked.connect(
            lambda: self.main_window.show_page("Chat")
        )

        card_layout.addWidget(self.assistant_icon)
        card_layout.addWidget(self.assistant_name)
        card_layout.addWidget(self.assistant_subtitle)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.status)
        card_layout.addSpacing(12)
        card_layout.addWidget(start_button)

        layout.addWidget(assistant_card)

        # Snapshot
        snapshot_title = create_label(
            "Assistant Snapshot",
            "section_title",
        )
        layout.addWidget(snapshot_title)

        snapshot_grid = QGridLayout()
        snapshot_grid.setSpacing(12)

        snapshot_grid.addWidget(
            create_card(
                "Identity",
                "Balanced · Detailed · Serbian",
            ),
            0,
            0,
        )

        snapshot_grid.addWidget(
            create_card(
                "AI Engine",
                "Qwen 2.5 7B · GPU · Ready",
            ),
            0,
            1,
        )

        snapshot_grid.addWidget(
            create_card(
                "Capabilities",
                "Text · Code · Vision · Documents",
            ),
            1,
            0,
        )

        snapshot_grid.addWidget(
            create_card(
                "Privacy",
                "Local processing · Local data",
            ),
            1,
            1,
        )

        layout.addLayout(snapshot_grid)

        # Quick actions
        quick_title = create_label(
            "Quick Actions",
            "section_title",
        )
        layout.addWidget(quick_title)

        quick_grid = QGridLayout()
        quick_grid.setSpacing(12)

        quick_grid.addWidget(
            create_card(
                "💬 Chat",
                "Start a new conversation.",
                lambda: self.main_window.show_page("Chat"),
            ),
            0,
            0,
        )

        quick_grid.addWidget(
            create_card(
                "🧠 Memory",
                "See what your assistant remembers.",
                lambda: self.main_window.show_page("Memory"),
            ),
            0,
            1,
        )

        quick_grid.addWidget(
            create_card(
                "📚 Knowledge",
                "Manage your local knowledge sources.",
                lambda: self.main_window.show_page("Knowledge"),
            ),
            1,
            0,
        )

        quick_grid.addWidget(
            create_card(
                "🧩 Capabilities",
                "Choose what your assistant can do.",
                lambda: self.main_window.show_page("Capabilities"),
            ),
            1,
            1,
        )

        layout.addLayout(quick_grid)
        layout.addStretch()


# ============================================================
# CHAT WORKSPACE
# ============================================================

class ChatWorkspace(QWidget):

    def __init__(self, main_window):
        super().__init__()

        self.main_window = main_window

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 20)

        header = QHBoxLayout()

        title_box = QVBoxLayout()

        title_box.addWidget(
            create_label(
                self.main_window.assistant_name,
                "page_title",
            )
        )

        title_box.addWidget(
            create_label(
                "Your personal AI conversation space",
                "page_subtitle",
            )
        )

        header.addLayout(title_box)
        header.addStretch()

        local_label = create_label(
            "● Local AI",
            "status_local",
        )

        header.addWidget(local_label)

        layout.addLayout(header)

        self.chat_view = QTextEdit()
        self.chat_view.setReadOnly(True)

        self.chat_view.setHtml(
            f"""
            <p>
            <b style="color:{EMERALD};">
            {self.main_window.assistant_name}
            </b>
            </p>

            <p>
            Hello! I'm your personal Offline AI Assistant.
            </p>

            <p>
            I'm ready to help you with the capabilities
            you've chosen.
            </p>

            <p>
            <i>
            Everything is local. Everything is yours.
            </i>
            </p>
            """
        )

        layout.addWidget(self.chat_view)

        # Capability buttons
        capability_bar = QHBoxLayout()

        for capability in [
            "📎 Files",
            "🖼 Vision",
            "🧠 Memory",
        ]:
            button = QPushButton(capability)
            button.clicked.connect(
                lambda checked=False, name=capability:
                self.add_system_message(name)
            )
            capability_bar.addWidget(button)

        capability_bar.addStretch()

        layout.addLayout(capability_bar)

        # Input
        input_row = QHBoxLayout()

        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText(
            "Type a message..."
        )

        self.message_input.returnPressed.connect(
            self.send_message
        )

        send_button = QPushButton("➤")
        send_button.setObjectName("primary_button")
        send_button.setFixedWidth(55)
        send_button.clicked.connect(
            self.send_message
        )

        input_row.addWidget(self.message_input)
        input_row.addWidget(send_button)

        layout.addLayout(input_row)

    def send_message(self):

        message = self.message_input.text().strip()

        if not message:
            return

        self.chat_view.append(
            f"""
            <p>
            <b>You</b>
            </p>

            <p>{message}</p>

            <p>
            <b style="color:{EMERALD};">
            {self.main_window.assistant_name}
            </b>
            </p>

            <p>
            This is a local preview response.
            In the real application, your selected
            AI model will generate the response here.
            </p>
            """
        )

        self.message_input.clear()

    def add_system_message(self, name):

        self.chat_view.append(
            f"""
            <p>
            <span style="color:{EMERALD};">
            Capability activated:
            </span>
            {name}
            </p>
            """
        )


# ============================================================
# MEMORY
# ============================================================

class MemoryPage(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addWidget(
            create_label(
                "What Your Assistant Remembers",
                "page_title",
            )
        )

        layout.addWidget(
            create_label(
                "You decide what your assistant remembers. "
                "You can edit or forget anything at any time.",
                "page_subtitle",
            )
        )

        memory_list = QListWidget()

        memories = [
            "You prefer detailed technical explanations.",
            "You are working on a local AI assistant project.",
            "You prefer a dark Graphite + Emerald interface.",
            "You prefer communicating with your assistant in Serbian.",
        ]

        for memory in memories:

            item = QListWidgetItem(
                f"🧠  {memory}"
            )

            memory_list.addItem(item)

        layout.addWidget(memory_list)

        buttons = QHBoxLayout()

        add_button = QPushButton(
            "Add Memory"
        )

        forget_button = QPushButton(
            "Forget Selected"
        )

        buttons.addWidget(add_button)
        buttons.addWidget(forget_button)
        buttons.addStretch()

        layout.addLayout(buttons)


# ============================================================
# KNOWLEDGE
# ============================================================

class KnowledgePage(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addWidget(
            create_label(
                "Knowledge",
                "page_title",
            )
        )

        layout.addWidget(
            create_label(
                "Give your assistant access to local information "
                "you choose to make available.",
                "page_subtitle",
            )
        )

        sources = QListWidget()

        for source in [
            "📁 Projects",
            "📁 Documentation",
            "📄 Project Requirements.pdf",
            "📄 Personal Notes.md",
        ]:
            sources.addItem(source)

        layout.addWidget(sources)

        add_button = QPushButton(
            "+ Add Knowledge Source"
        )

        layout.addWidget(add_button)


# ============================================================
# CAPABILITIES
# ============================================================

class CapabilitiesPage(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addWidget(
            create_label(
                "Capabilities",
                "page_title",
            )
        )

        layout.addWidget(
            create_label(
                "Choose what you want your assistant to be able to do.",
                "page_subtitle",
            )
        )

        capabilities = [
            (
                "Text & Conversation",
                "Available with current model.",
                True,
            ),
            (
                "Programming & Development",
                "Available with current model.",
                True,
            ),
            (
                "Vision",
                "Provided by the selected vision model.",
                True,
            ),
            (
                "Documents",
                "Local document understanding.",
                True,
            ),
            (
                "Voice Interaction",
                "Requires an additional local speech model.",
                False,
            ),
            (
                "Automation",
                "Requires additional configuration.",
                False,
            ),
        ]

        for name, description, enabled in capabilities:

            row = QFrame()

            row.setStyleSheet(
                f"""
                QFrame {{
                    background-color: {GRAPHITE_LIGHT};
                    border: 1px solid {BORDER};
                    border-radius: 8px;
                }}
                """
            )

            row_layout = QHBoxLayout(row)

            check = QCheckBox(name)
            check.setChecked(enabled)

            info = QLabel(description)
            info.setStyleSheet(
                f"color: {TEXT_SECONDARY};"
            )

            row_layout.addWidget(check)
            row_layout.addStretch()
            row_layout.addWidget(info)

            layout.addWidget(row)

        layout.addStretch()


# ============================================================
# PROJECTS
# ============================================================

class ProjectsPage(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addWidget(
            create_label(
                "Projects",
                "page_title",
            )
        )

        layout.addWidget(
            create_label(
                "Keep conversations, knowledge and context organized.",
                "page_subtitle",
            )
        )

        projects = QListWidget()

        for project in [
            "🎮  Local Game Library",
            "🤖  Offline AI Assistant",
            "💻  My Website",
            "📚  Research",
        ]:
            projects.addItem(project)

        layout.addWidget(projects)

        add_button = QPushButton(
            "+ New Project"
        )

        layout.addWidget(add_button)


# ============================================================
# SETTINGS
# ============================================================

class SettingsPage(QWidget):

    def __init__(self):

        super().__init__()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)

        layout.addWidget(
            create_label(
                "Settings",
                "page_title",
            )
        )

        layout.addWidget(
            create_label(
                "Configure how your assistant and local AI environment work.",
                "page_subtitle",
            )
        )

        tabs = QComboBox()

        tabs.addItems([
            "General",
            "Assistant",
            "AI / Model",
            "Privacy & Data",
        ])

        layout.addWidget(tabs)

        settings_box = QFrame()

        settings_layout = QVBoxLayout(settings_box)

        settings_layout.addWidget(
            QCheckBox(
                "Start application with Assistant Hub"
            )
        )

        settings_layout.addWidget(
            QCheckBox(
                "Show Local AI status"
            )
        )

        settings_layout.addWidget(
            QCheckBox(
                "Enable Memory"
            )
        )

        settings_layout.addWidget(
            QCheckBox(
                "Store conversations locally"
            )
        )

        settings_layout.addStretch()

        layout.addWidget(settings_box)

        layout.addStretch()


# ============================================================
# MAIN WINDOW
# ============================================================

class MainWindow(QMainWindow):

    def __init__(self):

        super().__init__()

        self.assistant_name = "Your Assistant"

        self.setWindowTitle(
            "Offline AI Assistant — Workspace Preview"
        )

        self.resize(
            1500,
            900,
        )

        self.sidebar_visible = True
        self.context_visible = True

        self.build_ui()

    # --------------------------------------------------------
    # BUILD UI
    # --------------------------------------------------------

    def build_ui(self):

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # TOP BAR
        topbar = QFrame()
        topbar.setObjectName("topbar")

        top_layout = QHBoxLayout(topbar)

        menu_button = QToolButton()
        menu_button.setText("☰")
        menu_button.clicked.connect(
            self.toggle_sidebar
        )

        top_layout.addWidget(menu_button)

        self.top_assistant_name = QLabel(
            self.assistant_name
        )

        self.top_assistant_name.setStyleSheet(
            "font-size: 12pt; font-weight: 600;"
        )

        top_layout.addWidget(
            self.top_assistant_name
        )

        top_layout.addStretch()

        local_status = QLabel(
            "● Local"
        )

        local_status.setStyleSheet(
            f"color: {EMERALD}; font-weight: 600;"
        )

        top_layout.addWidget(
            local_status
        )

        context_button = QToolButton()
        context_button.setText("Context")
        context_button.clicked.connect(
            self.toggle_context
        )

        top_layout.addWidget(
            context_button
        )

        settings_button = QToolButton()
        settings_button.setText("⚙")
        settings_button.clicked.connect(
            lambda: self.show_page("Settings")
        )

        top_layout.addWidget(
            settings_button
        )

        root_layout.addWidget(topbar)

        # MAIN AREA
        main_splitter = QSplitter(
            Qt.Horizontal
        )

        # SIDEBAR
        self.sidebar = self.create_sidebar()

        main_splitter.addWidget(
            self.sidebar
        )

        # CENTER
        self.pages = QStackedWidget()

        self.page_map = {}

        pages = [
            ("Home", AssistantHub(self)),
            ("Chat", ChatWorkspace(self)),
            ("Memory", MemoryPage()),
            ("Knowledge", KnowledgePage()),
            ("Capabilities", CapabilitiesPage()),
            ("Projects", ProjectsPage()),
            ("Settings", SettingsPage()),
        ]

        for name, page in pages:

            self.page_map[name] = page
            self.pages.addWidget(page)

        main_splitter.addWidget(
            self.pages
        )

        # CONTEXT PANEL
        self.context_panel = self.create_context_panel()

        main_splitter.addWidget(
            self.context_panel
        )

        main_splitter.setSizes([
            240,
            900,
            280,
        ])

        root_layout.addWidget(
            main_splitter
        )

        self.show_page("Home")

    # --------------------------------------------------------
    # SIDEBAR
    # --------------------------------------------------------

    def create_sidebar(self):

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")

        layout = QVBoxLayout(sidebar)

        layout.setContentsMargins(
            12,
            18,
            12,
            12,
        )

        layout.setSpacing(5)

        assistant_label = QLabel(
            self.assistant_name
        )

        assistant_label.setStyleSheet(
            f"""
            font-size: 13pt;
            font-weight: 600;
            padding: 8px;
            color: {EMERALD};
            """
        )

        layout.addWidget(
            assistant_label
        )

        subtitle = QLabel(
            "Your Personal Assistant"
        )

        subtitle.setStyleSheet(
            f"""
            color: {TEXT_SECONDARY};
            padding-left: 8px;
            padding-bottom: 10px;
            """
        )

        layout.addWidget(
            subtitle
        )

        new_chat = create_nav_button(
            "+  New Conversation"
        )

        new_chat.clicked.connect(
            lambda: self.show_page("Chat")
        )

        layout.addWidget(
            new_chat
        )

        layout.addSpacing(10)

        navigation = [
            ("💬  Chat", "Chat"),
            ("🧠  Memory", "Memory"),
            ("📚  Knowledge", "Knowledge"),
            ("🧩  Capabilities", "Capabilities"),
            ("🗂  Projects", "Projects"),
        ]

        for text, page_name in navigation:

            button = create_nav_button(
                text
            )

            button.clicked.connect(
                lambda checked=False,
                name=page_name:
                self.show_page(name)
            )

            layout.addWidget(
                button
            )

        layout.addStretch()

        profile_button = create_nav_button(
            "👤  My Profile"
        )

        profile_button.clicked.connect(
            self.edit_assistant_name
        )

        layout.addWidget(
            profile_button
        )

        settings_button = create_nav_button(
            "⚙  Settings"
        )

        settings_button.clicked.connect(
            lambda: self.show_page("Settings")
        )

        layout.addWidget(
            settings_button
        )

        return sidebar

    # --------------------------------------------------------
    # CONTEXT PANEL
    # --------------------------------------------------------

    def create_context_panel(self):

        panel = QFrame()
        panel.setObjectName(
            "context_panel"
        )

        layout = QVBoxLayout(panel)

        layout.setContentsMargins(
            18,
            22,
            18,
            18,
        )

        layout.addWidget(
            create_label(
                "Context",
                "section_title",
            )
        )

        layout.addSpacing(15)

        layout.addWidget(
            create_label(
                "Assistant"
            )
        )

        assistant = QLabel(
            f"{self.assistant_name}\n"
            "Balanced · Serbian"
        )

        assistant.setStyleSheet(
            f"color: {TEXT_SECONDARY};"
        )

        layout.addWidget(
            assistant
        )

        layout.addSpacing(15)

        layout.addWidget(
            create_label(
                "AI Model"
            )
        )

        model = QLabel(
            "Qwen 2.5 7B\n● Ready · GPU"
        )

        model.setStyleSheet(
            f"color: {TEXT_SECONDARY};"
        )

        layout.addWidget(
            model
        )

        layout.addSpacing(15)

        layout.addWidget(
            create_label(
                "Capabilities"
            )
        )

        capabilities = QLabel(
            "✓ Text\n"
            "✓ Programming\n"
            "✓ Vision\n"
            "✓ Documents"
        )

        capabilities.setStyleSheet(
            f"color: {TEXT_SECONDARY};"
        )

        layout.addWidget(
            capabilities
        )

        layout.addSpacing(15)

        layout.addWidget(
            create_label(
                "Memory"
            )
        )

        memory = QLabel(
            "3 relevant memories"
        )

        memory.setStyleSheet(
            f"color: {TEXT_SECONDARY};"
        )

        layout.addWidget(
            memory
        )

        layout.addStretch()

        privacy = QLabel(
            "🔒 Local AI\n"
            "Your data is safe here."
        )

        privacy.setStyleSheet(
            f"color: {EMERALD};"
        )

        layout.addWidget(
            privacy
        )

        return panel

    # --------------------------------------------------------
    # PAGE NAVIGATION
    # --------------------------------------------------------

    def show_page(self, page_name):

        if page_name in self.page_map:

            self.pages.setCurrentWidget(
                self.page_map[page_name]
            )

    # --------------------------------------------------------
    # SIDEBAR TOGGLE
    # --------------------------------------------------------

    def toggle_sidebar(self):

        self.sidebar_visible = not self.sidebar_visible

        self.sidebar.setVisible(
            self.sidebar_visible
        )

    # --------------------------------------------------------
    # CONTEXT TOGGLE
    # --------------------------------------------------------

    def toggle_context(self):

        self.context_visible = not self.context_visible

        self.context_panel.setVisible(
            self.context_visible
        )

    # --------------------------------------------------------
    # EDIT ASSISTANT NAME
    # --------------------------------------------------------

    def edit_assistant_name(self):

        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(
            self,
            "Your Assistant",
            "Choose a name for your assistant:",
            QLineEdit.Normal,
            "" if self.assistant_name == "Your Assistant"
            else self.assistant_name,
        )

        if ok and name.strip():

            self.assistant_name = name.strip()

            self.top_assistant_name.setText(
                self.assistant_name
            )

            self.refresh_assistant_pages()

    # --------------------------------------------------------
    # REFRESH ASSISTANT UI
    # --------------------------------------------------------

    def refresh_assistant_pages(self):

        hub = self.page_map.get(
            "Home"
        )

        if hub:

            hub.assistant_name.setText(
                self.assistant_name
            )

        chat = self.page_map.get(
            "Chat"
        )

        if chat:

            # Rebuild title area is unnecessary for this preview.
            # The assistant name will be used in generated messages.
            pass


# ============================================================
# APPLICATION
# ============================================================

def main():

    app = QApplication(
        sys.argv
    )

    app.setApplicationName(
        APP_NAME
    )

    app.setStyleSheet(
        APP_STYLE
    )

    window = MainWindow()

    window.show()

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":
    main()