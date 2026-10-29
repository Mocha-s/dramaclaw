"""Gateway transport shared by the optional panorama reference analyses."""

from __future__ import annotations

import asyncio
import json
import mimetypes
import os
from pathlib import Path

OVERLAP_MODEL_ENV = "SCENE_OVERLAP_ANALYSIS_MODEL"
OVERLAP_MODEL = "DC-scene-overlap-analyzer-LLM"
SPATIAL_MODEL_ENV = "SCENE_SPATIAL_CONTRACT_MODEL"
SPATIAL_MODEL = "DC-scene-spatial-contract-LLM"


def _scene_reference_media_type(image_path: Path) -> str:
    """Return the real MIME type for a scene reference sent to vision models."""
    media_type, _ = mimetypes.guess_type(str(image_path))
    return media_type if media_type in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"


def resolve_scene_analysis_model(
    model_env: str, default_model: str, model: str = ""
) -> str:
    requested = str(model or "").strip() or str(os.environ.get(model_env) or "").strip()
    requested = requested or default_model
    from novelvideo import model_gateway_settings

    settings = model_gateway_settings.get_model_gateway_settings()
    raw_mode = str(settings.get("model_gateway_mode") or "").strip().lower()
    normalized_mode = model_gateway_settings.normalize_gateway_mode(raw_mode)
    if raw_mode == model_gateway_settings.MODE_SUB2API:
        active_groups = model_gateway_settings.get_sub2api_groups()
    elif normalized_mode in {
        model_gateway_settings.MODE_CUSTOM,
        model_gateway_settings.MODE_HYBRID,
    }:
        active_groups = model_gateway_settings.get_third_party_gateway_groups()
    else:
        active_groups = []

    def has_explicit_route(candidate: str) -> bool:
        selected = model_gateway_settings._resolve_sub2api_group(
            capability="text", model=candidate, groups=active_groups
        )
        if selected is None:
            return False
        group, upstream_model, _mapping = selected
        return bool(
            str(group.get("baseUrl") or "").strip()
            and str(group.get("apiKey") or "").strip()
            and str(upstream_model or "").strip()
        )

    if has_explicit_route(requested):
        return requested

    fallback = str(os.environ.get("SCENE_ANALYSIS_FALLBACK_MODEL") or "").strip()
    if fallback and has_explicit_route(fallback):
        return fallback

    raise ValueError(
        "No explicit scene analysis model route; configure the requested alias "
        "or SCENE_ANALYSIS_FALLBACK_MODEL"
    )


def scene_analysis_gateway_configured() -> bool:
    """Check credentials for at least one active scene-analysis route."""
    from novelvideo.config import get_newapi_runtime_credentials
    from novelvideo.model_gateway_settings import get_effective_llm_config

    for model_env, default_model in (
        (OVERLAP_MODEL_ENV, OVERLAP_MODEL),
        (SPATIAL_MODEL_ENV, SPATIAL_MODEL),
    ):
        try:
            model = resolve_scene_analysis_model(model_env, default_model)
            config = get_effective_llm_config(model=model)
            api_key, base_url = get_newapi_runtime_credentials(
                api_key_override=config.api_key,
                base_url_override=config.base_url,
                env_api_key="MODEL_API_KEY",
                env_base_url="MODEL_BASE_URL",
            )
        except (RuntimeError, ValueError):
            continue
        if api_key and base_url:
            return True
    return False


async def analyze_scene_references(
    *,
    image_path: Path,
    prompt: str,
    model_env: str,
    default_model: str,
    model: str | None = None,
    max_tokens: int,
    timeout_seconds: float = 120.0,
) -> str:
    """Send a reference sheet through the edition's configured LLM gateway.

    Organization analysis remains disabled at the panorama runner: these child
    processes do not yet have their own admitted organization operation.
    """
    from pydantic_ai import Agent, BinaryContent, PromptedOutput, StructuredDict

    from novelvideo.brainclaw_contract import BrainClawProfile
    from novelvideo.config import (
        get_newapi_structured_output_model_settings,
        get_newapi_text_pydantic_model,
    )
    from novelvideo.task_backend.subprocesses import require_direct_model_egress_allowed

    require_direct_model_egress_allowed(None)
    transport = get_newapi_text_pydantic_model(
        model_env,
        default_model,
        model_name_override=model or None,
        timeout_seconds_override=timeout_seconds,
        brainclaw_profile=BrainClawProfile.FREEZONE_VISION_ANALYSIS,
        capability="vision.analyze",
    )
    agent = Agent(
        transport,
        output_type=PromptedOutput(
            StructuredDict({"type": "object", "additionalProperties": True}),
            template=False,
        ),
        name="Scene Reference Analyzer",
        model_settings={
            "temperature": 0.0,
            "max_tokens": max_tokens,
            **get_newapi_structured_output_model_settings(),
        },
    )
    result = await asyncio.wait_for(
        agent.run(
            [
                prompt,
                BinaryContent(
                    data=image_path.read_bytes(),
                    media_type=_scene_reference_media_type(image_path),
                ),
            ]
        ),
        timeout=timeout_seconds,
    )
    if not result.output:
        raise RuntimeError("Scene reference analysis returned empty output")
    return json.dumps(result.output, ensure_ascii=False)
