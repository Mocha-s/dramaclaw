"""Protocol-specific helpers for third-party model gateways."""

from __future__ import annotations

from typing import Any

from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

SUPPORTED_GATEWAY_PROTOCOLS = frozenset({"openai", "gemini", "anthropic"})
ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


def normalize_gateway_protocol(value: str | None) -> str:
    protocol = str(value or "").strip().lower()
    if protocol in {"claude", "anthropic"}:
        return "anthropic"
    if protocol in {"google", "gemini"}:
        return "gemini"
    return "openai"


def normalize_protocol_base_url(protocol: str, value: str | None) -> str:
    base_url = str(value or "").strip().rstrip("/")
    normalized = normalize_gateway_protocol(protocol)
    if normalized == "anthropic":
        if not base_url:
            return ANTHROPIC_DEFAULT_BASE_URL
        return base_url if base_url.endswith("/v1") else f"{base_url}/v1"
    return base_url


def anthropic_request_headers(api_key: str) -> dict[str, str]:
    return {
        "x-api-key": str(api_key or "").strip(),
        "anthropic-version": ANTHROPIC_VERSION,
    }


def model_discovery_request(
    protocol: str,
    base_url: str,
    api_key: str,
) -> tuple[str, dict[str, str], dict[str, str | int]]:
    normalized = normalize_gateway_protocol(protocol)
    endpoint_base = normalize_protocol_base_url(normalized, base_url).rstrip("/")
    if normalized == "anthropic":
        return (
            f"{endpoint_base}/models",
            anthropic_request_headers(api_key),
            {"limit": 1000},
        )
    if normalized == "gemini":
        gemini_base = endpoint_base
        if gemini_base.endswith("/v1beta"):
            native_base = gemini_base
        else:
            native_base = gemini_base[:-3] if gemini_base.endswith("/v1") else gemini_base
            native_base = f"{native_base}/v1beta"
        return (
            f"{native_base}/models",
            {"x-goog-api-key": api_key},
            {"pageSize": 1000},
        )
    endpoint = endpoint_base if endpoint_base.endswith("/models") else f"{endpoint_base}/models"
    return endpoint, {"Authorization": f"Bearer {api_key}"}, {"limit": 1000}


def extract_model_names(protocol: str, payload: dict[str, Any]) -> list[str]:
    normalized = normalize_gateway_protocol(protocol)
    raw_models = payload.get("models") if normalized == "gemini" else payload.get("data")
    if not isinstance(raw_models, list):
        raise ValueError("third-party gateway returned an invalid model list")
    names: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        if not isinstance(item, dict):
            continue
        model = str(
            item.get("baseModelId") or item.get("name") or ""
            if normalized == "gemini"
            else item.get("id") or ""
        ).strip()
        if model.startswith("models/"):
            model = model.removeprefix("models/")
        if not model or len(model) > 255 or model in seen:
            continue
        if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in model):
            continue
        seen.add(model)
        names.append(model)
    return names


def validate_protocol_capabilities(protocol: str, capabilities: list[str]) -> None:
    normalized = normalize_gateway_protocol(protocol)
    if normalized == "anthropic" and any(
        capability != "text" for capability in capabilities
    ):
        raise ValueError("Anthropic protocol currently supports only text capability groups")


def create_anthropic_text_model(
    model_name: str,
    *,
    api_key: str,
    base_url: str,
    profile=None,
):
    """Create a PydanticAI model backed by Anthropic's native Messages API."""
    provider = AnthropicProvider(
        api_key=api_key,
        base_url=normalize_protocol_base_url("anthropic", base_url),
    )
    return AnthropicModel(model_name, provider=provider, profile=profile)
