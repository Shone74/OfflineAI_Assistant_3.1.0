from __future__ import annotations


def test_qwen35_and_family_metadata_produce_llm_capabilities() -> None:
    from ai.models.model_loader import infer_capabilities

    capabilities = infer_capabilities(
        "Bonsai-27B",
        architecture="qwen35",
        model_family="prism-ml_Bonsai",
    )

    assert capabilities.text_generation is True
    assert capabilities.streaming is True
    assert capabilities.tool_calling is True
    assert capabilities.function_calling is True


def test_model_capabilities_dictionary_exposes_all_supported_flags() -> None:
    from ai.models.model_loader import ModelCapabilities

    names = ModelCapabilities().to_dict()

    assert {
        "text_generation",
        "streaming",
        "vision",
        "multimodal",
        "tool_calling",
        "function_calling",
        "structured_output",
        "json_output",
        "reasoning",
        "code_generation",
        "embeddings",
        "long_context",
    } == set(names)