"""Regression tests for cancelled-generation partial-response preservation (A2).

Locks the contract: when a generation is cancelled mid-stream, whatever
partial text was already streamed is preserved in the conversation history
(memory), explicitly marked as cancelled — while AI_RESPONSE_RECEIVED is NOT
published (a cancelled turn must not be presented or duplicated as a normal
completed assistant answer).

Both UI paths (ChatVoiceCoordinator for AppShell, MainWindow legacy workers)
run Assistant.process_message, so the backend contract below covers both.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.assistant import Assistant


# --------------------------------------------------------------------------- #
# Fake collaborators
# --------------------------------------------------------------------------- #
class FakeMemory:
    """Records user/assistant message writes."""

    def __init__(self) -> None:
        self.user_messages: list[str] = []
        self.assistant_messages: list[str] = []
        self.conversation_id: int | None = None

    def add_user_message(self, text: str) -> None:
        self.user_messages.append(text)

    def add_assistant_message(self, text: str) -> None:
        self.assistant_messages.append(text)

    def get_history(self) -> list[dict[str, str]]:
        return []

    def build_context(self, user_input: str, max_memories: int = 5) -> dict:  # noqa: ARG002
        return {"history": [], "relevant_memories": []}


class FakeEventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict | None]] = []

    def publish(self, event_type: str, data: dict | None = None) -> None:
        self.events.append((event_type, data))


class StubEngine:
    """Streams tokens until the cancel event fires."""

    model_name = "stub"
    is_ready = True
    load_status = ""
    supports_tool_calling = False

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens

    def generate_chat_stream(self, messages, config=None):  # noqa: ARG002
        for token in self._tokens:
            yield token

    def count_tokens(self, messages) -> int:  # noqa: ARG002
        return 0


def _make_assistant(memory: FakeMemory, bus: FakeEventBus,
                    tokens: list[str]) -> Assistant:
    engine = StubEngine(tokens)
    assistant = Assistant.__new__(Assistant)  # bypass heavy __init__
    # Minimal attribute surface used by process_message
    assistant._memory = memory
    assistant.event_bus = bus
    assistant._engine = engine
    assistant._tools = None
    assistant._rag_pipeline = None
    assistant._cancel_event = None
    assistant._pending_memory = None
    assistant._plugin_manager = None
    assistant._workspace_manager = None
    assistant._project_manager = None
    assistant._agent_repository = None
    assistant._context_manager = None
    assistant._active_project_id = None
    assistant._orchestrator = None
    assistant._planner = None
    assistant._automation = None
    from core.config_manager import ConfigManager
    import tempfile
    assistant.config = ConfigManager(
        settings_path=Path(tempfile.mkdtemp()) / "settings.json"
    )
    assistant._profile = {
        "identity": {"name": "Assistant", "description": ""},
        "personality": {},
        "communication": {},
        "expertise": {},
        "behavior": {},
        "boundaries": {},
    }
    assistant._active_workspace_id = None
    return assistant


# --------------------------------------------------------------------------- #
# Cancel mid-stream preserves the partial response in history
# --------------------------------------------------------------------------- #
class TestCancelPreservesPartialResponse:
    def test_cancelled_partial_text_is_saved_to_memory_marked(self) -> None:
        """Partial streamed text must land in the conversation history."""
        memory, bus = FakeMemory(), FakeEventBus()
        # The engine streams 10 tokens; the caller cancels after the 4th.
        tokens = [f"tok{i} " for i in range(10)]
        assistant = _make_assistant(memory, bus, tokens)
        cancel_event = threading.Event()
        seen: list[str] = []

        def token_callback(token: str) -> None:
            seen.append(token)
            if len(seen) == 4:
                cancel_event.set()  # cancel mid-stream

        response = assistant.process_message(
            "tell me a story",
            cancel_event=cancel_event,
            token_callback=token_callback,
        )

        # The partial text is returned (existing contract).
        assert response.strip() == "tok0 tok1 tok2 tok3".strip()
        # ...and is now ALSO preserved in history with the cancellation marker.
        assert len(memory.assistant_messages) == 1
        saved = memory.assistant_messages[0]
        assert "tok0 tok1 tok2 tok3" in saved
        assert "generation cancelled" in saved  # explicit marker

    def test_ai_response_received_not_published_on_cancel(self) -> None:
        """A cancelled turn must not be announced as a normal response."""
        memory, bus = FakeMemory(), FakeEventBus()
        tokens = ["partial ", "answer ", "more ", "text "]
        assistant = _make_assistant(memory, bus, tokens)
        cancel_event = threading.Event()

        def cancel_after_two(token: str) -> None:
            if token == "answer ":  # unique marker for the 2nd token
                cancel_event.set()

        assistant.process_message(
            "hi", cancel_event=cancel_event, token_callback=cancel_after_two
        )

        published = [e for e, _ in bus.events]
        assert "AI_RESPONSE_RECEIVED" not in published
        assert "GENERATION_CANCELLED" in published
        # The partial text was preserved with the cancellation marker.
        assert ("MEMORY_UPDATED", {"type": "assistant_message_cancelled"}) in [
            (e, d) for e, d in bus.events
        ]
        assert any("generation cancelled" in m for m in memory.assistant_messages)

    def test_cancel_before_any_token_saves_nothing(self) -> None:
        """Cancel at the very first boundary → empty partial → no history write."""
        memory, bus = FakeMemory(), FakeEventBus()
        assistant = _make_assistant(memory, bus, ["x "])
        cancel_event = threading.Event()
        cancel_event.set()  # already set before generation starts

        assistant.process_message("hi", cancel_event=cancel_event)

        published = [e for e, _ in bus.events]
        assert "AI_RESPONSE_RECEIVED" not in published
        assert memory.assistant_messages == []  # nothing worth saving
        assert ("MEMORY_UPDATED", {"type": "assistant_message_cancelled"}) not in [
            (e, d) for e, d in bus.events
        ]

    def test_normal_completion_unchanged(self) -> None:
        """Non-cancelled generations keep the existing behaviour exactly."""
        memory, bus = FakeMemory(), FakeEventBus()
        assistant = _make_assistant(memory, bus, ["full ", "response "])

        response = assistant.process_message("hello")

        assert response.strip() == "full response".strip()
        assert len(memory.assistant_messages) == 1
        assert memory.assistant_messages[0].strip() == "full response"
        published = [e for e, _ in bus.events]
        assert "AI_RESPONSE_RECEIVED" in published
        assert ("MEMORY_UPDATED", {"type": "assistant_message"}) in [
            (e, d) for e, d in bus.events
        ]

    def test_user_message_still_recorded_on_cancel(self) -> None:
        """The user's question stays in history even when the answer is cancelled."""
        memory, bus = FakeMemory(), FakeEventBus()
        assistant = _make_assistant(memory, bus, ["t "])
        cancel_event = threading.Event()
        cancel_event.set()

        assistant.process_message("important question", cancel_event=cancel_event)

        assert memory.user_messages == ["important question"]
