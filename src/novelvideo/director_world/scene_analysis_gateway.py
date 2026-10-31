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


def scene_analysis_timeout_seconds() -> float:
    """Return the bounded timeout for one gateway vision-analysis call."""
    raw = str(os.environ.get("SCENE_ANALYSIS_TIMEOUT_SECONDS") or "300").strip()
    try:
        return max(float(raw), 30.0)
    except ValueError:
        return 300.0


def _scene_reference_media_type(image_path: Path) -> str:
    """Return the real MIME type for a scene reference sent to vision models."""
    media_type, _ = mimetypes.guess_type(str(image_path))
    return media_type if media_type in {"image/jpeg", "image/png", "image/webp"} else "image/jpeg"


def resolve_scene_analysis_model(
    model_env: str, default_model: str, model: str = ""
) -> str:
    from novelvideo import model_gateway_settings
    explicit_model = str(model or "").strip()
    env_model = str(os.environ.get(model_env) or "").strip()
    # stage_asset_tasks passes the business alias as the child-process default.
    # That is not a scene-specific override: analysis must inherit the unified
    # text capability selected in Settings unless the operator explicitly sets
    # a scene-analysis model or CLI override.
    if explicit_model and explicit_model != default_model:
        return explicit_model
    if env_model:
        return env_model

    settings = model_gateway_settings.get_model_gateway_settings()
    gateway_mode = model_gateway_settings.normalize_gateway_mode(
        settings.get("model_gateway_mode")
    )
    if gateway_mode not in {
        model_gateway_settings.MODE_CUSTOM,
        model_gateway_settings.MODE_HYBRID,
    }:
        from novelvideo.config import get_effective_newapi_text_model_name

        return get_effective_newapi_text_model_name(model_env, default_model)

    text_defaults = model_gateway_settings.get_capability_defaults()
    if not text_defaults.get("textGroupId") or not text_defaults.get("textModel"):
        raise ValueError(
            "No unified text model is configured for scene analysis; select a text model in Settings"
        )
    capability_default = model_gateway_settings.resolve_capability_default(
        model_gateway_settings.CAPABILITY_TEXT
    )
    if capability_default is not None and capability_default.model:
        groups = model_gateway_settings.get_third_party_gateway_groups()
        group = next(
            (
                item
                for item in groups
                if str(item.get("id") or "") == capability_default.group_id
            ),
            None,
        )
        if group is not None:
            mapping = next(
                (
                    item
                    for item in group.get("modelMappings", [])
                    if str(item.get("upstreamModel") or "").strip()
                    == capability_default.model
                    and not str(item.get("requestPattern") or "").strip().endswith("*")
                ),
                None,
            )
            if mapping is not None and str(mapping.get("requestPattern") or "").strip():
                return str(mapping["requestPattern"]).strip()
        return capability_default.model

    raise ValueError(
        "No unified text model is configured for scene analysis; select a text model in Settings"
    )



def scene_analysis_gateway_configured() -> bool:
    """Check that a configured scene-analysis route can reach its gateway."""
    from novelvideo.config import get_newapi_runtime_credentials
    from novelvideo.model_gateway_settings import get_effective_llm_config

    for model_env, default_model in (
        (OVERLAP_MODEL_ENV, OVERLAP_MODEL),
        (SPATIAL_MODEL_ENV, SPATIAL_MODEL),
    ):
        try:
            model = resolve_scene_analysis_model(model_env, default_model)
            llm_config = get_effective_llm_config(model=model)
            api_key, base_url = get_newapi_runtime_credentials(
                api_key_override=llm_config.api_key,
                base_url_override=llm_config.base_url,
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
    timeout_seconds: float | None = None,
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
    timeout_seconds = timeout_seconds or scene_analysis_timeout_seconds()
    resolved_model = resolve_scene_analysis_model(
        model_env, default_model, model=model or ""
    )
    transport = get_newapi_text_pydantic_model(
        model_env,
        default_model,
        model_name_override=resolved_model,
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
            **get_newapi_structured_output_model_settings(model=resolved_model),
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
