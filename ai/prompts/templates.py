"""Prompt templates and formatting helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PromptTemplate:
    """A simple string-substitution prompt template."""

    template: str
    defaults: dict[str, Any] = field(default_factory=dict)

    def format(self, **kwargs: Any) -> str:
        values = {**self.defaults, **kwargs}
        return self.template.format(**values)


CHAT_TEMPLATE = PromptTemplate(
    template=(
        "<|im_start|>system\n"
        "{system_prompt}<|im_end|>\n"
        "{history}<|im_end|>\n"
        "<|im_start|>user\n"
        "{user_input}<|im_end|>"
    ),
)

TOOL_USE_TEMPLATE = PromptTemplate(
    template=(
        "Use the following JSON format to call tools:\n"
        '{{\n'
        '  "tool": "{tool_name}",\n'
        '  "parameters": {parameters}\n'
        '}}'
    ),
)


def format_conversation(
    messages: list[dict[str, str]],
    system_prompt: str,
) -> str:
    """Format a list of message dicts into a prompt string."""
    history = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        prefix = "User" if role == "user" else "Assistant"
        history += f"{prefix}: {content}\n"
    return CHAT_TEMPLATE.format(
        system_prompt=system_prompt,
        history=history,
        user_input="",
    )
