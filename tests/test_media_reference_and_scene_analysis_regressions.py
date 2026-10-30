from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_effective_custom_image_route_reuses_legacy_edit_format_when_mapping_omits_it(
    monkeypatch, tmp_path
):
    from novelvideo import model_gateway_settings

    monkeypatch.setattr(model_gateway_settings, "_settings_db_path", lambda: tmp_path / "settings.db")
    model_gateway_settings.save_third_party_gateway_groups(
        [
            {
                "id": "custom-image",
                "name": "Custom image",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {"requestPattern": "gpt-image-2.5", "upstreamModel": "gpt-image-2.5"}
                ],
            }
        ],
        activate=False,
    )
    model_gateway_settings._write_many(
        {
            "sub2api_groups": json.dumps(
                [
                    {
                        "id": "legacy-image",
                        "name": "Legacy image",
                        "protocol": "openai",
                        "baseUrl": "https://image.example/v1",
                        "apiKey": "image-key",
                        "capabilities": ["image"],
                        "modelMappings": [
                            {
                                "requestPattern": "gpt-image-2.5",
                                "upstreamModel": "gpt-image-2.5",
                                "imageEditFormat": "multipart",
                            }
                        ],
                    }
                ]
            )
        }
    )
    model_gateway_settings.set_model_gateway_mode(model_gateway_settings.MODE_CUSTOM)

    effective = model_gateway_settings.get_effective_newapi_config(
        capability="image", model="gpt-image-2.5"
    )

    assert effective.image_edit_reference_format == "multipart"


def test_third_party_image_request_reuses_legacy_format_in_request_schema(
    monkeypatch, tmp_path
):
    from novelvideo import model_gateway_settings

    monkeypatch.setattr(model_gateway_settings, "_settings_db_path", lambda: tmp_path / "settings.db")
    model_gateway_settings.save_third_party_gateway_groups(
        [
            {
                "id": "custom-image",
                "name": "Custom image",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "gpt-image-2.5",
                        "upstreamModel": "gpt-image-2.5-upstream",
                    }
                ],
            }
        ],
        activate=True,
    )
    model_gateway_settings._write_many(
        {
            "sub2api_groups": json.dumps(
                [
                    {
                        "id": "legacy-image",
                        "name": "Legacy image",
                        "protocol": "openai",
                        "baseUrl": "https://image.example/v1",
                        "apiKey": "image-key",
                        "capabilities": ["image"],
                        "modelMappings": [
                            {
                                "requestPattern": "gpt-image-2.5",
                                "upstreamModel": "gpt-image-2.5",
                                "imageEditFormat": "multipart",
                            }
                        ],
                    }
                ]
            )
        }
    )

    resolved = model_gateway_settings.resolve_third_party_image_request("gpt-image-2.5")

    assert resolved is not None
    assert resolved["reference_image_format"] == "multipart"
    assert resolved["request_schema"]["referenceFormat"] == "multipart"


def test_grid_generation_config_injects_canvas_metadata_for_reference_calls(
    monkeypatch,
):
    from novelvideo import config, model_gateway_settings

    monkeypatch.setattr(
        config,
        "_image_provider_config",
        lambda *_args, **_kwargs: {
            "provider": "newapi",
            "api_key": "test-key",
            "model": "gpt-image-2.5",
            "base_url": "https://gateway.example/v1",
            "gateway_source": "third_party",
            "gateway_protocol": "openai",
            "image_edit_reference_format": "images",
        },
    )
    monkeypatch.setattr(
        model_gateway_settings,
        "resolve_third_party_image_request",
        lambda _model: {
            "reference_image_format": "multipart",
            "request_schema": {"endpoint": "images/generations", "referenceFormat": "multipart"},
            "model_params": {"quality": "high"},
            "upstream_model": "gpt-image-2.5-upstream",
            "base_url": "https://gateway.example/v1",
            "api_key": "test-key",
        },
    )

    result = config.get_grid_generation_config(
        provider_override="newapi", model_override="gpt-image-2.5"
    )

    assert result["newapi_request_schema"]["referenceFormat"] == "multipart"
    assert result["newapi_model_params"] == {"quality": "high"}
    assert result["model"] == "gpt-image-2.5-upstream"


def test_grid_generation_config_does_not_apply_inactive_custom_metadata(
    monkeypatch,
):
    from novelvideo import config, model_gateway_settings

    monkeypatch.setattr(
        config,
        "_image_provider_config",
        lambda *_args, **_kwargs: {
            "provider": "newapi",
            "api_key": "official-key",
            "model": "official-image-model",
            "base_url": "https://official.example/v1",
            "gateway_source": "official",
            "gateway_protocol": "openai",
            "image_edit_reference_format": "images",
        },
    )
    monkeypatch.setattr(
        model_gateway_settings,
        "resolve_third_party_image_request",
        lambda _model: {
            "request_schema": {"referenceFormat": "multipart"},
            "model_params": {"quality": "high"},
            "upstream_model": "inactive-custom-model",
            "base_url": "https://inactive.example/v1",
            "api_key": "inactive-key",
        },
    )

    result = config.get_grid_generation_config(
        provider_override="newapi", model_override="official-image-model"
    )

    assert result["api_key"] == "official-key"
    assert result["base_url"] == "https://official.example/v1"
    assert result["model"] == "official-image-model"
    assert "newapi_request_schema" not in result


def test_image_request_metadata_resolves_from_upstream_model_alias(
    monkeypatch, tmp_path
):
    from novelvideo import model_gateway_settings

    monkeypatch.setattr(model_gateway_settings, "_settings_db_path", lambda: tmp_path / "settings.db")
    model_gateway_settings.save_third_party_gateway_groups(
        [
            {
                "id": "custom-image",
                "name": "Custom image",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "gpt-image-2.5",
                        "upstreamModel": "gpt-image-2.5-upstream",
                        "imageEditFormat": "multipart",
                    }
                ],
            }
        ],
        activate=True,
    )

    resolved = model_gateway_settings.resolve_third_party_image_request(
        "gpt-image-2.5-upstream"
    )

    assert resolved is not None
    assert resolved["upstream_model"] == "gpt-image-2.5-upstream"


@pytest.mark.asyncio
async def test_freezone_gen_preserves_shared_image_metadata_without_overrides(
    monkeypatch, tmp_path
):
    from novelvideo import config
    from novelvideo.freezone import jobs
    from novelvideo.generators import nanobanana_grid

    captured = {}
    monkeypatch.setattr(
        config,
        "get_grid_generation_config",
        lambda **_kwargs: {
            "provider": "newapi",
            "model": "gpt-image-2.5-upstream",
            "api_key": "test-key",
            "base_url": "https://gateway.example/v1",
            "newapi_request_schema": {
                "endpoint": "images/edits",
                "referenceFormat": "multipart",
            },
            "newapi_model_params": {"quality": "high"},
        },
    )

    async def fake_generate_reference_edit_image(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"image")
        return kwargs["output_path"]

    monkeypatch.setattr(
        nanobanana_grid,
        "generate_reference_edit_image",
        fake_generate_reference_edit_image,
    )

    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    await jobs.run_freezone_gen(
        project_dir=tmp_path,
        job_id="shared-metadata",
        prompt="generate",
        reference_paths=[str(reference)],
    )

    assert captured["config"]["newapi_request_schema"]["referenceFormat"] == "multipart"
    assert captured["config"]["newapi_model_params"] == {"quality": "high"}


@pytest.mark.asyncio
async def test_freezone_gen_applies_catalog_metadata_when_default_provider_is_not_newapi(
    monkeypatch, tmp_path
):
    from novelvideo import config
    from novelvideo.freezone import jobs
    from novelvideo.generators import nanobanana_grid

    captured = {}
    monkeypatch.setattr(
        config,
        "get_grid_generation_config",
        lambda **_kwargs: {
            "provider": "openrouter",
            "model": "gpt-image-2.5",
            "api_key": "test-key",
        },
    )
    monkeypatch.setattr(
        "novelvideo.model_gateway_settings.resolve_third_party_image_request",
        lambda _model: {
            "reference_image_format": "multipart",
            "request_schema": {
                "endpoint": "images/generations",
                "referenceFormat": "multipart",
            },
            "model_params": {"quality": "high"},
            "upstream_model": "gpt-image-2.5-upstream",
            "base_url": "https://gateway.example/v1",
            "api_key": "catalog-key",
        },
    )

    async def fake_generate_reference_edit_image(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"image")
        return kwargs["output_path"]

    monkeypatch.setattr(
        nanobanana_grid,
        "generate_reference_edit_image",
        fake_generate_reference_edit_image,
    )
    reference = tmp_path / "catalog-reference.png"
    reference.write_bytes(b"reference")

    await jobs.run_freezone_gen(
        project_dir=tmp_path,
        job_id="catalog-metadata",
        prompt="generate",
        reference_paths=[str(reference)],
        model="gpt-image-2.5",
    )

    assert captured["config"]["provider"] == "newapi"
    assert captured["config"]["newapi_request_schema"]["referenceFormat"] == "multipart"
    assert captured["config"]["newapi_model_params"] == {"quality": "high"}
    assert captured["config"]["model"] == "gpt-image-2.5-upstream"


@pytest.mark.asyncio
async def test_freezone_edit_preserves_shared_image_metadata_without_overrides(
    monkeypatch, tmp_path
):
    from novelvideo import config
    from novelvideo.freezone import jobs
    from novelvideo.generators import nanobanana_grid

    captured = {}
    monkeypatch.setattr(
        config,
        "get_grid_generation_config",
        lambda **_kwargs: {
            "provider": "newapi",
            "model": "gpt-image-2.5-upstream",
            "api_key": "test-key",
            "base_url": "https://gateway.example/v1",
            "newapi_request_schema": {
                "endpoint": "images/edits",
                "referenceFormat": "multipart",
            },
            "newapi_model_params": {"quality": "high"},
        },
    )

    async def fake_generate_reference_edit_image(**kwargs):
        captured.update(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"image")
        return kwargs["output_path"]

    monkeypatch.setattr(
        nanobanana_grid,
        "generate_reference_edit_image",
        fake_generate_reference_edit_image,
    )

    base = tmp_path / "base.png"
    base.write_bytes(b"base")
    await jobs.run_freezone_edit(
        project_dir=tmp_path,
        job_id="shared-metadata-edit",
        prompt="edit",
        base_path=str(base),
    )

    assert captured["config"]["newapi_request_schema"]["referenceFormat"] == "multipart"
    assert captured["config"]["newapi_model_params"] == {"quality": "high"}


def test_scene_analysis_timeout_defaults_are_longer_than_legacy_window(monkeypatch):
    from novelvideo.director_world import scene_analysis_gateway

    monkeypatch.delenv("SCENE_ANALYSIS_TIMEOUT_SECONDS", raising=False)

    assert scene_analysis_gateway.scene_analysis_timeout_seconds() >= 300


def test_scene_analysis_timeout_is_configurable(monkeypatch):
    from novelvideo.director_world import scene_analysis_gateway

    monkeypatch.setenv("SCENE_ANALYSIS_TIMEOUT_SECONDS", "420")

    assert scene_analysis_gateway.scene_analysis_timeout_seconds() == 420.0


def test_scene_analysis_subprocess_timeout_defaults_to_ten_minutes(monkeypatch):
    from novelvideo import stage_asset_tasks

    monkeypatch.delenv("SCENE_ANALYSIS_SUBPROCESS_TIMEOUT_SECONDS", raising=False)

    assert stage_asset_tasks._scene_analysis_subprocess_timeout() == 600


@pytest.mark.asyncio
async def test_scene_analysis_passes_configured_timeout_to_model(monkeypatch, tmp_path):
    import httpx
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    from novelvideo import config
    from novelvideo.director_world import scene_spatial_contract

    image = tmp_path / "sheet.jpg"
    image.write_bytes(b"reference")
    requests = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: requests.append(request)
            or httpx.Response(
                200,
                json={
                    "id": "scene-analysis",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "DC-scene-spatial-contract-LLM",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": '{"ok":true}',
                            },
                        }
                    ],
                },
            )
        )
    ) as client:
        calls = []

        def gateway_model(env, default_model, **kwargs):
            calls.append(kwargs)
            return OpenAIChatModel(
                default_model,
                provider=OpenAIProvider(
                    base_url="https://gateway.invalid/v1",
                    api_key="test-key",
                    http_client=client,
                ),
            )

        monkeypatch.setenv("SCENE_ANALYSIS_TIMEOUT_SECONDS", "420")
        monkeypatch.setattr(config, "get_newapi_text_pydantic_model", gateway_model)
        await scene_spatial_contract.ask_gateway(
            image_path=image,
            prompt="Analyze references",
            max_tokens=100,
        )

    assert calls[0]["timeout_seconds_override"] == 420.0
    assert len(requests) == 1
