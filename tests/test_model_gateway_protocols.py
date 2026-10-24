from __future__ import annotations

from novelvideo.model_gateway_protocols import (
    anthropic_request_headers,
    extract_model_names,
    normalize_gateway_protocol,
    normalize_protocol_base_url,
)


def test_anthropic_protocol_uses_native_base_url_and_headers() -> None:
    assert normalize_gateway_protocol("claude") == "anthropic"
    assert normalize_protocol_base_url("anthropic", "https://api.anthropic.com") == "https://api.anthropic.com/v1"
    assert anthropic_request_headers("sk-ant-test") == {
        "x-api-key": "sk-ant-test",
        "anthropic-version": "2023-06-01",
    }


def test_anthropic_model_catalog_extracts_names() -> None:
    payload = {
        "data": [
            {"id": "claude-sonnet-5-5"},
            {"id": "claude-opus-5-5"},
            {"id": "claude-sonnet-5-5"},
        ]
    }

    assert extract_model_names("anthropic", payload) == [
        "claude-sonnet-5-5",
        "claude-opus-5-5",
    ]


def test_anthropic_text_factory_constructs_native_messages_model() -> None:
    from pydantic_ai.models.anthropic import AnthropicModel

    from novelvideo.model_gateway_protocols import create_anthropic_text_model

    model = create_anthropic_text_model(
        "claude-sonnet-5-5",
        api_key="sk-ant-test",
        base_url="https://claude.example/v1",
    )

    assert isinstance(model, AnthropicModel)
    assert model.__dict__["_model_name"] == "claude-sonnet-5-5"
    provider = model.__dict__["_provider"]
    assert provider.name == "anthropic"
    assert str(provider.client.base_url).rstrip("/") == "https://claude.example/v1"


def test_anthropic_catalog_rejects_media_capabilities() -> None:
    from novelvideo.model_gateway_protocols import validate_protocol_capabilities

    validate_protocol_capabilities("anthropic", ["text"])
    try:
        validate_protocol_capabilities("anthropic", ["image"])
    except ValueError as exc:
        assert "text" in str(exc)
    else:
        raise AssertionError("Anthropic media capability validation did not fail")


def test_invalid_gateway_protocol_is_rejected() -> None:
    from novelvideo.model_gateway_protocols import validate_gateway_protocol

    try:
        validate_gateway_protocol("not-a-protocol")
    except ValueError as exc:
        assert "unsupported gateway protocol" in str(exc)
    else:
        raise AssertionError("invalid protocol was accepted")
