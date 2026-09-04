"""Custom exceptions for the Offline AI Assistant project."""

from __future__ import annotations


class AssistantError(Exception):
    """Base exception for all OfflineAI errors."""


class ConfigurationError(AssistantError):
    """Raised when configuration is missing or invalid."""


class ModelError(AssistantError):
    """Raised when an AI model fails to load or run."""


class ToolError(AssistantError):
    """Raised when a tool call fails."""


class PermissionError(AssistantError):
    """Raised when a security permission is denied."""

    def __init__(self, permission: str, message: str = "") -> None:
        self.permission = permission
        super().__init__(message or f"Permission denied: {permission}")
