"""Settings UI package — modular settings components.

The main settings module (ui.settings.settings) is re-exported here for
backwards compatibility. New components are in submodules.
"""

# Re-export everything from the main settings module for backwards compatibility
from ui.settings.settings import *  # noqa: F403,F401

# Also re-export profile tabs from the submodule
from ui.settings.profile_tabs import (
    BehaviorTab,
    BoundariesTab,
    CommunicationTab,
    ExpertiseTab,
    PersonalityTab,
    ProfileTab,
)

# Also re-export model/storage tabs from the submodule
from ui.settings.model_storage_tabs import (
    ModelStatusTab,
    StorageTab,
)

# Also re-export logging/language tabs from the submodule
from ui.settings.logging_language_tabs import (
    LoggingTab,
    LanguageTab,
)

# Also re-export plugin tab from the submodule
from ui.settings.plugin_tab import (
    PluginTab,
)

# Also re-export generation/memory tabs from the submodule
from ui.settings.generation_memory_tabs import (
    GenerationSettingsTab,
    MemorySettingsTab,
)

# Also re-export filesystem tab from the submodule
from ui.settings.filesystem_tab import (
    FilesystemSecurityTab,
)

# Also re-export audio tab from the submodule
from ui.settings.audio_tab import (
    _AudioTestWorker,
    AudioSettingsTab,
)

__all__ = [
    # Profile tabs
    "ProfileTab",
    "CommunicationTab",
    "PersonalityTab",
    "ExpertiseTab",
    "BehaviorTab",
    "BoundariesTab",
    # Model/Storage tabs
    "ModelStatusTab",
    "StorageTab",
    # Logging/Language tabs
    "LoggingTab",
    "LanguageTab",
    # Plugin tab
    "PluginTab",
    # Generation/Memory tabs
    "GenerationSettingsTab",
    "MemorySettingsTab",
    # Filesystem tab
    "FilesystemSecurityTab",
    # Audio tab
    "_AudioTestWorker",
    "AudioSettingsTab",
]