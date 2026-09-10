from __future__ import annotations

import base64


def test_vision_messages_use_image_parts_and_preserve_data_uri() -> None:
    from ai.engine.llm_engine import _extract_vision_messages

    encoded = base64.b64encode(b"png-bytes").decode("ascii")
    messages = _extract_vision_messages([{
        "role": "user",
        "content": "What is in this image?",
        "images": [f"data:image/jpeg;base64,{encoded}"],
    }])

    parts = messages[0]["content"]
    assert parts[0] == {"type": "text", "text": "What is in this image?"}
    assert parts[1] == {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }
    assert encoded not in parts[0]["text"]


def test_raw_image_bytes_are_base64_encoded_as_image_parts() -> None:
    from ai.engine.llm_engine import _extract_vision_messages

    messages = _extract_vision_messages([{
        "role": "user",
        "content": "Describe it",
        "images": [b"raw-image-bytes"],
    }])

    image_url = messages[0]["content"][1]["image_url"]["url"]
    assert image_url == (
        "data:image/png;base64,"
        + base64.b64encode(b"raw-image-bytes").decode("ascii")
    )


def test_non_streaming_engine_forwards_multimodal_parts() -> None:
    from ai.engine.llm_engine import LlamaCppEngine

    class FakeLoader:
        is_stub = False

        def __init__(self) -> None:
            self.messages = None

        def generate_chat(self, messages, **kwargs):
            self.messages = messages
            return "ok"

    engine = LlamaCppEngine()
    loader = FakeLoader()
    engine._loader = loader
    encoded = base64.b64encode(b"image").decode("ascii")

    assert engine.generate_chat([
        {"role": "user", "content": "Look", "images": [encoded]},
    ]) == "ok"
    assert loader.messages[0]["content"][1]["type"] == "image_url"
