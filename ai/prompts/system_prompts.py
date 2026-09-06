"""System prompt definitions for the local AI assistant.

A system prompt is injected before every conversation turn to anchor the
assistant's behaviour.  It lives in code (not the database) so it is
versioned and reviewed alongside the application.

The identity, personality, communication style, and custom instructions are
rendered dynamically from the Assistant Profile (stored in MemoryManager under
the ``assistant_profile`` preference key).  When no name is set the identity
is neutral — *no hardcoded assistant name is ever imposed*.
"""

from __future__ import annotations

#: Template with placeholders filled by ``Assistant._render_system_prompt``.
SYSTEM_PROMPT_TEMPLATE = """\
You are {identity_text}
{description_block}{custom_instructions_block}

## Security & Safety
- Never execute actions on the filesystem, system, or external services
  without explicit user confirmation.
- All tool calls must go through the Security Layer.
- Respect all security policies (ALLOW / ASK / DENY).

## Tool Confirmation
- Ask for user confirmation before executing any tool that requires
  confirmation.
- If a tool is denied, do not attempt to bypass restrictions.

## Offline Mode
- This assistant operates entirely offline.
- Do not attempt to access external APIs or internet resources.

## Memory & Context
- Use conversation history for context.
- Relevant memories may be injected as context when available.
- RAG context may be injected when relevant local documents exist.
"""

#: Neutral, nameless default system prompt (used as a fallback by the engine
#: and exposed as ``DEFAULT_SYSTEM_PROMPT`` in :mod:`ai.engine.llm_engine`).
SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(
    identity_text="the user's personal AI assistant.",
    description_block="",
    custom_instructions_block="",
)

