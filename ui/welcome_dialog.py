"""Welcome / First Run dialog — introduces the offline assistant to new users."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ai.models.model_loader import ModelCapabilities, ModelStatus
from ui.translations import Language, TranslationManager, tr


class WelcomeDialog(QDialog):
    """First-run welcome experience showing offline/local info, model, and profile."""

    def __init__(
        self,
        model_name: str = "N/A",
        model_capabilities: ModelCapabilities | None = None,
        model_status: ModelStatus | None = None,
        parent: QWidget | None = None,
        language: Language | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("welcome_title"))
        self.setModal(True)
        self.setMinimumWidth(480)
        self.setMinimumHeight(400)

        self._model_name = model_name
        self._model_capabilities = model_capabilities or ModelCapabilities()
        self._model_status = model_status
        self._language = language or TranslationManager.get_language()

        self._build_ui()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)

        # Title
        title = QLabel("<h2>Vaš lokalni AI asistent</h2>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)

        # Offline/Local explanation
        offline_group = self._build_offline_section()
        main_layout.addWidget(offline_group)

        # Model information
        model_group = self._build_model_section()
        main_layout.addWidget(model_group)

        # Profile introduction
        profile_section = self._build_profile_section()
        main_layout.addWidget(profile_section)

        # Add spacer
        main_layout.addStretch()

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(self.accept)
        main_layout.addWidget(button_box)

    def _build_offline_section(self) -> QLabel:
        container = QLabel()
        container.setWordWrap(True)
        
        if self._language == Language.ENGLISH:
            container.setText("""
<b>Your assistant is 100% offline and local.</b>

• Your data and conversations stay on this computer
• No mandatory internet required
• AI model runs directly on your device
• All settings are saved locally in settings.json""")
        else:
            container.setText("""
<b>Vaš asistent je 100% offline / lokalan.</b>

• Vaši podaci i konverzacije ostaju na vašem računaru
• Nema obaveznih internetskih poslova
• AI model radi direktno na vašem uređaju
• Sve konfiguracije se čuvaju lokalno u settings.json fajlu""")
        return container

    def _build_model_section(self) -> QLabel:
        container = QLabel()
        container.setWordWrap(True)

        if self._model_status == ModelStatus.MODEL_AVAILABLE:
            caps = self._model_capabilities
            if self._language == Language.ENGLISH:
                cap_list = []
                if caps.text_generation:
                    cap_list.append(" text generation")
                if caps.streaming:
                    cap_list.append(" streaming")
                if caps.reasoning:
                    cap_list.append(" reasoning")
                if caps.code_generation:
                    cap_list.append(" code generation")
                caps_text = ",".join(cap_list) if cap_list else " basic"
                container.setText(f"""
<b>Active model:</b> {self._model_name}

 Capabilities{caps_text}: full and reliable offline responses.
""")
            else:
                cap_list = []
                if caps.text_generation:
                    cap_list.append(" tekstgenerator")
                if caps.streaming:
                    cap_list.append(" streaming")
                if caps.reasoning:
                    cap_list.append(" razumevanje")
                if caps.code_generation:
                    cap_list.append(" generisanje koda")
                caps_text = ",".join(cap_list) if cap_list else " osnovne"
                container.setText(f"""
<b>Aktivni model:</b> {self._model_name}

Kapaciteti{caps_text}: polni i pouzdani offline odgovori.
""")
        elif self._model_status == ModelStatus.NO_MODEL_AVAILABLE:
            if self._language == Language.ENGLISH:
                container.setText("""
<b>Active model:</b> (no model loaded)

Download a .gguf model to the models\\llm folder to get real AI responses.
""")
            else:
                container.setText("""
<b>Aktivni model:</b> (nema učitanog modela)

Prenesite .gguf model u folder \\models\\llm\\ da biste dobili pravi AI odgovor.
""")
        else:
            if self._language == Language.ENGLISH:
                container.setText("""
<b>Active mode:</b> Limited (stub active)

Your application is running with stub mode until you add an AI model.
Conversations will be limited to placeholder responses.

Download a .gguf model to the models\\llm folder to get
real AI responses with contextual memory.
""")
            else:
                container.setText("""
<b>Aktivni režim:</b> Ograničen (stub aktivan)

Vaša aplikacija radi uz stub zamenu dok ne postavite AI model.
Konverzacije će biti ograničene na placeholder odgovore.

Prenesite .gguf model u folder \\models\\llm\\ da biste dobili
pravi AI odgovor sa kontekstualnim pamćenjem.
""")
        return container

    def _build_profile_section(self) -> QTextEdit:
        container = QTextEdit()
        container.setReadOnly(True)
        container.setMaximumHeight(120)

        if self._language == Language.ENGLISH:
            container.setText("""
<b>Assistant Profile — "Your assistant. Your way."</b>

Click the ⚙ icon in the top right corner to:
• Change the assistant name
• Set personality and communication style
• Define expertise areas
• Set boundaries

Your profile controls how the assistant responds to your queries.""")
        else:
            container.setText("""
<b>Profil asistenta — "Vaš asistent. Vaš način."</b>

Kliknite na ikonu ⚙ u gornjem desnom uglu da biste:
• Promenili ime asistenta
• Postavili ličnost i stil komunikacije
• Definisli oblasti struna
• Postavili kutije i granice

Vaš profil kontrola kako asistent odgovara na vaše upite.""")
        return container