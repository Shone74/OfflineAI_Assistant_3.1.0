"""Translation infrastructure for UI localization.

The application is English-only.  This module keeps the translation
lookup API for compatibility but serves English strings regardless of
the configured language value.
"""

from __future__ import annotations

from enum import Enum


class Language(Enum):
    """Application language — English only (kept for config compatibility)."""

    ENGLISH = "en"

    @classmethod
    def from_string(cls, value: str) -> Language:
        return cls.ENGLISH


class TranslationManager:
    """Simple translation manager for UI strings (English-only)."""

    _instance: TranslationManager | None = None
    _current_language: Language = Language.ENGLISH

    def __init__(self, language: Language | None = None) -> None:
        if language is not None:
            TranslationManager._current_language = language

    @classmethod
    def get_language(cls) -> Language:
        return cls._current_language

    @classmethod
    def set_language(cls, lang: Language) -> None:
        cls._current_language = Language.ENGLISH

    def tr(self, key: str) -> str:
        """Translate a key to the current language."""
        return TRANSLATIONS.get(self._current_language, {}).get(key, key)


_ENGLISH_STRINGS = {
    "welcome_title": "Welcome — Offline AI Assistant",
    "offline_message": """Your assistant is 100% offline and local.

• Your data and conversations stay on this computer
• No mandatory internet required
• AI model runs directly on your device
• All settings are saved locally in settings.json""",
    "model_available": "Active model: {model}\n\nCapabilities{capabilities}: full and reliable offline responses.",
    "model_available_caps": "text generation, streaming, reasoning, code generation",
    "no_model": "Active model: (no model loaded)\n\nDownload a .gguf model to the models\\llm folder to get real AI responses.",
    "stub_mode": """Active mode: Limited (stub active)

Your application is running with stub mode until you add an AI model.
Conversations will be limited to placeholder responses.

Download a .gguf model to the models\\llm folder to get
real AI responses with contextual memory.""",
    "model_section_title": "AI Model",
    "profile_section_title": "Assistant Profile",
    "profile_intro": """Assistant Profile — "Your assistant. Your way."

Click the ⚙ icon in the top right corner to:
• Change the assistant name
• Set personality and communication style
• Define expertise areas
• Set boundaries

Your profile controls how the assistant responds to your queries.""",
    "dialog_ok": "OK",
    "settings": "Settings",
    "close": "Close",
    "save": "Save",
    "cancel": "Cancel",
    "theme": "Theme",
    "theme_dark": "Dark",
    "theme_light": "Light",
    "theme_cyber": "Cyber",
    "model_title": "AI Model",
    "model_name": "Model name",
    "app_status": "OFFLINE AI ASSISTANT",
    "memory_label": "Memory",
    "agents_label": "Agents",
    "tools_label": "Tools",
    "voice_label": "Voice",
    "home_label": "Home",
    "chat_label": "Chat",
    "send_button": "Send",
    "input_placeholder": "Enter your message...",
    "assistant_prefix": "Assistant",
    "user_prefix": "You",
}

TRANSLATIONS: dict[Language, dict[str, str]] = {
    Language.ENGLISH: _ENGLISH_STRINGS,
}


def tr(key: str, lang: Language | None = None) -> str:
    """Translate a key to the specified or current language."""
    if lang is None:
        lang = TranslationManager.get_language()
    return TRANSLATIONS.get(lang, _ENGLISH_STRINGS).get(key, key)


def format_translation(key: str, **kwargs: str) -> str:
    """Translate and format a key with provided arguments."""
    template = tr(key)
    return template.format(**kwargs)
