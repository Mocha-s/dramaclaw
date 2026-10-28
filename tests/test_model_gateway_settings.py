from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import pytest


import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from novelvideo import config
from novelvideo import model_gateway_settings as gateway_settings
from novelvideo.shared import runtime_env
from novelvideo import model_gateway_settings
from novelvideo import official_media_catalog_remote
from novelvideo.api.routes import freezone as freezone_routes
from novelvideo.api.routes import model_gateway
from novelvideo.official_defaults import OFFICIAL_NEWAPI_BASE_URL
from novelvideo.model_gateway_settings import (
    CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
    EffectiveMediaRelayConfig,
    EffectiveNewApiConfig,
    MODE_CUSTOM,
    MODE_HYBRID,
    MODE_OFFICIAL,
    MODE_SUB2API,
    CAPABILITY_AUDIO,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_TEXT,
    CAPABILITY_VIDEO,
    build_newapi_database_status,
    build_model_gateway_status,
    get_effective_cognee_embedding_config,
    get_effective_media_relay_config,
    get_effective_newapi_config,
    get_ce_media_model_catalog,
    get_sub2api_media_model_catalog,
    get_newapi_embedding_model_config,
    get_official_media_model_catalog,
    get_newapi_media_model_mappings,
    get_newapi_provider_channels,
    normalize_relay_base_url,
    save_official_newapi_key,
    save_platform_gateway_key,
    save_custom_newapi_gateway,
    save_sub2api_gateway,
    save_sub2api_groups,
    save_newapi_embedding_model_config,
    save_newapi_media_model_mappings,
    save_media_relay_config,
    save_newapi_database_config,
    save_newapi_provider_channels,
    set_model_gateway_mode,
)
from novelvideo.model_gateway_runtime import refresh_model_gateway_runtime
from novelvideo.generators.video_generator import (
    NewApiVideoGenerator,
    newapi_video_backend_options,
)


def test_third_party_groups_migrate_sub2api_losslessly_and_normalize_mode(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    legacy = {
        "id": "media",
        "name": "Media gateway",
        "protocol": "openai",
        "baseUrl": "https://gateway.example/v1",
        "apiKey": "sk-secret",
        "capabilities": ["image"],
        "modelMappings": [{"requestPattern": "img", "upstreamModel": "upstream", "imageEditFormat": "multipart"}],
    }
    model_gateway_settings._write_many(
        {"sub2api_groups": json.dumps([legacy]), "model_gateway_mode": MODE_SUB2API}
    )

    groups = gateway_settings.get_third_party_gateway_groups()

    assert groups == [legacy]
    settings = gateway_settings.get_model_gateway_settings()
    assert settings["model_gateway_mode"] == MODE_CUSTOM
    assert settings["sub2api_groups"] == json.dumps([legacy])
    assert gateway_settings.get_third_party_gateway_groups(masked=True)[0]["apiKeyPreview"] == "*********"


def test_legacy_gateway_fixture_migrates_resolves_masks_and_preserves_data(
    monkeypatch, tmp_path
):
    """Exercise the complete CE upgrade path without exposing credentials."""
    _isolate_settings_db(monkeypatch, tmp_path)
    legacy_groups = [
        {
            "id": "portable-text",
            "name": "Portable text",
            "protocol": "openai",
            "baseUrl": "https://portable.example/v1",
            "apiKey": "sk-portable-secret",
            "capabilities": ["text"],
            "modelMappings": [
                {"requestPattern": "logical-text", "upstreamModel": "upstream-text"}
            ],
        },
        {
            "id": "portable-image",
            "name": "Portable image",
            "protocol": "gemini",
            "baseUrl": "https://gemini.example",
            "apiKey": "gemini-secret",
            "capabilities": ["image"],
            "modelMappings": [
                {"requestPattern": "logical-image", "upstreamModel": "gemini-image"}
            ],
        },
    ]
    legacy_admin_channels = [{"provider": "private", "upstreamKey": "admin-secret"}]
    model_gateway_settings._write_many(
        {
            "sub2api_groups": json.dumps(legacy_groups),
            "sub2api_base_url": "http://127.0.0.1:3000/v1",
            "sub2api_api_key_text": "legacy-text-secret",
            "custom_newapi_base_url": "http://127.0.0.1:4000/v1",
            "custom_newapi_api_key": "legacy-local-secret",
            "custom_newapi_provider_channels": json.dumps(legacy_admin_channels),
            "model_gateway_mode": MODE_SUB2API,
        }
    )

    groups = gateway_settings.get_third_party_gateway_groups()
    text = gateway_settings.get_effective_newapi_config(model="logical-text")
    image = gateway_settings.get_effective_newapi_config(
        capability=CAPABILITY_IMAGE, model="logical-image"
    )
    status = gateway_settings.build_model_gateway_status()
    warnings = status["migrationWarnings"]
    saved = gateway_settings.get_model_gateway_settings()

    assert groups == legacy_groups
    assert (text.source, text.api_key, text.model) == (
        "third_party",
        "sk-portable-secret",
        "upstream-text",
    )
    assert (image.source, image.api_key, image.model) == (
        "third_party",
        "gemini-secret",
        "gemini-image",
    )
    rejected = gateway_settings.get_effective_newapi_config(model="unmapped-model")
    assert rejected.source != "third_party"
    assert rejected.base_url == ""
    assert rejected.api_key == ""
    assert saved["model_gateway_mode"] == MODE_CUSTOM
    assert saved["sub2api_groups"] == json.dumps(legacy_groups)
    assert saved["custom_newapi_base_url"] == "http://127.0.0.1:4000/v1"
    assert saved["custom_newapi_api_key"] == "legacy-local-secret"
    assert saved["custom_newapi_provider_channels"] == json.dumps(legacy_admin_channels)
    assert any("local or incomplete" in warning for warning in warnings)
    assert any("not portable" in warning for warning in warnings)
    warnings_text = json.dumps(warnings)
    for secret in (
        "sk-portable-secret",
        "gemini-secret",
        "legacy-text-secret",
        "legacy-local-secret",
        "admin-secret",
    ):
        assert secret not in warnings_text
    masked = gateway_settings.get_third_party_gateway_groups(masked=True)
    assert all("apiKey" not in group for group in masked)
    assert all(
        preview not in {"sk-portable-secret", "gemini-secret"}
        for preview in (group["apiKeyPreview"] for group in masked)
    )
    assert [group["apiKeyPreview"] for group in masked] == [
        "sk-p...cret",
        "gemi...cret",
    ]
    status_groups = status["thirdParty"]["groups"]
    assert all("apiKey" not in group for group in status_groups)
    assert [group["apiKeyPreview"] for group in status_groups] == [
        "sk-p...cret",
        "gemi...cret",
    ]


def test_third_party_migration_is_idempotent_and_canonical_wins(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    canonical = [{"id": "canonical", "name": "Canonical", "protocol": "openai", "baseUrl": "https://one.example/v1", "apiKey": "key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "*", "upstreamModel": "*"}]}]
    model_gateway_settings._write_many({"sub2api_groups": "[]", "third_party_gateway_groups": json.dumps(canonical)})
    assert gateway_settings.get_third_party_gateway_groups() == canonical
    first = gateway_settings.get_model_gateway_settings()
    assert gateway_settings.get_third_party_gateway_groups() == canonical
    assert gateway_settings.get_model_gateway_settings() == first


def test_third_party_save_rejects_malformed_without_partial_write(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({"sub2api_groups": "{malformed"})
    assert gateway_settings.get_third_party_gateway_groups() == []
    settings = gateway_settings.get_model_gateway_settings()
    assert "third_party_gateway_groups" not in settings
    assert "could not be migrated" in settings["third_party_gateway_migration_warnings"]


def test_custom_newapi_external_endpoint_migrates_but_loopback_does_not(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({"custom_newapi_base_url": "https://custom.example/v1", "custom_newapi_api_key": "custom-secret"})
    groups = gateway_settings.get_third_party_gateway_groups()
    assert groups[0]["baseUrl"] == "https://custom.example/v1"
    assert groups[0]["protocol"] == "openai"
    assert groups[0]["apiKey"] == "custom-secret"

    _isolate_settings_db(monkeypatch, tmp_path / "loopback")
    model_gateway_settings._write_many({"custom_newapi_base_url": "http://127.0.0.1:3000/v1", "custom_newapi_api_key": "local-secret"})
    assert gateway_settings.get_third_party_gateway_groups() == []


def test_legacy_custom_save_updates_empty_canonical_groups(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({"third_party_gateway_groups": "[]"})

    save_custom_newapi_gateway(
        base_url="https://legacy-save.example/v1", api_key="saved-secret"
    )

    effective = get_effective_newapi_config(model="some-model")
    assert (effective.source, effective.base_url, effective.api_key) == (
        "third_party", "https://legacy-save.example/v1", "saved-secret"
    )
    assert gateway_settings.get_model_gateway_settings()["custom_newapi_api_key"] == "saved-secret"


def test_malformed_legacy_migration_cannot_resolve_preserved_custom_endpoint(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({
        "sub2api_groups": "{malformed",
        "custom_newapi_base_url": "http://127.0.0.1:4000/v1",
        "custom_newapi_api_key": "local-secret",
        "model_gateway_mode": MODE_CUSTOM,
    })

    effective = get_effective_newapi_config(model="some-model")

    assert effective.base_url == ""
    assert effective.api_key == ""


def test_migration_warning_is_non_secret_and_preserves_newapi_admin_data(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({
        "custom_newapi_base_url": "https://custom.example/v1",
        "custom_newapi_api_key": "custom-secret",
        "custom_newapi_provider_channels": json.dumps([{"provider": "openrouter", "upstreamKey": "provider-secret"}]),
    })
    status = gateway_settings.build_model_gateway_status()
    warnings = status["migrationWarnings"]
    assert warnings and all("secret" not in warning for warning in warnings)
    assert "custom-secret" not in json.dumps(warnings)
    assert "provider-secret" not in json.dumps(warnings)
    assert gateway_settings.get_model_gateway_settings()["custom_newapi_provider_channels"]


def test_malformed_canonical_groups_are_preserved_and_retryable(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    raw = "{not-json"
    model_gateway_settings._write_many({"third_party_gateway_groups": raw, "sub2api_groups": "[]"})

    assert gateway_settings.get_third_party_gateway_groups() == []
    settings = gateway_settings.get_model_gateway_settings()
    assert settings["third_party_gateway_groups"] == raw
    assert "Canonical" in settings["third_party_gateway_migration_warnings"]
    assert gateway_settings.get_model_gateway_settings().get("third_party_gateway_migration_version") != "1"


def test_custom_resolution_uses_canonical_group(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    group = {"id": "canonical", "name": "Canonical", "protocol": "openai", "baseUrl": "https://canonical.example/v1", "apiKey": "canonical-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "logical-model", "upstreamModel": "upstream-model"}]}
    model_gateway_settings._write_many({"third_party_gateway_groups": json.dumps([group]), "model_gateway_mode": MODE_CUSTOM})

    effective = gateway_settings.get_effective_newapi_config(model="logical-model")

    assert effective.source == "third_party"
    assert effective.api_key == "canonical-key"
    assert effective.model == "upstream-model"


def test_hybrid_uses_most_specific_third_party_mapping_then_official(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_platform_gateway_key(api_key="official-key", activate=False)
    groups = [
        {"id": "broad", "name": "Broad", "protocol": "openai", "baseUrl": "https://broad.example/v1", "apiKey": "broad-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "vendor-*", "upstreamModel": "broad-model"}]},
        {"id": "specific", "name": "Specific", "protocol": "openai", "baseUrl": "https://specific.example/v1", "apiKey": "specific-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "vendor-chat-*", "upstreamModel": "specific-model"}]},
    ]
    gateway_settings.save_third_party_gateway_groups(groups)
    set_model_gateway_mode(MODE_HYBRID)

    selected = get_effective_newapi_config(model="vendor-chat-pro")
    fallback = get_effective_newapi_config(model="unmapped-model")

    assert (selected.source, selected.api_key, selected.model) == ("third_party", "specific-key", "specific-model")
    assert (fallback.source, fallback.api_key) == ("hybrid", "official-key")


def test_generic_third_party_config_and_enable_routes_are_available(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setattr(model_gateway, "require_ce_gateway_settings_management", lambda: None)
    monkeypatch.setattr(model_gateway, "_refresh_runtime_after_gateway_write", lambda: {})
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post("/model-gateway/third-party/config", json={"groups": [
        {"id": "g", "name": "Gateway", "protocol": "openai", "baseUrl": "https://gateway.example/v1", "apiKey": "sk-secret-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "*", "upstreamModel": "*"}]}
    ]})

    assert response.status_code == 200
    assert "sk-secret-key" not in response.text
    enabled = client.post("/model-gateway/third-party/enable")
    assert enabled.status_code == 200
    assert enabled.json()["data"]["mode"] == MODE_CUSTOM


def test_legacy_sub2api_mode_resolves_through_canonical_custom_groups(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    group = {"id": "canonical", "name": "Canonical", "protocol": "openai", "baseUrl": "https://canonical.example/v1", "apiKey": "canonical-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "logical-model", "upstreamModel": "upstream-model"}]}
    model_gateway_settings._write_many({"third_party_gateway_groups": json.dumps([group]), "model_gateway_mode": MODE_SUB2API})

    effective = gateway_settings.get_effective_newapi_config(model="logical-model")

    assert effective.mode == MODE_CUSTOM
    assert effective.source == "third_party"
    assert effective.api_key == "canonical-key"


@pytest.mark.parametrize("url", ["http://10.0.0.7:3000/v1", "http://192.168.1.4/v1", "http://[fc00::1]/v1", "http://[::1]/v1"])
def test_custom_migration_rejects_private_or_local_addresses(monkeypatch, tmp_path, url):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({"custom_newapi_base_url": url, "custom_newapi_api_key": "local-key"})

    assert gateway_settings.get_third_party_gateway_groups() == []


def test_hybrid_llm_uses_text_mapping_and_official_fallback(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    group = {"id": "text", "name": "Text", "protocol": "openai", "baseUrl": "https://text.example/v1", "apiKey": "third-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "DC-agent-*", "upstreamModel": "gpt-6"}]}
    model_gateway_settings._write_many({"third_party_gateway_groups": json.dumps([group]), "model_gateway_mode": MODE_HYBRID, "platform_gateway_api_key": "official-key"})

    mapped = gateway_settings.get_effective_llm_config(model="DC-agent-one")
    fallback = gateway_settings.get_effective_llm_config(model="unmapped")

    assert (mapped.source, mapped.api_key, mapped.model, mapped.is_brainclaw) == ("third_party", "third-key", "gpt-6", False)
    assert (fallback.source, fallback.api_key, fallback.is_brainclaw) == ("hybrid", "official-key", True)


def test_exact_mapping_beats_arbitrarily_long_prefix(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model = "a" * 1_000_001
    groups = [
        {"id": "exact", "name": "Exact", "protocol": "openai", "baseUrl": "https://exact.example/v1", "apiKey": "exact-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": model, "upstreamModel": "exact-upstream"}]},
        {"id": "prefix", "name": "Prefix", "protocol": "openai", "baseUrl": "https://prefix.example/v1", "apiKey": "prefix-key", "capabilities": ["text"], "modelMappings": [{"requestPattern": "a" * 1_000_000 + "*", "upstreamModel": "prefix-upstream"}]},
    ]
    gateway_settings.save_third_party_gateway_groups(groups, activate=True)

    effective = gateway_settings.get_effective_newapi_config(model=model)

    assert effective.api_key == "exact-key"


def test_exact_mapping_beats_wildcard_mapping(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    group = {
        "id": "text",
        "name": "Text",
        "protocol": "openai",
        "baseUrl": "https://text.example/v1",
        "apiKey": "text-key",
        "capabilities": ["text"],
        "modelMappings": [
            {"requestPattern": "*", "upstreamModel": "generic-model"},
            {"requestPattern": "DC-freezone-text-writer-LLM", "upstreamModel": "gpt-6.1-sol"},
        ],
    }
    model_gateway_settings._write_many(
        {"third_party_gateway_groups": json.dumps([group]), "model_gateway_mode": MODE_CUSTOM}
    )

    exact = gateway_settings.get_effective_newapi_config(
        model="DC-freezone-text-writer-LLM"
    )
    wildcard = gateway_settings.get_effective_newapi_config(model="DC-hermes-LLM")

    assert exact.model == "gpt-6.1-sol"
    assert wildcard.model == "generic-model"


def test_rewriting_mapping_drops_legacy_image_format_same_endpoint(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(model_gateway.router)
    old = {"id": "image", "name": "Image", "protocol": "openai", "baseUrl": "https://image.example/v1", "apiKey": "secret", "capabilities": ["image"], "modelMappings": [{"requestPattern": "image-model", "upstreamModel": "old", "imageEditFormat": "multipart"}]}
    gateway_settings.save_third_party_gateway_groups([old])

    response = TestClient(app).post("/model-gateway/third-party/config", json={"groups": [{**old, "modelMappings": [{"requestPattern": "image-model", "upstreamModel": "new", "imageEditFormat": "multipart"}]}]})

    assert response.status_code == 200
    saved = gateway_settings.get_third_party_gateway_groups()[0]
    assert "imageEditFormat" not in saved["modelMappings"][0]


@pytest.mark.parametrize("method,path", [
    ("post", "/model-gateway/custom/newapi/init"),
    ("post", "/model-gateway/custom/newapi/provider-channels"),
    ("delete", "/model-gateway/custom/newapi/comfyui"),
    ("get", "/model-gateway/custom/newapi/channel-types"),
    ("post", "/model-gateway/custom/newapi/provider-channel/models"),
    ("post", "/model-gateway/custom/newapi/provider-channel/sync"),
    ("post", "/model-gateway/custom/newapi/channels"),
    ("post", "/model-gateway/custom/newapi/channels/batch"),
    ("post", "/model-gateway/custom/newapi/embedding-model"),
    ("post", "/model-gateway/custom/newapi/media-models"),
])
def test_legacy_newapi_admin_routes_return_410(monkeypatch, tmp_path, method, path):
    _isolate_settings_db(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)
    response = client.post(path, json={}) if method == "post" else getattr(client, method)(path)
    assert response.status_code == 410
    assert "not portable" in response.text.lower()


def test_generic_model_discovery_errors_do_not_name_sub2api(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(model_gateway.router)
    response = TestClient(app).post("/model-gateway/third-party/models", json={"id": "missing", "protocol": "openai", "baseUrl": "https://gateway.example/v1", "apiKey": "key"})
    assert "Sub2API" not in response.text


@respx.mock
def test_anthropic_model_discovery_uses_native_headers(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    route = respx.get("https://api.anthropic.com/v1/models").mock(
        return_value=Response(
            200,
            json={"data": [{"id": "claude-sonnet-5-5"}]},
        )
    )
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/third-party/models",
        json={
            "id": "claude",
            "protocol": "anthropic",
            "baseUrl": "https://api.anthropic.com",
            "apiKey": "sk-ant-test",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["models"] == ["claude-sonnet-5-5"]
    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == "sk-ant-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in request.headers
from novelvideo.newapi_provisioner import (
    _merge_channel_payload,
    AdminToken,
    build_channel_payload,
    ensure_newapi_setup,
    get_provisioner_config,
    list_channel_types,
    NewApiSetupCredentials,
    NewApiProvisionerConfig,
    normalize_admin_base_url,
    open_newapi_db,
    require_provisioner_enabled,
    update_provider_channel_credentials,
    upsert_channel,
)


def test_platform_gateway_defaults_to_owned_endpoint_and_neutral_identity(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_official_newapi_key(api_key="sk-owned-platform", activate=True)

    effective = get_effective_newapi_config(capability=CAPABILITY_TEXT, model="writer")

    assert OFFICIAL_NEWAPI_BASE_URL == "https://api.aigcdo.top/v1"
    assert effective.base_url == "https://api.aigcdo.top/v1"
    assert effective.api_key == "sk-owned-platform"


def test_platform_gateway_does_not_reuse_legacy_official_key(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "official_newapi_api_key": "sk-relayclaw-key",
            "model_gateway_mode": MODE_OFFICIAL,
        }
    )

    effective = get_effective_newapi_config(capability=CAPABILITY_TEXT, model="writer")

    assert effective.base_url == "https://api.aigcdo.top/v1"
    assert effective.api_key == ""


def test_saving_platform_key_retires_legacy_official_key(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {"official_newapi_api_key": "sk-relayclaw-key"}
    )

    save_platform_gateway_key(api_key="sk-platform-key", activate=True)

    settings = model_gateway_settings.get_model_gateway_settings()
    assert settings["platform_gateway_api_key"] == "sk-platform-key"
    assert "official_newapi_api_key" not in settings


def test_sub2api_media_catalog_keeps_custom_logical_names_without_newapi_prefix(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "owned-media",
                "name": "Owned media",
                "protocol": "openai",
                "baseUrl": "https://api.aigcdo.top/v1",
                "apiKey": "sk-owned-media",
                "capabilities": ["image", "video"],
                "modelMappings": [
                    {
                        "requestPattern": "poster-main",
                        "upstreamModel": "gpt-image-2",
                    },
                    {
                        "requestPattern": "trailer-fast",
                        "upstreamModel": "seedance-2.0-fast",
                        "videoEndpoint": "videos",
                    },
                ],
            }
        ],
        activate=True,
    )

    image = get_sub2api_media_model_catalog("image")
    video = get_sub2api_media_model_catalog("video")

    assert image[0]["id"] == "poster-main"
    assert image[0]["apiModel"] == "poster-main"
    assert image[0]["gatewayModel"] == "gpt-image-2"
    video_entry = next(item for item in video if item["id"] == "trailer-fast")
    assert video_entry["apiModel"] == "trailer-fast"
    assert video_entry["gatewayModel"] == "seedance-2.0-fast"


@pytest.mark.parametrize("failures", [1, 3])
def test_settings_initialization_retries_lock_and_closes_connections(
    monkeypatch, tmp_path, failures
):
    import sqlite3
    from novelvideo import model_gateway_settings as settings

    monkeypatch.setattr(settings, "_settings_db_path", lambda: tmp_path / "settings.db")
    configure = settings.configure_sqlite_connection
    connections = []

    def contend_on_journal_mode(conn):
        connections.append(conn)
        if len(connections) <= failures:
            raise sqlite3.OperationalError("database is locked")
        configure(conn)

    monkeypatch.setattr(settings, "configure_sqlite_connection", contend_on_journal_mode)
    if failures == 1:
        assert settings._read_all() == {}
        assert len(connections) == 2
    else:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            settings._read_all()
        assert len(connections) == 3
    for conn in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            conn.execute("SELECT 1")


def _newer_bundled_catalog_version(offset: int = 1) -> str:
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )
    parts = str(bundled["catalogVersion"]).split(".")
    parts[-1] = str(int(parts[-1]) + offset)
    return ".".join(parts)


def test_bundled_catalog_includes_seedance_25_capabilities():
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )

    model = bundled["mediaModels"]["seedance-2.5"]
    assert model["upstreamModel"] == "seedance-2.5"
    assert model["mediaType"] == "video"
    assert model["config"]["supportedModes"] == [
        "text_to_video",
        "image_reference",
        "all_reference",
        "video_edit",
        "first_last_frame",
    ]
    assert model["config"]["referenceImageMax"] == 30
    assert model["config"]["referenceVideoMax"] == 10
    assert model["config"]["referenceAudioMax"] == 10
    assert model["config"]["maxDuration"] == 30
    assert model["config"]["referenceVideoTotalMaxSeconds"] == 30
    assert model["config"]["referenceAudioTotalMaxSeconds"] == 30


def test_generic_comfyui_i2v_defaults_to_widescreen():
    config = model_gateway._default_comfyui_media_model_config("wan-i2v")

    assert config["ratioOptions"][0] == "16:9"


def test_comfyui_channel_update_replaces_removed_workflow_models():
    existing = {
        "id": 9,
        "type": 63,
        "model_mapping": json.dumps({"old-model": "old-model", "kept": "kept"}),
        "models": "old-model,kept",
        "base_url": "http://127.0.0.1:8188",
    }
    incoming = build_channel_payload(
        provider="comfyui",
        channel_type=63,
        upstream_key="",
        model_mapping={"kept": "kept"},
        base_url="http://127.0.0.1:8188",
        other_settings={"comfyui": {"workflow_by_model": {"kept": {"1": {}}}}},
    )

    merged = _merge_channel_payload(existing, incoming)["channel"]

    assert merged["models"] == "kept"
    assert json.loads(merged["model_mapping"]) == {"kept": "kept"}


@respx.mock
def test_list_channel_types_normalizes_newapi_metadata():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    admin = AdminToken(
        admin_user_id=1,
        admin_username="root",
        access_token="admin-secret",
        token_created=False,
    )
    route = respx.get(
        "http://new-api:3000/api/channel/types",
        params={"status": 1},
    ).mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [
                        {
                            "type": 62,
                            "provider": "TokenHub",
                            "name": "TokenHub",
                            "description": "Telecom gateway",
                            "icon": "TokenHub",
                            "default_base_url": "https://aigw.telecomjs.com",
                            "status": 1,
                            "capabilities": ["text", "video"],
                            "requires_base_url": False,
                            "supports_base_url_override": True,
                        }
                    ]
                },
            },
        )
    )

    assert list_channel_types(cfg, admin) == [
        {
            "type": 62,
            "provider": "tokenhub",
            "name": "TokenHub",
            "description": "Telecom gateway",
            "icon": "TokenHub",
            "defaultBaseUrl": "https://aigw.telecomjs.com",
            "status": 1,
            "capabilities": ["text", "video"],
            "requiresBaseUrl": False,
            "supportsBaseUrlOverride": True,
        }
    ]
    assert route.called


def _isolate_settings_db(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setattr(runtime_env, "load_project_dotenv", lambda override=False: None)
    monkeypatch.setenv("ST_EDITION", "ce")
    for key in (
        "ST_CONTROL_PLANE_DSN",
        "MODEL_GATEWAY_MODE",
        "MODEL_GATEWAY_RUNTIME_VERSION",
        "NEWAPI_API_KEY",
        "NEWAPI_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_ce_image_selection_options_and_generation_use_configured_media_groups(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": MODE_CUSTOM,
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "image-gateway",
                        "name": "Image gateway",
                        "protocol": "openai",
                        "baseUrl": "https://images.example/v1",
                        "apiKey": "sk-image",
                        "capabilities": ["image"],
                        "modelMappings": [
                            {
                                "requestPattern": "custom-image-v1",
                                "upstreamModel": "upstream-image-v1",
                            }
                        ],
                    }
                ]
            ),
        }
    )

    options = config.configured_image_generation_selection_options()
    image_config = config.get_grid_generation_config(
        selection_override="custom-image-v1"
    )

    assert options == {"custom-image-v1": "Image gateway · custom-image-v1"}
    assert image_config["provider"] == "newapi"
    assert image_config["api_key"] == "sk-image"
    assert image_config["base_url"] == "https://images.example/v1"
    assert image_config["model"] == "upstream-image-v1"
    assert config.normalize_image_generation_selection("missing") == "custom-image-v1"
    assert config.normalize_character_image_selection("custom-image-v1") == "custom-image-v1"


def test_custom_text_tasks_without_specific_mapping_reuse_text_writer_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": MODE_CUSTOM,
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "gpt-text",
                        "name": "GPT text",
                        "protocol": "openai",
                        "baseUrl": "https://text.example/v1",
                        "apiKey": "sk-text",
                        "capabilities": ["text"],
                        "modelMappings": [
                            {
                                "requestPattern": "DC-freezone-text-writer-LLM",
                                "upstreamModel": "gpt-6.1-sol",
                            }
                        ],
                    },
                    {
                        "id": "claude-text",
                        "name": "Claude text",
                        "protocol": "openai",
                        "baseUrl": "https://claude.example/v1",
                        "apiKey": "sk-claude",
                        "capabilities": ["text"],
                        "modelMappings": [
                            {
                                "requestPattern": "claude-sonnet-5-5",
                                "upstreamModel": "claude-sonnet-5-5",
                            }
                        ],
                    },
                ]
            ),
        }
    )

    llm = gateway_settings.get_effective_llm_config(
        model="DC-literal-beat-meta-LLM"
    )

    assert llm.source == "third_party"
    assert llm.base_url == "https://text.example/v1"
    assert llm.api_key == "sk-text"
    assert llm.model == "gpt-6.1-sol"


def test_capability_default_returns_upstream_model_without_dc_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": MODE_CUSTOM,
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "gpt-text",
                        "name": "GPT text",
                        "protocol": "openai",
                        "baseUrl": "https://text.example/v1",
                        "apiKey": "sk-text",
                        "capabilities": ["text"],
                        "modelMappings": [
                            {
                                "requestPattern": "DC-freezone-text-writer-LLM",
                                "upstreamModel": "gpt-6.1-sol",
                            }
                        ],
                    }
                ]
            ),
        }
    )

    default = gateway_settings.resolve_capability_default("text")

    assert default is not None
    assert default.model == "gpt-6.1-sol"
    assert not default.model.startswith("DC-")
    assert gateway_settings.resolve_capability_default("embedding") is None


def test_capability_defaults_are_persisted_and_select_text_upstream_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": MODE_CUSTOM,
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "one",
                        "name": "One",
                        "protocol": "openai",
                        "baseUrl": "https://one.example/v1",
                        "apiKey": "sk-one",
                        "capabilities": ["text"],
                        "modelMappings": [{"requestPattern": "one", "upstreamModel": "one"}],
                    },
                    {
                        "id": "two",
                        "name": "Two",
                        "protocol": "openai",
                        "baseUrl": "https://two.example/v1",
                        "apiKey": "sk-two",
                        "capabilities": ["text"],
                        "modelMappings": [{"requestPattern": "two", "upstreamModel": "two"}],
                    },
                ]
            ),
        }
    )
    gateway_settings.save_capability_defaults(text_group_id="two", text_model="two")

    assert gateway_settings.get_capability_defaults() == {"textGroupId": "two", "textModel": "two"}
    assert gateway_settings.resolve_capability_default("text").model == "two"


def test_capability_defaults_persist_text_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)

    gateway_settings.save_capability_defaults(text_reasoning_effort="high")

    assert gateway_settings.get_capability_defaults() == {
        "textReasoningEffort": "high"
    }
    assert gateway_settings.get_saved_text_reasoning_effort() == "high"


@pytest.mark.parametrize("value", ["none", "xhigh-ish"])
def test_capability_defaults_reject_invalid_text_reasoning_effort(
    monkeypatch: pytest.MonkeyPatch, tmp_path, value: str
):
    _isolate_settings_db(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="low, medium, high, xhigh, max"):
        gateway_settings.save_capability_defaults(text_reasoning_effort=value)


def test_effective_llm_uses_saved_capability_default_for_unmapped_feature(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    groups = [
        {
            "id": group_id,
            "name": group_id,
            "protocol": "openai",
            "baseUrl": f"https://{group_id}.example/v1",
            "apiKey": f"sk-{group_id}",
            "capabilities": ["text"],
            "modelMappings": [{"requestPattern": model_id, "upstreamModel": upstream}],
        }
        for group_id, model_id, upstream in (
            ("one", "one-alias", "one-upstream"),
            ("two", "two-alias", "two-upstream"),
        )
    ]
    model_gateway_settings._write_many({
        "model_gateway_mode": MODE_CUSTOM,
        "third_party_gateway_groups": json.dumps(groups),
    })
    gateway_settings.save_capability_defaults(text_group_id="two", text_model="two-upstream")

    llm = gateway_settings.get_effective_llm_config(model="DC-episode-prop-planner-LLM")

    assert llm.source == "third_party"
    assert llm.model == "two-upstream"
    assert llm.base_url == "https://two.example/v1"


def test_capability_default_group_id_disambiguates_duplicate_upstream_models(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    groups = [
        {
            "id": group_id,
            "name": group_id,
            "protocol": "openai",
            "baseUrl": f"https://{group_id}.example/v1",
            "apiKey": f"sk-{group_id}",
            "capabilities": ["text"],
            "modelMappings": [{"requestPattern": model_id, "upstreamModel": "same-model"}],
        }
        for group_id, model_id in (("one", "one-alias"), ("two", "two-alias"))
    ]
    model_gateway_settings._write_many(
        {"model_gateway_mode": MODE_CUSTOM, "third_party_gateway_groups": json.dumps(groups)}
    )
    gateway_settings.save_capability_defaults(
        text_group_id="two", text_model="same-model"
    )

    resolved = gateway_settings.resolve_capability_default("text")

    assert resolved.group_id == "two"
    assert resolved.base_url == "https://two.example/v1"


def test_capability_default_falls_back_when_saved_group_disappears(
    monkeypatch: pytest.MonkeyPatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": MODE_CUSTOM,
            "third_party_gateway_groups": json.dumps([
                {
                    "id": "remaining",
                    "name": "Remaining",
                    "protocol": "openai",
                    "baseUrl": "https://remaining.example/v1",
                    "apiKey": "sk-remain",
                    "capabilities": ["text"],
                    "modelMappings": [{"requestPattern": "DC-freezone-text-writer-LLM", "upstreamModel": "remaining-model"}],
                }
            ]),
        }
    )
    model_gateway_settings._write_many(
        {"third_party_capability_defaults": json.dumps({"textGroupId": "removed", "textModel": "old-model"})}
    )

    resolved = gateway_settings.resolve_capability_default("text")

    assert resolved.group_id == "remaining"
    assert resolved.model == "remaining-model"


def test_gateway_status_exposes_saved_capability_defaults(monkeypatch: pytest.MonkeyPatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many({
        "third_party_capability_defaults": json.dumps({
            "textGroupId": "gpt",
            "textModel": "gpt-6.1-sol",
            "embeddingGroupId": "embeddings",
            "embeddingModel": "text-embedding-3-large",
            "textReasoningEffort": "medium",
        })
    })

    status = model_gateway_settings.build_model_gateway_status()

    assert status["capabilityDefaults"] == {
        "textGroupId": "gpt",
        "textModel": "gpt-6.1-sol",
        "embeddingGroupId": "embeddings",
        "embeddingModel": "text-embedding-3-large",
        "textReasoningEffort": "medium",
    }




def test_effective_newapi_config_uses_request_scoped_explicit_config_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _isolate_settings_db(monkeypatch, tmp_path)
    explicit = EffectiveNewApiConfig(
        mode=MODE_OFFICIAL,
        source="request",
        base_url="https://request.example/v1",
        api_key="sk-request-only",
    )
    environment_before = dict(os.environ)
    monkeypatch.setattr(
        model_gateway_settings,
        "_read_all",
        lambda: pytest.fail("explicit config must not read SQLite"),
    )

    result = get_effective_newapi_config(explicit_config=explicit)

    assert result is explicit
    assert dict(os.environ) == environment_before
    assert not (tmp_path / "state").exists()


def test_effective_media_relay_config_uses_request_scoped_explicit_config_without_writes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _isolate_settings_db(monkeypatch, tmp_path)
    explicit = EffectiveMediaRelayConfig(
        source="request",
        provider="aliyun_oss",
        ttl_seconds=60,
        endpoint="https://relay.example",
        bucket="tenant-bucket",
        access_key_id="request-ak",
        access_key_secret="request-sk",
    )
    environment_before = dict(os.environ)
    monkeypatch.setattr(
        model_gateway_settings,
        "_read_all",
        lambda: pytest.fail("explicit config must not read SQLite"),
    )

    result = get_effective_media_relay_config(explicit_config=explicit)

    assert result is explicit
    assert dict(os.environ) == environment_before
    assert not (tmp_path / "state").exists()


@pytest.mark.parametrize(
    ("resolver", "explicit_config"),
    [
        (get_effective_newapi_config, {"api_key": "forged"}),
        (get_effective_media_relay_config, {"access_key_secret": "forged"}),
    ],
)
def test_effective_config_rejects_untyped_explicit_override(
    resolver,
    explicit_config,
) -> None:
    with pytest.raises(TypeError, match="explicit_config"):
        resolver(explicit_config=explicit_config)


def test_comfyui_provider_channel_defaults_to_channel_type_63(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)

    saved = save_newapi_provider_channels(
        [
            {
                "provider": "comfyui",
                "baseUrl": "http://host.docker.internal:8188",
                "settings": {
                    "comfyui": {
                        "workflow_by_model": {
                            "h3-t2v": {
                                "1": {
                                    "class_type": "SaveVideo",
                                    "inputs": {},
                                }
                            }
                        }
                    }
                },
            }
        ]
    )

    assert saved[0]["type"] == 63


@pytest.mark.asyncio
async def test_custom_catalog_disabled_mapping_removes_official_model(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_media_model_mappings(
        {
            "LingShan-G2": {
                "provider": "openrouter",
                "mediaType": "image",
                "enabled": False,
            }
        }
    )
    set_model_gateway_mode(MODE_CUSTOM)

    catalog = await freezone_routes._ee_media_model_catalog("image")

    assert catalog is not None
    assert all(item.get("id") != "LingShan-G2" for item in catalog)


@pytest.mark.asyncio
async def test_custom_catalog_uses_configured_third_party_media_groups_only(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "image-gateway",
                        "name": "Image gateway",
                        "protocol": "openai",
                        "baseUrl": "https://images.example/v1",
                        "apiKey": "sk-image-secret",
                        "capabilities": ["image"],
                        "modelMappings": [
                            {
                                "requestPattern": "gpt-image-2",
                                "upstreamModel": "gpt-image-2",
                            }
                        ],
                    }
                ]
            ),
            "model_gateway_mode": MODE_CUSTOM,
        }
    )

    catalog = await freezone_routes._ee_media_model_catalog("image")

    assert [item["id"] for item in catalog or []] == ["gpt-image-2"]
    assert all(item["id"] != "LingShan-G2" for item in catalog or [])
    assert catalog[0]["gatewayModel"] == "gpt-image-2"


@pytest.mark.asyncio
async def test_official_catalog_is_empty_without_official_key(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    set_model_gateway_mode(MODE_OFFICIAL)

    catalog = await freezone_routes._ee_media_model_catalog("image")

    assert catalog == []


def test_custom_llm_uses_configured_third_party_text_group(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "text-gateway",
                        "name": "Text gateway",
                        "protocol": "openai",
                        "baseUrl": "https://text.example/v1",
                        "apiKey": "sk-text-secret",
                        "capabilities": ["text"],
                        "modelMappings": [
                            {"requestPattern": "*", "upstreamModel": "qwen-max"}
                        ],
                    }
                ]
            ),
            "model_gateway_mode": MODE_CUSTOM,
            "custom_llm_mode": CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
        }
    )

    llm = gateway_settings.get_effective_llm_config(model="DC-codex-agent-LLM")

    assert llm.source == "third_party"
    assert llm.base_url == "https://text.example/v1"
    assert llm.api_key == "sk-text-secret"
    assert llm.model == "qwen-max"
    assert llm.is_brainclaw is False


def test_provider_channel_partial_save_preserves_unmentioned_channels(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_provider_channels(
        [
            {"provider": "openrouter", "upstreamKey": "sk-openrouter-old"},
            {"provider": "volcengine", "upstreamKey": "sk-volcengine-old"},
        ]
    )

    saved = save_newapi_provider_channels(
        [{"provider": "volcengine", "upstreamKey": "sk-volcengine-new"}],
        preserve_unmentioned=True,
    )

    by_provider = {channel["provider"]: channel for channel in saved}
    assert by_provider["openrouter"]["upstreamKey"] == "sk-openrouter-old"
    assert by_provider["volcengine"]["upstreamKey"] == "sk-volcengine-new"






def test_hybrid_mode_uses_official_gateway_by_default(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_custom_newapi_gateway(
        base_url="http://127.0.0.1:3000",
        api_key="sk-custom-secret",
        activate=False,
    )
    save_official_newapi_key(api_key="sk-official-secret", activate=False)
    set_model_gateway_mode(MODE_HYBRID)

    effective = get_effective_newapi_config()
    effective_llm = gateway_settings.get_effective_llm_config()

    assert effective.mode == MODE_HYBRID
    assert effective.source == "hybrid"
    assert effective.api_key == "sk-official-secret"
    assert effective_llm.mode == MODE_HYBRID
    assert effective_llm.source == "hybrid"
    assert effective_llm.api_key == "sk-official-secret"
    assert effective_llm.model == "brainclaw"
    assert effective_llm.is_brainclaw is True




def test_newapi_video_backends_only_include_enabled_comfyui_video_models(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_media_model_mappings(
        {
            "legacy-video": {"provider": "comfyui"},
            "enabled-video": {
                "provider": "comfyui",
                "mediaType": "video",
                "enabled": True,
            },
            "disabled-video": {
                "provider": "comfyui",
                "mediaType": "video",
                "enabled": False,
            },
            "comfy-image": {
                "provider": "comfyui",
                "mediaType": "image",
                "enabled": True,
            },
        }
    )

    options = newapi_video_backend_options()

    assert "legacy-video" in options
    assert "enabled-video" in options
    assert "disabled-video" not in options
    assert "comfy-image" not in options




def test_newapi_runtime_credentials_allow_explicit_override(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_custom_newapi_gateway(
        base_url="http://127.0.0.1:3000",
        api_key="sk-custom-secret",
        activate=True,
    )

    api_key, base_url = config.get_newapi_runtime_credentials(
        api_key_override="sk-request-secret",
        base_url_override="https://request.example/v1",
    )

    assert api_key == "sk-request-secret"
    assert base_url == "https://request.example/v1"




def test_legacy_pydantic_factory_uses_ce_gateway_settings(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("MODEL_API_KEY", "sk-stale-env-secret")
    monkeypatch.setenv("MODEL_BASE_URL", "https://stale-env.example/v1")
    save_custom_newapi_gateway(
        base_url="http://new-api:3000",
        api_key="sk-database-secret",
        activate=True,
    )
    captured: dict[str, object] = {}

    def fake_model(model_name, **kwargs):
        captured.update(model_name=model_name, **kwargs)
        return "newapi-model"

    monkeypatch.setattr(config, "_newapi_text_openai_model", fake_model)

    result = config.get_pydantic_model(
        provider_override="openrouter",
        model_name_override="openrouter/DC-legacy-agent-LLM",
    )

    assert result == "newapi-model"
    assert captured["model_name"] == "DC-legacy-agent-LLM"
    assert captured["api_key"] == "sk-database-secret"
    assert captured["base_url"] == "http://new-api:3000/v1"
    assert captured["timeout_seconds"] == 300.0


def test_legacy_pydantic_factory_uses_ee_deployment_gateway(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://ee-gateway.example/v1")
    monkeypatch.setattr(config, "NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setattr(config, "NEWAPI_BASE_URL", "https://ee-gateway.example/v1")
    captured: dict[str, object] = {}

    class FakeModel:
        async def request(self, *_args):
            return "newapi-response"

    def fake_model(model_name, **kwargs):
        captured.update(model_name=model_name, **kwargs)
        return FakeModel()

    monkeypatch.setattr(config, "_newapi_text_openai_model", fake_model)

    model = config.get_pydantic_model(model_name_override="DC-legacy-agent-LLM")

    assert captured == {}
    result = asyncio.run(model.request([], None, object()))

    assert result == "newapi-response"
    assert captured["model_name"] == "DC-legacy-agent-LLM"
    assert captured["api_key"] == "sk-ee-secret"
    assert captured["base_url"] == "https://ee-gateway.example/v1"


def test_ee_media_model_mappings_do_not_open_ce_settings(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setattr(
        model_gateway_settings,
        "_connect",
        lambda: pytest.fail("EE must not open CE settings.db"),
    )

    assert get_newapi_media_model_mappings() == {}
    assert not (tmp_path / "state").exists()


def test_ee_platform_video_paths_do_not_call_ce_media_model_accessor(
    monkeypatch,
    tmp_path,
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://ee-gateway.example/v1")
    monkeypatch.setattr(config, "NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setattr(config, "NEWAPI_BASE_URL", "https://ee-gateway.example/v1")
    monkeypatch.setattr(
        model_gateway_settings,
        "get_newapi_media_model_mappings",
        lambda: pytest.fail("EE video paths must not call the CE accessor"),
    )

    generator = NewApiVideoGenerator(model="seedance-2.0")
    options = newapi_video_backend_options()

    assert generator.api_key == "sk-ee-secret"
    assert generator.base_url == "https://ee-gateway.example/v1"
    assert "seedance-2.0" in options


def test_ce_video_generator_uses_third_party_video_catalog_schema(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_third_party_gateway_groups = model_gateway_settings.save_third_party_gateway_groups
    save_third_party_gateway_groups(
        [
            {
                "id": "video",
                "name": "Video gateway",
                "protocol": "openai",
                "baseUrl": "https://video.example/v1",
                "apiKey": "video-key",
                "capabilities": ["video"],
                "modelMappings": [
                    {
                        "requestPattern": "seedance-custom",
                        "upstreamModel": "upstream-video",
                        "videoEndpoint": "videos",
                    }
                ],
            }
        ],
        activate=True,
    )

    generator = NewApiVideoGenerator(model="seedance-custom")

    assert generator.api_key == "video-key"
    assert generator.base_url == "https://video.example/v1"
    assert generator.model == "upstream-video"
    assert generator.request_schema["endpoint"] == "videos"


def test_ee_model_gateway_settings_reader_does_not_open_sqlite(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setattr(
        model_gateway_settings,
        "_connect",
        lambda: pytest.fail("EE must not open CE settings.db"),
    )

    assert model_gateway_settings.get_model_gateway_settings() == {
        "model_gateway_mode": MODE_OFFICIAL
    }
    assert not (tmp_path / "state").exists()


def test_cognee_newapi_resolution_prefers_saved_gateway(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.delenv("COGNEE_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("COGNEE_LLM_MODEL", raising=False)
    monkeypatch.delenv("NEWAPI_BASE_URL", raising=False)
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-env-secret")

    save_custom_newapi_gateway(
        base_url="https://custom.example",
        api_key="sk-custom-secret",
        activate=True,
    )

    from novelvideo.cognee import config as cognee_config

    assert cognee_config._resolve_llm_provider() == "newapi"
    assert (
        cognee_config._resolve_llm_api_key("newapi", "openai/DC-model")
        == "sk-custom-secret"
    )
    assert (
        cognee_config._get_endpoint_env("newapi", "COGNEE_LLM_ENDPOINT", "LLM_ENDPOINT")
        == "https://custom.example/v1"
    )


def test_cognee_provider_env_cannot_bypass_newapi(monkeypatch):
    from novelvideo.cognee import config as cognee_config

    monkeypatch.setenv("COGNEE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("COGNEE_LLM_API_KEY", "direct-secret")
    monkeypatch.setattr(
        cognee_config,
        "_effective_newapi_gateway",
        lambda: ("gateway-secret", "https://gateway.example/v1"),
    )

    assert cognee_config._resolve_llm_provider() == "newapi"
    assert (
        cognee_config._resolve_llm_api_key("newapi", "DC-cognee-LLM")
        == "gateway-secret"
    )


def test_cognee_embedding_provider_env_cannot_bypass_newapi(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("COGNEE_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("COGNEE_EMBEDDING_MODEL", "DC-cognee-embedding")

    effective = get_effective_cognee_embedding_config(llm_provider="gemini")

    assert effective.provider == "newapi"
    assert effective.model == "DC-cognee-embedding"


def test_ee_cognee_embedding_ignores_ce_database_config(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_embedding_model_config(
        provider="openai",
        upstream_model="stale-ce-embedding",
        dimension=3072,
    )
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("COGNEE_EMBEDDING_MODEL", "DC-ee-embedding")
    monkeypatch.setenv("COGNEE_EMBEDDING_DIM", "1536")

    effective = get_effective_cognee_embedding_config()

    assert effective.source == "environment"
    assert effective.provider == "newapi"
    assert effective.model == "DC-ee-embedding"
    assert effective.dimensions == "1536"
    assert effective.upstream_model == ""


def test_model_gateway_can_switch_back_to_official(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_official_newapi_key(
        api_key="sk-official-secret",
        activate=True,
    )
    save_custom_newapi_gateway(
        base_url="http://127.0.0.1:3000/v1",
        api_key="sk-custom-secret",
        activate=True,
    )
    set_model_gateway_mode(MODE_OFFICIAL)

    effective = get_effective_newapi_config(
        official_base_url="https://official.example/v1",
        official_api_key="sk-official-secret",
    )
    assert effective.mode == MODE_OFFICIAL
    assert effective.base_url == OFFICIAL_NEWAPI_BASE_URL
    assert effective.api_key == "sk-official-secret"

    status = build_model_gateway_status(
        official_base_url="https://official.example/v1",
        official_api_key="sk-official-secret",
    )
    assert status["custom"]["configured"] is True
    assert status["effective"]["source"] == "official"






def test_sub2api_rejects_endpoint_change_without_all_new_keys(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_gateway(
        base_url="https://old-sub2api.example/v1",
        keys={
            capability: f"sk-{capability}-old"
            for capability in ("text", "embedding", "image", "video", "audio")
        },
        activate=True,
    )
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/sub2api/config",
        json={
            "groups": [
                {
                    "id": "text",
                    "name": "Text",
                    "protocol": "openai",
                    "baseUrl": "https://new-sub2api.example/v1",
                    "capabilities": ["text"],
                    "models": ["*"] ,
                }
            ]
        },
    )

    assert response.status_code == 400
    assert "API Key is required when changing the Base URL" in response.json()["detail"]
    assert get_effective_newapi_config().base_url == "https://old-sub2api.example/v1"


def test_sub2api_rejects_non_http_base_url(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/sub2api/config",
        json={"groups": [{
            "id": "text",
            "name": "Text",
            "protocol": "openai",
            "baseUrl": "file:///tmp/sub2api",
            "apiKey": "sk-text",
            "capabilities": ["text"],
            "models": ["*"] ,
        }]},
    )

    assert response.status_code == 400




def test_sub2api_missing_capability_key_fails_closed(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_gateway(
        base_url="https://sub2api.example/v1",
        keys={CAPABILITY_TEXT: "sk-text-secret"},
        activate=True,
    )

    assert get_effective_newapi_config(capability=CAPABILITY_IMAGE).base_url == ""
    assert get_effective_newapi_config(capability=CAPABILITY_IMAGE).api_key == ""




def test_sub2api_media_mapping_preserves_protocol_metadata(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "media",
                "name": "Media gateway",
                "protocol": "openai",
                "baseUrl": "https://media.example/v1",
                "apiKey": "sk-media",
                "capabilities": ["image", "video"],
                "modelMappings": [
                    {
                        "requestPattern": "gpt-image-2.5",
                        "upstreamModel": "gpt-image-2.5",
                        "imageEditFormat": "input_reference",
                        "videoEndpoint": "video/generations",
                    }
                ],
            }
        ],
        activate=True,
    )

    group = model_gateway_settings.get_sub2api_groups()[0]
    assert group["modelMappings"][0]["imageEditFormat"] == "input_reference"
    assert group["modelMappings"][0]["videoEndpoint"] == "video/generations"


def test_sub2api_media_catalog_defaults_to_verified_protocols_and_sd17_limits(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "media",
                "name": "Media gateway",
                "protocol": "openai",
                "baseUrl": "https://media.example/v1",
                "apiKey": "sk-media",
                "capabilities": ["image", "video"],
                "modelMappings": [
                    {"requestPattern": "gpt-image-2.5", "upstreamModel": "gpt-image-2.5"},
                    {
                        "requestPattern": "sd17-seedance-2.5-2",
                        "upstreamModel": "sd17-seedance-2.5-2",
                    },
                ],
            }
        ],
        activate=True,
    )

    image = next(
        item
        for item in model_gateway_settings.get_sub2api_media_model_catalog("image")
        if item["id"] == "gpt-image-2.5"
    )
    video = next(
        item
        for item in model_gateway_settings.get_sub2api_media_model_catalog("video")
        if item["id"] == "sd17-seedance-2.5-2"
    )

    assert image["request"]["referenceFormat"] == "images"
    assert video["request"]["endpoint"] == "videos"
    assert video["referenceImageMax"] == 30
    assert video["minDuration"] == 10
    assert video["maxDuration"] == 30
    assert video["resolutionOptions"] == ["720p"]


def test_media_model_mapping_preserves_generic_image_capabilities(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_third_party_gateway_groups = model_gateway_settings.save_third_party_gateway_groups
    save_third_party_gateway_groups(
        [
            {
                "id": "generic-image",
                "name": "Generic image gateway",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "custom-image",
                        "upstreamModel": "custom-image-upstream",
                        "qualityOptions": ["low", "medium", "high", "xhigh", "max"],
                        "resolutionOptions": ["1K", "2K"],
                        "ratioOptions": ["1:1", "16:9"],
                    }
                ],
            }
        ],
        activate=True,
    )

    image = next(
        item
        for item in model_gateway_settings.get_third_party_media_model_catalog("image")
        if item["id"] == "custom-image"
    )

    assert image["qualityOptions"] == ["low", "medium", "high", "xhigh", "max"]
    assert image["resolutionOptions"] == ["1K", "2K"]
    assert image["ratioOptions"] == ["1:1", "16:9"]


def test_third_party_media_catalog_preserves_image_reference_format(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_third_party_gateway_groups = model_gateway_settings.save_third_party_gateway_groups
    save_third_party_gateway_groups(
        [
            {
                "id": "image",
                "name": "Image gateway",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "image-custom",
                        "upstreamModel": "image-custom-upstream",
                        "imageEditFormat": "input_reference",
                    }
                ],
            }
        ],
        activate=True,
    )

    image = next(
        item
        for item in model_gateway_settings.get_third_party_media_model_catalog("image")
        if item["id"] == "image-custom"
    )

    assert image["request"]["referenceFormat"] == "input_reference"




def test_gemini_sub2api_gateway_uses_native_v1beta_protocol(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "gemini-image",
                "name": "Gemini image",
                "protocol": "gemini",
                "baseUrl": "https://gemini.example/v1beta",
                "apiKey": "gemini-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "gemini-2.5-flash-image",
                        "upstreamModel": "gemini-2.5-flash-image",
                    }
                ],
            }
        ],
        activate=True,
    )

    effective = get_effective_newapi_config(
        capability="image", model="gemini-2.5-flash-image"
    )
    assert effective.protocol == "gemini"
    assert effective.base_url == "https://gemini.example/v1"
    assert effective.native_base_url == "https://gemini.example/v1beta"

    image_config = config.get_grid_generation_config(
        provider_override="newapi", model_override="gemini-2.5-flash-image"
    )
    assert image_config["gateway_protocol"] == "gemini"
    assert image_config["gateway_native_base_url"] == "https://gemini.example/v1beta"




def test_sub2api_effective_image_gateway_preserves_mapping_protocol_override(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "image",
                "name": "Image",
                "protocol": "openai",
                "baseUrl": "https://image.example/v1",
                "apiKey": "image-key",
                "capabilities": ["image"],
                "modelMappings": [
                    {
                        "requestPattern": "image-custom",
                        "upstreamModel": "image-custom-upstream",
                        "imageEditFormat": "multipart",
                    }
                ],
            }
        ],
        activate=True,
    )

    image_config = config.get_grid_generation_config(
        provider_override="newapi", model_override="image-custom"
    )
    assert image_config["image_edit_reference_format"] == "multipart"






def test_sub2api_supports_partial_user_defined_groups_and_model_matching(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_sub2api_groups(
        [
            {
                "id": "openai-main",
                "name": "OpenAI main",
                "protocol": "openai",
                "baseUrl": "https://sub2api.example/v1",
                "apiKey": "sk-openai-secret",
                "capabilities": ["text", "image"],
                "modelMappings": [
                    {"requestPattern": "DC-codex-agent-LLM", "upstreamModel": "gpt-5.2"},
                    {"requestPattern": "DC-image-*", "upstreamModel": "gpt-4o"},
                ],
            },
            {
                "id": "gemini-embedding",
                "name": "Gemini embedding",
                "protocol": "gemini",
                "baseUrl": "https://sub2api.example/v1",
                "apiKey": "sk-gemini-secret",
                "capabilities": ["embedding"],
                "modelMappings": [
                    {"requestPattern": "DC-cognee-embedding", "upstreamModel": "gemini-embedding-001"}
                ],
            },
        ],
        activate=True,
    )

    openai = get_effective_newapi_config(capability="text", model="DC-codex-agent-LLM")
    assert openai.api_key == "sk-openai-secret"
    assert openai.model == "gpt-5.2"
    embedding = get_effective_newapi_config(
        capability="embedding", model="DC-cognee-embedding"
    )
    assert embedding.api_key == "sk-gemini-secret"
    assert embedding.model == "gemini-embedding-001"
    assert get_effective_newapi_config(capability="video", model="seedance-2").base_url == ""


@pytest.mark.parametrize(
    ("protocol", "base_url", "upstream_body", "expected_models", "expected_header"),
    [
        (
            "openai",
            "https://openai.sub2api.test/v1",
            {"data": [{"id": "gpt-5"}, {"id": "gpt-4o"}]},
            ["gpt-5", "gpt-4o"],
            "Authorization",
        ),
        (
            "gemini",
            "https://gemini.sub2api.test/v1beta",
            {"models": [{"name": "models/gemini-3-flash", "baseModelId": "gemini-3-flash"}]},
            ["gemini-3-flash"],
            "x-goog-api-key",
        ),
    ],
)
def test_sub2api_model_discovery_uses_protocol_auth_and_normalizes_models(
    monkeypatch, tmp_path, protocol, base_url, upstream_body, expected_models, expected_header
):
    _isolate_settings_db(monkeypatch, tmp_path)
    requests: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, *, headers, params):
            requests.append({"url": url, "headers": headers, "params": params})
            return Response(200, json=upstream_body)

    monkeypatch.setattr(model_gateway.httpx, "Client", FakeClient)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/sub2api/models",
        json={
            "id": "group-1",
            "protocol": protocol,
            "baseUrl": base_url,
            "apiKey": "sk-group-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["models"] == expected_models
    assert "sk-group-secret" not in response.text
    request = requests[0]
    if expected_header == "Authorization":
        assert request["headers"][expected_header] == "Bearer sk-group-secret"
    else:
        assert request["headers"][expected_header] == "sk-group-secret"


def test_gemini_model_discovery_normalizes_v1_base_url_to_v1beta(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    requests: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, *, headers, params):
            requests.append({"url": url, "headers": headers, "params": params})
            return Response(
                200,
                json={
                    "models": [
                        {
                            "name": "models/gemini-3.1-flash-image-preview",
                            "baseModelId": "gemini-3.1-flash-image-preview",
                        }
                    ]
                },
            )

    monkeypatch.setattr(model_gateway.httpx, "Client", FakeClient)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/sub2api/models",
        json={
            "id": "gemini-image",
            "protocol": "gemini",
            "baseUrl": "https://sub2api.example/v1",
            "apiKey": "gemini-key",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["models"] == [
        "gemini-3.1-flash-image-preview"
    ]
    assert requests == [
        {
            "url": "https://sub2api.example/v1beta/models",
            "headers": {"x-goog-api-key": "gemini-key"},
            "params": {"pageSize": 1000},
        }
    ]


def test_sub2api_model_discovery_hides_upstream_error_body(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, *_args, **_kwargs):
            return Response(401, text="invalid key sk-sensitive-secret")

    monkeypatch.setattr(model_gateway.httpx, "Client", FakeClient)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/sub2api/models",
        json={
            "id": "group-1",
            "protocol": "openai",
            "baseUrl": "https://sub2api.test/v1",
            "apiKey": "sk-sensitive-secret",
        },
    )

    assert response.status_code == 502
    assert "sk-sensitive-secret" not in response.text
    assert "invalid key" not in response.text




def test_model_gateway_official_database_key_overrides_env(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_official_newapi_key(
        api_key="sk-user-official-secret",
        activate=True,
    )

    effective = get_effective_newapi_config(
        official_base_url="https://env-official.example/v1",
        official_api_key="sk-env-official-secret",
    )
    assert effective.mode == MODE_OFFICIAL
    assert effective.base_url == OFFICIAL_NEWAPI_BASE_URL
    assert effective.api_key == "sk-user-official-secret"

    status = build_model_gateway_status(
        official_base_url="https://env-official.example/v1",
        official_api_key="sk-env-official-secret",
    )
    assert status["official"]["source"] == "database"
    assert status["official"]["environment"]["configured"] is False


def test_model_gateway_official_url_ignores_newapi_base_url_env(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_official_newapi_key(api_key="sk-database-secret", activate=True)
    monkeypatch.setenv("MODEL_GATEWAY_MODE", MODE_OFFICIAL)
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://malicious.example/v1")
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-env-secret")

    effective = get_effective_newapi_config()

    assert effective.mode == MODE_OFFICIAL
    assert effective.base_url == OFFICIAL_NEWAPI_BASE_URL
    assert effective.api_key == "sk-database-secret"


def test_ce_gateway_does_not_fall_back_to_env_after_database_is_initialized(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    set_model_gateway_mode(MODE_OFFICIAL)
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-later-secret")

    effective = get_effective_newapi_config()
    api_key, base_url = config.get_newapi_runtime_credentials()

    assert effective.api_key == ""
    assert api_key == ""
    assert base_url == OFFICIAL_NEWAPI_BASE_URL


def test_ee_gateway_uses_environment_and_ignores_ce_settings(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_official_newapi_key(api_key="sk-ce-secret", activate=True)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://ee-gateway.example/v1")

    effective = get_effective_newapi_config()

    assert effective.mode == MODE_OFFICIAL
    assert effective.source == "environment"
    assert effective.base_url == "https://ee-gateway.example/v1"
    assert effective.api_key == "sk-ee-secret"

    status = build_model_gateway_status()
    assert status["effective"]["baseUrl"] == "https://ee-gateway.example/v1"
    assert status["official"]["source"] == "environment"


def test_ee_cannot_mutate_ce_model_gateway_settings(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")

    app = FastAPI()
    app.include_router(model_gateway.router)
    response = TestClient(app).post(
        "/model-gateway/official/config",
        json={"newApiApiKey": "sk-should-not-be-saved"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ORG_SERVICE_EGRESS_DENIED"


def test_ce_runtime_refresh_never_mutates_process_environment(monkeypatch, tmp_path):
    from novelvideo.agents import global_video_optimizer

    _isolate_settings_db(monkeypatch, tmp_path)
    tracked = {
        "MODEL_GATEWAY_RUNTIME_VERSION": "startup-version",
        "NEWAPI_API_KEY": "startup-newapi-key",
        "NEWAPI_BASE_URL": "https://startup.example/v1",
        "OPENAI_API_KEY": "startup-openai-key",
        "OPENAI_BASE_URL": "https://startup-openai.example/v1",
        "LLM_API_KEY": "startup-llm-key",
        "LLM_ENDPOINT": "https://startup-llm.example/v1",
        "EMBEDDING_API_KEY": "startup-embedding-key",
        "EMBEDDING_ENDPOINT": "https://startup-embedding.example/v1",
    }
    for key, value in tracked.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(global_video_optimizer, "_global_video_optimizer", object())
    save_official_newapi_key(api_key="sk-database-secret", activate=True)

    runtime = refresh_model_gateway_runtime()

    assert runtime["configured"] is True
    assert {key: os.environ.get(key) for key in tracked} == tracked
    assert global_video_optimizer._global_video_optimizer is None
    assert (
        "novelvideo.agents.global_video_optimizer._global_video_optimizer"
        in runtime["clearedCaches"]
    )


def test_newapi_base_url_normalizers_keep_admin_and_relay_urls_separate():
    assert normalize_admin_base_url("http://new-api:3000/v1") == "http://new-api:3000"
    assert normalize_admin_base_url("http://new-api:3000/") == "http://new-api:3000"
    assert normalize_relay_base_url("http://new-api:3000") == "http://new-api:3000/v1"
    assert (
        normalize_relay_base_url("http://new-api:3000/v1") == "http://new-api:3000/v1"
    )


def test_build_channel_payload_maps_dc_models_to_upstream_models():
    payload = build_channel_payload(
        provider="ali",
        name="user-supplied-name-is-ignored",
        upstream_key="sk-upstream",
        model_mapping={
            "DC-screenplay-normalizer-LLM": "qwen-plus",
            "DC-staging-prop-planner-LLM": "qwen-max",
        },
        group="default,drama",
        priority=2,
    )

    channel = payload["channel"]
    assert payload["mode"] == "single"
    assert channel["name"] == "DC-ali"
    assert channel["type"] == 17
    assert (
        channel["models"] == "DC-screenplay-normalizer-LLM,DC-staging-prop-planner-LLM"
    )
    assert channel["group"] == ",default,drama,"
    assert channel["test_model"] == "DC-screenplay-normalizer-LLM"
    assert channel["model_mapping"] == (
        '{"DC-screenplay-normalizer-LLM":"qwen-plus",'
        '"DC-staging-prop-planner-LLM":"qwen-max"}'
    )


@respx.mock
def test_ensure_newapi_setup_creates_root_when_instance_is_fresh():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    respx.get("http://new-api:3000/api/setup").mock(
        side_effect=[
            Response(200, json={"success": True, "data": {"status": False}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": False,
                        "root_init": False,
                        "database_type": "postgres",
                    },
                },
            ),
            Response(200, json={"success": True, "data": {"status": True}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": True,
                        "root_init": True,
                        "database_type": "postgres",
                    },
                },
            ),
        ]
    )
    setup_request = respx.post("http://new-api:3000/api/setup").mock(
        return_value=Response(200, json={"success": True})
    )

    status = ensure_newapi_setup(
        cfg,
        NewApiSetupCredentials(
            username="admin",
            password="strongpass",
            confirm_password="strongpass",
        ),
    )

    assert status.initialized is True
    assert status.root_initialized is True
    assert status.setup_performed is True
    assert status.already_initialized is False
    assert setup_request.calls.last.request.content
    assert json.loads(setup_request.calls.last.request.content) == {
        "SelfUseModeEnabled": True,
        "DemoSiteEnabled": False,
        "username": "admin",
        "password": "strongpass",
        "confirmPassword": "strongpass",
    }


@respx.mock
def test_ensure_newapi_setup_requires_credentials_for_fresh_instance():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    respx.get("http://new-api:3000/api/setup").mock(
        side_effect=[
            Response(200, json={"success": True, "data": {"status": False}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": False,
                        "root_init": False,
                        "database_type": "postgres",
                    },
                },
            ),
        ]
    )

    with pytest.raises(ValueError, match="setupUsername"):
        ensure_newapi_setup(cfg, NewApiSetupCredentials(username="admin"))


@respx.mock
def test_ensure_newapi_setup_finishes_setup_when_root_already_exists():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    respx.get("http://new-api:3000/api/setup").mock(
        side_effect=[
            Response(200, json={"success": True, "data": {"status": False}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": False,
                        "root_init": True,
                        "database_type": "postgres",
                    },
                },
            ),
            Response(200, json={"success": True, "data": {"status": True}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": True,
                        "root_init": True,
                        "database_type": "postgres",
                    },
                },
            ),
        ]
    )
    setup_request = respx.post("http://new-api:3000/api/setup").mock(
        return_value=Response(200, json={"success": True})
    )

    status = ensure_newapi_setup(cfg)

    assert status.initialized is True
    assert status.setup_performed is True
    assert status.already_initialized is False
    assert json.loads(setup_request.calls.last.request.content) == {
        "SelfUseModeEnabled": True,
        "DemoSiteEnabled": False,
    }


@respx.mock
def test_ensure_newapi_setup_skips_post_when_instance_is_initialized():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    respx.get("http://new-api:3000/api/setup").mock(
        side_effect=[
            Response(200, json={"success": True, "data": {"status": True}}),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "status": True,
                        "root_init": True,
                        "database_type": "postgres",
                    },
                },
            ),
        ]
    )
    setup_request = respx.post("http://new-api:3000/api/setup").mock(
        return_value=Response(200, json={"success": True})
    )

    status = ensure_newapi_setup(
        cfg,
        NewApiSetupCredentials(
            username="root",
            password="strongpass",
            confirm_password="strongpass",
        ),
    )

    assert status.initialized is True
    assert status.root_initialized is True
    assert status.setup_performed is False
    assert status.already_initialized is True
    assert not setup_request.called


@respx.mock
def test_upsert_channel_merges_existing_dc_provider_channel():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    admin = AdminToken(
        admin_user_id=1,
        admin_username="root",
        access_token="admin-secret",
        token_created=False,
    )
    payload = build_channel_payload(
        provider="ali",
        upstream_key="sk-upstream-new",
        model_mapping={"DC-screenplay-normalizer-LLM": "qwen-plus"},
        base_url="https://dashscope-new.example.com",
    )

    respx.get("http://new-api:3000/api/channel/").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [{"id": 3, "name": "DC-ali", "type": 17}],
                    "total": 1,
                },
            },
        )
    )
    respx.get("http://new-api:3000/api/channel/3").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": 3,
                    "name": "DC-ali",
                    "type": 17,
                    "key": "sk-upstream-old",
                    "base_url": "https://dashscope-old.example.com",
                    "models": "DC-old-model",
                    "model_mapping": json.dumps({"DC-old-model": "qwen-old"}),
                    "group": ",default,",
                    "status": 1,
                },
            },
        )
    )
    update_route = respx.put("http://new-api:3000/api/channel/").mock(
        return_value=Response(200, json={"success": True})
    )

    result = upsert_channel(cfg, admin, payload)

    assert result["ok"] is True
    assert result["action"] == "update"
    assert result["channelId"] == 3
    channel = json.loads(update_route.calls.last.request.content)
    assert channel["id"] == 3
    assert channel["name"] == "DC-ali"
    assert channel["key"] == "sk-upstream-new"
    assert channel["base_url"] == "https://dashscope-new.example.com"
    assert "status" not in channel
    assert channel["models"] == "DC-old-model,DC-screenplay-normalizer-LLM"
    assert json.loads(channel["model_mapping"]) == {
        "DC-old-model": "qwen-old",
        "DC-screenplay-normalizer-LLM": "qwen-plus",
    }


@respx.mock
def test_update_provider_channel_credentials_preserves_models_and_mapping():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    admin = AdminToken(
        admin_user_id=1,
        admin_username="root",
        access_token="admin-secret",
        token_created=False,
    )

    respx.get("http://new-api:3000/api/channel/").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [{"id": 3, "name": "DC-ali", "type": 17}],
                    "total": 1,
                },
            },
        )
    )
    respx.get("http://new-api:3000/api/channel/3").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": 3,
                    "name": "DC-ali",
                    "type": 17,
                    "key": "sk-upstream-old",
                    "base_url": "https://dashscope-old.example.com",
                    "models": "DC-old-model,DC-screenplay-normalizer-LLM",
                    "model_mapping": json.dumps(
                        {
                            "DC-old-model": "qwen-old",
                            "DC-screenplay-normalizer-LLM": "qwen-plus",
                        }
                    ),
                    "group": ",default,",
                    "priority": 2,
                    "weight": 3,
                    "test_model": "DC-old-model",
                },
            },
        )
    )
    update_route = respx.put("http://new-api:3000/api/channel/").mock(
        return_value=Response(200, json={"success": True})
    )

    result = update_provider_channel_credentials(
        cfg,
        admin,
        provider="ali",
        upstream_key="sk-upstream-new",
        base_url="https://dashscope-new.example.com/",
    )

    assert result["ok"] is True
    assert result["action"] == "update"
    assert result["channelId"] == 3
    channel = json.loads(update_route.calls.last.request.content)
    assert channel["key"] == "sk-upstream-new"
    assert channel["base_url"] == "https://dashscope-new.example.com"
    assert channel["models"] == "DC-old-model,DC-screenplay-normalizer-LLM"
    assert json.loads(channel["model_mapping"]) == {
        "DC-old-model": "qwen-old",
        "DC-screenplay-normalizer-LLM": "qwen-plus",
    }
    assert channel["priority"] == 2
    assert channel["weight"] == 3
    assert channel["test_model"] == "DC-old-model"


@respx.mock
def test_update_provider_channel_credentials_clears_base_url_override():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    admin = AdminToken(
        admin_user_id=1,
        admin_username="root",
        access_token="admin-secret",
        token_created=False,
    )

    respx.get("http://new-api:3000/api/channel/").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [{"id": 3, "name": "DC-ali", "type": 17}],
                    "total": 1,
                },
            },
        )
    )
    respx.get("http://new-api:3000/api/channel/3").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": 3,
                    "name": "DC-ali",
                    "type": 17,
                    "key": "sk-upstream-old",
                    "base_url": "https://dashscope-old.example.com",
                    "models": "DC-old-model",
                    "model_mapping": json.dumps({"DC-old-model": "qwen-old"}),
                    "group": ",default,",
                    "test_model": "DC-old-model",
                },
            },
        )
    )
    update_route = respx.put("http://new-api:3000/api/channel/").mock(
        return_value=Response(200, json={"success": True})
    )

    result = update_provider_channel_credentials(
        cfg,
        admin,
        provider="ali",
        upstream_key="sk-upstream-new",
        base_url="",
    )

    assert result["ok"] is True
    channel = json.loads(update_route.calls.last.request.content)
    assert channel["key"] == "sk-upstream-new"
    assert channel["base_url"] == ""
    assert channel["models"] == "DC-old-model"
    assert json.loads(channel["model_mapping"]) == {"DC-old-model": "qwen-old"}


@respx.mock
def test_upsert_channel_removes_same_dc_model_from_other_provider_channels():
    cfg = NewApiProvisionerConfig(
        admin_base_url="http://new-api:3000",
        sql_dsn="local",
        sqlite_path="/tmp/one-api.db",
        admin_username="root",
        init_timeout_ms=1000,
        relay_token_name="dramaclaw-ce-runtime",
    )
    admin = AdminToken(
        admin_user_id=1,
        admin_username="root",
        access_token="admin-secret",
        token_created=False,
    )
    payload = build_channel_payload(
        provider="openrouter",
        upstream_key="sk-openrouter",
        model_mapping={"DC-hermes-LLM": "google/gemini-2.5-flash"},
    )

    respx.get("http://new-api:3000/api/channel/").mock(
        side_effect=[
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": [
                            {"id": 4, "name": "DC-openrouter", "type": 20},
                            {"id": 3, "name": "DC-ali", "type": 17},
                        ],
                    },
                },
            ),
            Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "items": [
                            {"id": 4, "name": "DC-openrouter", "type": 20},
                            {"id": 3, "name": "DC-ali", "type": 17},
                        ],
                    },
                },
            ),
        ]
    )
    respx.get("http://new-api:3000/api/channel/4").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": 4,
                    "name": "DC-openrouter",
                    "type": 20,
                    "key": "sk-old-openrouter",
                    "base_url": "https://openrouter.ai/api",
                    "models": "DC-old-openrouter-model",
                    "model_mapping": json.dumps(
                        {"DC-old-openrouter-model": "openrouter/old"}
                    ),
                    "group": ",default,",
                    "status": 1,
                },
            },
        )
    )
    respx.get("http://new-api:3000/api/channel/3").mock(
        return_value=Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": 3,
                    "name": "DC-ali",
                    "type": 17,
                    "key": "sk-ali",
                    "base_url": "https://dashscope.aliyuncs.com",
                    "models": "DC-hermes-LLM,DC-screenplay-normalizer-LLM",
                    "model_mapping": json.dumps(
                        {
                            "DC-hermes-LLM": "qwen-plus",
                            "DC-screenplay-normalizer-LLM": "qwen-max",
                        }
                    ),
                    "group": ",default,",
                    "status": 1,
                    "test_model": "DC-hermes-LLM",
                },
            },
        )
    )
    update_route = respx.put("http://new-api:3000/api/channel/").mock(
        return_value=Response(200, json={"success": True})
    )

    result = upsert_channel(cfg, admin, payload)

    assert result["ok"] is True
    assert result["action"] == "update"
    assert result["dedupedChannels"] == [
        {
            "channelId": 3,
            "name": "DC-ali",
            "ok": True,
            "httpStatus": 200,
            "removedModels": ["DC-hermes-LLM"],
        }
    ]
    target_update = json.loads(update_route.calls[0].request.content)
    assert target_update["id"] == 4
    assert json.loads(target_update["model_mapping"]) == {
        "DC-old-openrouter-model": "openrouter/old",
        "DC-hermes-LLM": "google/gemini-2.5-flash",
    }
    stale_update = json.loads(update_route.calls[1].request.content)
    assert stale_update["id"] == 3
    assert stale_update["models"] == "DC-screenplay-normalizer-LLM"
    assert stale_update["test_model"] == "DC-screenplay-normalizer-LLM"
    assert json.loads(stale_update["model_mapping"]) == {
        "DC-screenplay-normalizer-LLM": "qwen-max",
    }


def test_provisioner_enabled_by_default_and_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ST_EDITION", "ce")
    monkeypatch.delenv("ST_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("NEWAPI_PROVISIONER_ENABLED", raising=False)
    require_provisioner_enabled()

    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "false")
    with pytest.raises(PermissionError, match="not enabled"):
        require_provisioner_enabled()

    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    require_provisioner_enabled()


def test_provisioner_is_always_disabled_in_ee(monkeypatch):
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")

    with pytest.raises(PermissionError, match="not enabled"):
        require_provisioner_enabled()


def test_newapi_db_defaults_to_managed_ce_sqlite_and_does_not_create_empty_file(
    monkeypatch,
    tmp_path,
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("NEWAPI_SQL_DSN", raising=False)
    monkeypatch.delenv("NEWAPI_SQLITE_PATH", raising=False)

    cfg = model_gateway.get_provisioner_config()

    assert cfg.admin_base_url == "http://127.0.0.1:3000"
    assert cfg.sql_dsn == "local"
    assert cfg.sqlite_path == str(tmp_path / "state" / "newapi" / "one-api.db")
    with pytest.raises(RuntimeError, match="does not exist"):
        open_newapi_db(cfg)

    assert not (tmp_path / "state" / "newapi" / "one-api.db").exists()


def test_newapi_db_rejects_missing_sqlite_file(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    missing = tmp_path / "missing-one-api.db"
    monkeypatch.setenv("NEWAPI_SQL_DSN", "local")
    monkeypatch.setenv("NEWAPI_SQLITE_PATH", str(missing))

    with pytest.raises(RuntimeError, match="does not exist"):
        open_newapi_db(model_gateway.get_provisioner_config())

    assert not missing.exists()


def test_provisioner_config_prefers_saved_database_settings(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "NEWAPI_SQL_DSN", "postgresql://env:envpass@127.0.0.1:5432/envdb"
    )
    monkeypatch.setenv("NEWAPI_SQLITE_PATH", "/env/one-api.db")
    monkeypatch.setenv("NEWAPI_ADMIN_USERNAME", "env-root")
    monkeypatch.setenv("NEWAPI_ADMIN_BASE_URL", "http://env-new-api:3000")
    save_custom_newapi_gateway(
        base_url="http://saved-new-api:3000/v1",
        api_key="sk-custom-secret",
        admin_base_url="http://saved-new-api:3000",
        activate=True,
    )
    save_newapi_database_config(
        sql_dsn="local",
        sqlite_path="/saved/one-api.db",
        admin_username="saved-root",
    )

    cfg = get_provisioner_config()

    assert cfg.admin_base_url == "http://saved-new-api:3000"
    assert cfg.sql_dsn == "local"
    assert cfg.sqlite_path == "/saved/one-api.db"
    assert cfg.admin_username == "saved-root"


def test_provisioner_config_request_database_overrides_saved_settings(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_database_config(
        sql_dsn="local",
        sqlite_path="/saved/one-api.db",
        admin_username="saved-root",
    )

    cfg = get_provisioner_config(
        "http://request-new-api:3000",
        sql_dsn="postgresql://request:secret@127.0.0.1:5432/newapi",
        sqlite_path="",
        admin_username="request-root",
    )

    assert cfg.admin_base_url == "http://request-new-api:3000"
    assert cfg.sql_dsn == "postgresql://request:secret@127.0.0.1:5432/newapi"
    assert cfg.sqlite_path == ""
    assert cfg.admin_username == "request-root"


def test_database_status_does_not_expose_database_credentials(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_database_config(
        sql_dsn="postgresql://root:secret@127.0.0.1:5432/newapi",
        admin_username="root",
    )

    status = build_newapi_database_status()

    assert status["configured"] is True
    assert status["source"] == "database"
    assert status["databaseType"] == "external"
    assert "sqlDsnPreview" not in status
    assert "sqlitePath" not in status
    assert "adminUsername" not in status
    assert "secret" not in str(status)


def test_model_gateway_config_route_masks_effective_key(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_BASE_URL", "https://official.example/v1"
    )
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_API_KEY", "sk-official-secret"
    )
    save_official_newapi_key(
        api_key="sk-official-secret",
        activate=True,
    )

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.get("/model-gateway/config")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mode"] == MODE_OFFICIAL
    assert data["effective"]["apiKeyPreview"] == "sk-o...cret"
    assert "sk-official-secret" not in response.text


def test_ee_model_gateway_config_skips_ce_provisioner_and_settings(
    monkeypatch,
    tmp_path,
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setenv("NEWAPI_BASE_URL", "https://ee-gateway.example/v1")
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setattr(model_gateway.app_config, "NEWAPI_API_KEY", "sk-ee-secret")
    monkeypatch.setattr(
        model_gateway,
        "build_provisioner_status",
        lambda: pytest.fail("EE must not build CE provisioner status"),
    )
    monkeypatch.setattr(
        model_gateway_settings,
        "_connect",
        lambda: pytest.fail("EE must not open CE settings.db"),
    )
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).get("/model-gateway/config")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["effective"]["baseUrl"] == "https://ee-gateway.example/v1"
    assert data["provisioner"] == {
        "enabled": False,
        "adminBaseUrl": "",
        "dbConfigured": False,
        "database": {
            "configured": False,
            "available": False,
            "source": "unavailable",
        },
        "adminUsername": "",
        "relayTokenName": "",
        "providers": {},
        "providerChannels": [],
        "mediaModels": {},
        "embeddingModel": {},
        "relayBaseUrl": "",
    }
    assert not (tmp_path / "state").exists()


def test_ce_model_gateway_config_uses_provisioner_builder(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    expected = {
        "enabled": True,
        "adminBaseUrl": "http://new-api:3000",
        "dbConfigured": True,
        "database": {"configured": True},
        "adminUsername": "root",
        "relayTokenName": "ce-runtime",
        "providers": {"openrouter": {}},
        "providerChannels": [],
        "mediaModels": {},
        "embeddingModel": {},
        "relayBaseUrl": "http://new-api:3000/v1",
    }
    monkeypatch.setattr(model_gateway, "build_provisioner_status", lambda: expected)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).get("/model-gateway/config")

    assert response.status_code == 200
    assert response.json()["data"]["provisioner"] == expected


def test_model_gateway_config_excludes_closed_source_provider_presets(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.get("/model-gateway/config")

    assert response.status_code == 200
    providers = response.json()["data"]["provisioner"]["providers"]
    assert "ali" in providers
    assert "openrouter" in providers
    assert "deepseek" in providers
    assert "openai" in providers
    assert providers["azure"]["type"] == 3
    assert providers["gemini"]["type"] == 24
    assert providers["volcengine"]["type"] == 45
    assert providers["codex"]["type"] == 57
    assert "huimeng" not in providers
    assert "fal" not in providers


def test_enable_official_gateway_route_switches_mode_when_enabled(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_BASE_URL", "https://official.example/v1"
    )
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_API_KEY", "sk-official-secret"
    )
    save_official_newapi_key(
        api_key="sk-official-secret",
        activate=True,
    )
    save_custom_newapi_gateway(
        base_url="http://new-api:3000",
        api_key="sk-custom-secret",
        activate=True,
    )

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post("/model-gateway/official/enable")

    assert response.status_code == 200
    assert response.json()["data"]["mode"] == MODE_OFFICIAL
    assert (
        get_effective_newapi_config(
            official_base_url="https://official.example/v1",
            official_api_key="sk-official-secret",
        ).mode
        == MODE_OFFICIAL
    )


def test_official_media_catalog_preferences_and_remote_update(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    source_url = "https://catalog.example.test/official_media_models.json"
    monkeypatch.setenv("OFFICIAL_MEDIA_CATALOG_URL", source_url)
    remote_version = _newer_bundled_catalog_version()
    payload = {
        "version": 1,
        "catalogVersion": remote_version,
        "name": "Test official media models",
        "mediaModels": {
            "test-video": {
                "provider": "newapi",
                "upstreamModel": "test-video",
                "mediaType": "video",
                "label": "Test Video",
                "enabled": True,
                "sortOrder": 10,
                "config": {
                    "request": {
                        "endpoint": "video/generations",
                        "parameters": [],
                    }
                },
            }
        },
    }
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    initial = client.get("/model-gateway/official/media-catalog")
    enabled = client.post(
        "/model-gateway/official/media-catalog/preferences",
        json={"autoUpdate": True},
    )
    with respx.mock:
        respx.get(source_url).mock(return_value=Response(200, json=payload))
        checked = client.post("/model-gateway/official/media-catalog/check")
    current = client.get("/model-gateway/official/media-catalog")

    assert initial.status_code == 200
    assert initial.json()["data"]["autoUpdate"] is False
    assert initial.json()["data"]["source"] == "bundled"
    assert enabled.json()["data"]["autoUpdate"] is True
    assert checked.status_code == 200, checked.text
    assert checked.json()["data"]["updated"] is True
    assert current.json()["data"]["source"] == "remote"
    assert current.json()["data"]["catalogVersion"] == remote_version
    assert current.json()["data"]["modelCount"] == 1


def test_official_media_catalog_defaults_to_dramaclaw_download_bucket(monkeypatch):
    monkeypatch.delenv("OFFICIAL_MEDIA_CATALOG_MANIFEST_URL", raising=False)
    monkeypatch.delenv("OFFICIAL_MEDIA_CATALOG_URL", raising=False)

    assert official_media_catalog_remote._remote_source() == (
        "https://dramaclaw-dl.oss-cn-chengdu.aliyuncs.com/"
        "official-media-catalog/manifest.json",
        True,
    )


def test_official_media_catalog_manifest_verifies_hash_and_revalidates_etag(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    manifest_url = "https://catalog.example.test/official-media-catalog/manifest.json"
    monkeypatch.setenv("OFFICIAL_MEDIA_CATALOG_MANIFEST_URL", manifest_url)
    payload = {
        "version": 1,
        "catalogVersion": _newer_bundled_catalog_version(2),
        "name": "Test official media models",
        "mediaModels": {
            "test-video": {
                "provider": "newapi",
                "upstreamModel": "test-video",
                "mediaType": "video",
                "label": "Test Video",
                "enabled": True,
                "sortOrder": 10,
                "config": {
                    "request": {
                        "endpoint": "video/generations",
                        "parameters": [],
                    }
                },
            }
        },
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    catalog_path = f"catalogs/{digest}.json"
    catalog_url = f"https://catalog.example.test/official-media-catalog/{catalog_path}"
    manifest = {
        "schemaVersion": 1,
        "catalogVersion": payload["catalogVersion"],
        "revision": "a" * 40,
        "publishedAt": "2026-08-07T12:00:00Z",
        "sha256": digest,
        "path": catalog_path,
    }
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    with respx.mock:
        manifest_route = respx.get(manifest_url).mock(
            side_effect=[
                Response(200, json=manifest, headers={"etag": '"release-1"'}),
                Response(304, headers={"etag": '"release-1"'}),
            ]
        )
        catalog_route = respx.get(catalog_url).mock(
            return_value=Response(200, content=canonical)
        )
        installed = client.post("/model-gateway/official/media-catalog/check")
        unchanged = client.post("/model-gateway/official/media-catalog/check")

    assert installed.status_code == 200, installed.text
    installed_data = installed.json()["data"]
    assert installed_data["updated"] is True
    assert installed_data["source"] == "remote"
    assert installed_data["revision"] == "a" * 40
    assert installed_data["publishedAt"] == "2026-08-07T12:00:00Z"
    assert installed_data["sha256"] == digest
    assert installed_data["remoteUrl"] == manifest_url
    assert installed_data["lastError"] == ""
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["data"]["updated"] is False
    assert len(catalog_route.calls) == 1
    assert len(manifest_route.calls) == 2
    assert manifest_route.calls[1].request.headers["if-none-match"] == '"release-1"'


def test_official_media_catalog_manifest_rejects_hash_mismatch(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    manifest_url = "https://catalog.example.test/releases/manifest.json"
    monkeypatch.setenv("OFFICIAL_MEDIA_CATALOG_MANIFEST_URL", manifest_url)
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )
    payload = {**bundled, "catalogVersion": "2026.08.07.2"}
    actual_digest = hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    manifest = {
        "schemaVersion": 1,
        "catalogVersion": payload["catalogVersion"],
        "revision": "b" * 40,
        "publishedAt": "2026-08-07T12:00:00Z",
        "sha256": "0" * 64,
        "path": f"catalogs/{'0' * 64}.json",
    }
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    with respx.mock:
        respx.get(manifest_url).mock(return_value=Response(200, json=manifest))
        respx.get(
            f"https://catalog.example.test/releases/catalogs/{'0' * 64}.json"
        ).mock(return_value=Response(200, json=payload))
        response = client.post("/model-gateway/official/media-catalog/check")

    assert response.status_code == 502
    assert "SHA256" in response.json()["detail"]
    status = client.get("/model-gateway/official/media-catalog").json()["data"]
    assert status["source"] == "bundled"
    assert "SHA256" in status["lastError"]
    assert actual_digest != manifest["sha256"]


def test_official_media_catalog_manifest_rejects_absolute_content_url():
    with pytest.raises(ValueError, match="path"):
        official_media_catalog_remote.validate_official_media_catalog_manifest(
            {
                "schemaVersion": 1,
                "catalogVersion": "2026.08.07.1",
                "revision": "c" * 40,
                "publishedAt": "2026-08-07T12:00:00Z",
                "sha256": "d" * 64,
                "path": "https://attacker.example/catalog.json",
            }
        )


def test_official_media_catalog_rejects_downgrade(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    source_url = "https://catalog.example.test/official_media_models.json"
    monkeypatch.setenv("OFFICIAL_MEDIA_CATALOG_URL", source_url)
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )
    downgraded = {**bundled, "catalogVersion": "2026.08.05.9"}
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    with respx.mock:
        route = respx.get(source_url)
        route.mock(return_value=Response(200, json=downgraded))
        downgrade_response = client.post(
            "/model-gateway/official/media-catalog/check"
        )

    assert downgrade_response.status_code == 502
    assert "downgrade" in downgrade_response.json()["detail"]
    status = client.get("/model-gateway/official/media-catalog").json()["data"]
    assert status["source"] == "bundled"


def test_official_media_catalog_rejects_reused_version_with_different_content(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )
    changed = {**bundled, "name": "Changed without a version bump"}

    with pytest.raises(ValueError, match="version already exists"):
        model_gateway_settings.install_official_media_catalog(
            changed,
            source_url="https://catalog.example.test/official_media_models.json",
        )

    cache_path = Path(config.STATE_DIR) / "local" / "official_media_models.json"
    assert not cache_path.exists()


def test_official_media_catalog_rejects_invalid_model_before_cache_write(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    source_url = "https://catalog.example.test/official_media_models.json"
    monkeypatch.setenv("OFFICIAL_MEDIA_CATALOG_URL", source_url)
    payload = {
        "version": 1,
        "catalogVersion": "2026.08.06.2",
        "mediaModels": {
            "broken-video": {
                "provider": "newapi",
                "upstreamModel": "broken-video",
                "mediaType": "video",
                "sortOrder": "not-a-number",
                "config": {
                    "request": {
                        "endpoint": "video/generations",
                        "parameters": [],
                    }
                },
            }
        },
    }
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    with respx.mock:
        respx.get(source_url).mock(return_value=Response(200, json=payload))
        response = client.post("/model-gateway/official/media-catalog/check")

    assert response.status_code == 502
    assert "sortOrder must be an integer" in response.json()["detail"]
    cache_path = Path(config.STATE_DIR) / "local" / "official_media_models.json"
    assert not cache_path.exists()
    assert client.get("/model-gateway/official/media-catalog").json()["data"][
        "source"
    ] == "bundled"


def test_official_media_catalog_ignores_cache_older_than_bundle(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    bundled = json.loads(
        Path(model_gateway_settings.__file__)
        .with_name("official_media_models.json")
        .read_text(encoding="utf-8")
    )
    cached = json.loads(json.dumps(bundled))
    cached["catalogVersion"] = "2026.08.05.9"
    cache_path = Path(config.STATE_DIR) / "local" / "official_media_models.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(cached), encoding="utf-8")

    status = model_gateway_settings.get_official_media_catalog_update_status()

    assert status["source"] == "bundled"
    assert status["catalogVersion"] == bundled["catalogVersion"]


def test_save_official_gateway_route_persists_user_registered_key(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_BASE_URL", "https://env.example/v1"
    )
    monkeypatch.setattr(model_gateway.app_config, "NEWAPI_API_KEY", "sk-env-secret")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post(
        "/model-gateway/official/config",
        json={
            "newApiApiKey": "sk-user-registered-secret",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["mode"] == MODE_OFFICIAL
    assert data["official"]["baseUrl"] == OFFICIAL_NEWAPI_BASE_URL
    assert data["official"]["source"] == "database"
    assert data["official"]["apiKeyPreview"] == "sk-u...cret"
    assert "sk-user-registered-secret" not in response.text

    effective = get_effective_newapi_config(
        official_base_url="https://env.example/v1",
        official_api_key="sk-env-secret",
    )
    assert effective.base_url == OFFICIAL_NEWAPI_BASE_URL
    assert effective.api_key == "sk-user-registered-secret"


def test_save_official_gateway_route_ignores_submitted_gateway_url(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(
        model_gateway.app_config, "NEWAPI_BASE_URL", "https://env.example/v1"
    )
    monkeypatch.setattr(model_gateway.app_config, "NEWAPI_API_KEY", "sk-env-secret")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post(
        "/model-gateway/official/config",
        json={
            "newApiBaseUrl": "https://official-user.example",
            "newApiApiKey": "sk-user-registered-secret",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["official"]["baseUrl"] == OFFICIAL_NEWAPI_BASE_URL
    effective = get_effective_newapi_config(
        official_base_url="https://env.example/v1",
        official_api_key="sk-env-secret",
    )
    assert effective.base_url == OFFICIAL_NEWAPI_BASE_URL
    assert effective.api_key == "sk-user-registered-secret"












def test_provider_channel_replacement_only_cascades_removed_provider(
    monkeypatch,
    tmp_path,
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_provider_channels(
        [
            {"provider": "openrouter", "upstreamKey": "sk-openrouter"},
            {"provider": "fal", "upstreamKey": "sk-fal"},
        ]
    )
    save_newapi_media_model_mappings(
        {
            "openrouter-image": {
                "provider": "openrouter",
                "upstreamModel": "openrouter/image",
                "mediaType": "image",
            },
            "fal-video": {
                "provider": "fal",
                "upstreamModel": "fal/video",
                "mediaType": "video",
            },
        }
    )
    save_newapi_embedding_model_config(
        provider="openrouter",
        upstream_model="openrouter/embedding",
        dimension=1024,
    )

    save_newapi_provider_channels(
        [{"provider": "fal", "upstreamKey": ""}],
        preserve_unmentioned=False,
    )

    channels = get_newapi_provider_channels()
    assert [channel["provider"] for channel in channels] == ["fal"]
    assert channels[0]["upstreamKey"] == "sk-fal"
    assert get_newapi_media_model_mappings() == {
        "fal-video": {
            "provider": "fal",
            "upstreamModel": "fal/video",
            "mediaType": "video",
        }
    }
    assert get_newapi_embedding_model_config() == {}










@pytest.mark.parametrize("provider", ["claude", "anthropic"])
def test_anthropic_channel_creation_without_explicit_type(provider):
    payload = build_channel_payload(
        provider=provider,
        upstream_key="sk-new-upstream",
        model_mapping={"op-5-5": "op-5-5"},
    )
    assert payload["channel"]["name"] == f"DC-{provider}"
    assert payload["channel"]["type"] == 14
    assert payload["channel"]["base_url"] == "https://api.anthropic.com"












def test_ce_media_model_catalog_uses_saved_custom_model_capabilities(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_media_model_mappings(
        {
            "custom-video": {
                "provider": "volcengine",
                "upstreamModel": "doubao-custom-video",
                "mediaType": "video",
                "label": "Custom Video",
                "enabled": True,
                "sortOrder": 12,
                "config": {
                    "resolutionOptions": ["720p", "1080p"],
                    "ratioOptions": ["16:9", "9:16"],
                    "minDuration": 4,
                    "maxDuration": 10,
                    "supportedModes": ["text_to_video", "first_frame"],
                    "request": {
                        "endpoint": "video/generations",
                        "parameters": [],
                    },
                },
            },
            "disabled-image": {
                "provider": "openrouter",
                "upstreamModel": "disabled-image",
                "mediaType": "image",
                "enabled": False,
                "config": {},
            },
        }
    )

    catalog = get_ce_media_model_catalog("video")

    assert len(catalog) == 1
    assert catalog[0]["id"] == "custom-video"
    assert catalog[0]["apiModel"] == "custom-video"
    assert catalog[0]["label"] == "Custom Video"
    assert catalog[0]["resolutionOptions"] == ["720p", "1080p"]
    assert catalog[0]["supportedModes"] == ["text_to_video", "first_frame"]
    assert get_ce_media_model_catalog("image") == []
    assert get_ce_media_model_catalog("video", provider="comfyui") == []


def test_official_media_model_catalog_uses_ce_export_shape(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    model_gateway_settings._write_many(
        {
            "model_gateway_mode": "custom",
            "third_party_gateway_groups": json.dumps(
                [
                    {
                        "id": "video-gateway",
                        "name": "video",
                        "baseUrl": "https://gateway.invalid/v1",
                        "apiKey": "test-key",
                        "protocol": "openai",
                        "capabilities": ["video"],
                        "modelMappings": [
                            {
                                "requestPattern": "MiniMax-H3",
                                "upstreamModel": "MiniMax-H3",
                                "resolutionOptions": ["768p", "2k"],
                            }
                        ],
                    }
                ]
            ),
        }
    )
    images = get_official_media_model_catalog("image")
    videos = get_official_media_model_catalog("video")

    assert len(images) == 8
    assert len(videos) == 11
    assert [entry["id"] for entry in videos[:2]] == [
        "wan3.0-video-prime",
        "wan3.0-video",
    ]
    wan = videos[0]
    assert wan["referenceFileMax"] == 1
    assert wan["referenceLinkMax"] == 1
    assert "pdf" in wan["referenceFileTypes"]
    seedance_25 = next(entry for entry in videos if entry["id"] == "seedance-2.5")
    assert seedance_25["apiModel"] == "seedance-2.5"
    assert seedance_25["resolutionOptions"] == ["480p", "720p", "1080p"]
    assert seedance_25["ratioOptions"][-1] == "auto"
    seedream = next(entry for entry in images if entry["id"] == "seedream-5.0-pro")
    assert seedream["gatewayModel"] == "seedream-5.0-pro"
    assert seedream["resolutionOptions"] == ["1k", "2k"]
    assert seedream["minPixels"] == 3686400
    seedance = next(entry for entry in videos if entry["id"] == "seedance-2.0-mini")
    assert seedance["apiModel"] == "seedance-2.0-mini"
    assert "video_edit" in seedance["supportedModes"]
    happyhorse_11 = next(entry for entry in videos if entry["id"] == "happyhorse-1.1")
    assert happyhorse_11["gatewayModel"] == "happyhorse-1.1"
    assert happyhorse_11["minDuration"] == 3
    assert happyhorse_11["maxDuration"] == 15
    assert happyhorse_11["ratioOptions"] == [
        "16:9",
        "9:16",
        "1:1",
        "4:3",
        "3:4",
        "21:9",
        "9:21",
        "5:4",
        "4:5",
    ]
    assert happyhorse_11["supportedModes"] == [
        "text_to_video",
        "first_frame",
        "image_to_video",
        "image_reference",
    ]
    assert happyhorse_11["supportsGenerateAudio"] is False
    assert happyhorse_11["referenceImageMax"] == 9
    assert happyhorse_11["referenceVideoMax"] == 0
    assert happyhorse_11["referenceAudioMax"] == 0
    minimax = videos[-1]
    assert minimax["id"] == "MiniMax-H3"
    assert minimax["gatewayModel"] == "MiniMax-H3"
    assert minimax["resolutionOptions"] == ["768p", "2k"]
    from novelvideo.api.routes.generation import _seedance2_resolution_for_backend

    assert _seedance2_resolution_for_backend("MiniMax-H3", "2K") == "2k"
    assert minimax["ratioOptions"] == [
        "21:9",
        "16:9",
        "4:3",
        "1:1",
        "3:4",
        "9:16",
    ]
    assert minimax["minDuration"] == 4
    assert minimax["maxDuration"] == 15
    assert minimax["supportedModes"] == [
        "text_to_video",
        "first_frame",
        "first_last_frame",
        "image_to_video",
        "image_reference",
        "all_reference",
    ]
    assert minimax["referenceImageMax"] == 9
    assert minimax["referenceVideoMax"] == 3
    assert minimax["referenceAudioMax"] == 3


def test_custom_media_model_accepts_arbitrary_image_and_video_models():
    specs, normalized = model_gateway._build_media_model_channel_specs(
        {
            "kling-custom": model_gateway.MediaModelConfigBody(
                provider="openrouter",
                upstreamModel="kling-v2",
                mediaType="video",
                label="Kling Custom",
                config={
                    "resolutionOptions": ["720p", "1080p"],
                    "supportedModes": ["text_to_video", "first_frame"],
                    "request": {
                        "endpoint": "video/generations",
                        "parameters": [],
                    },
                },
            )
        }
    )

    assert specs[0].model_mapping == {"kling-custom": "kling-v2"}
    assert normalized["kling-custom"]["mediaType"] == "video"
    assert normalized["kling-custom"]["label"] == "Kling Custom"
    assert normalized["kling-custom"]["config"]["resolutionOptions"] == [
        "720p",
        "1080p",
    ]






def test_custom_newapi_embedding_model_accepts_positive_project_dimension():
    body = model_gateway.SaveEmbeddingModelBody.model_validate(
        {
            "provider": "openai",
            "upstreamModel": "text-embedding-3-large",
            "dimension": 3072,
        }
    )

    _, normalized = model_gateway._build_embedding_model_channel_spec(body)

    assert normalized["dimension"] == 3072
    assert normalized["sendDimensions"] is True


def test_effective_cognee_embedding_prefers_saved_custom_config(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    set_model_gateway_mode(MODE_CUSTOM)
    monkeypatch.setenv("COGNEE_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("COGNEE_EMBEDDING_MODEL", "gemini-embedding-001")
    monkeypatch.setenv("COGNEE_EMBEDDING_DIM", "768")

    save_newapi_embedding_model_config(
        provider="openai",
        upstream_model="text-embedding-3-large",
        dimension=3072,
    )

    effective = get_effective_cognee_embedding_config(llm_provider="gemini")

    assert effective.source == "database"
    assert effective.provider == "newapi"
    assert effective.model == "DC-cognee-embedding"
    assert effective.dimensions == "3072"
    assert effective.upstream_provider == "openai"
    assert effective.upstream_model == "text-embedding-3-large"


def test_effective_cognee_embedding_keeps_saved_batch_size(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    set_model_gateway_mode(MODE_CUSTOM)

    save_newapi_embedding_model_config(
        provider="ali",
        upstream_model="text-embedding-v3",
        dimension=1024,
        batch_size=10,
    )

    effective = get_effective_cognee_embedding_config(llm_provider="newapi")

    assert effective.source == "database"
    assert effective.provider == "newapi"
    assert effective.model == "DC-cognee-embedding"
    assert effective.dimensions == "1024"
    assert effective.batch_size == "10"


def test_ce_official_embedding_ignores_saved_custom_model(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_newapi_embedding_model_config(
        provider="openai",
        upstream_model="stale-custom-model",
        dimension=1024,
    )
    set_model_gateway_mode(MODE_OFFICIAL)
    monkeypatch.setenv("COGNEE_EMBEDDING_MODEL", "DC-cognee-embedding")
    monkeypatch.setenv("COGNEE_EMBEDDING_DIM", "1024")

    effective = get_effective_cognee_embedding_config()

    assert effective.source == "environment"
    assert effective.model == "DC-cognee-embedding"
    assert effective.dimensions == "1024"
    assert effective.upstream_model == ""


def test_cognee_apply_embedding_env_sets_saved_batch_size(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.delenv("EMBEDDING_BATCH_SIZE", raising=False)

    save_custom_newapi_gateway(
        base_url="https://custom.example",
        api_key="sk-custom-secret",
        activate=True,
    )
    save_newapi_embedding_model_config(
        provider="ali",
        upstream_model="text-embedding-v3",
        dimension=1024,
        batch_size=10,
    )

    from novelvideo.cognee import config as cognee_config

    cognee_config._apply_embedding_env("newapi", "sk-custom-secret")

    assert os.environ["EMBEDDING_BATCH_SIZE"] == "10"




def test_media_relay_config_route_persists_and_masks_oss_keys(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_PROVIDER", "aliyun_oss")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_TTL_SECONDS", 1800)
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_ENDPOINT", "env.endpoint")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_BUCKET", "env-bucket")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_AK", "env-ak-secret")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_SK", "env-sk-secret")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "ttlSeconds": 900,
            "endpoint": "oss-cn-shanghai.aliyuncs.com",
            "bucket": "user-relay",
            "accessKeyId": "LTAI-user-secret",
            "accessKeySecret": "SK-user-secret",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "database"
    assert data["ttlSeconds"] == 900
    assert data["endpoint"] == "oss-cn-shanghai.aliyuncs.com"
    assert data["bucket"] == "user-relay"
    assert data["accessKeyIdPreview"] == "LTAI...cret"
    assert data["accessKeySecretPreview"] == "SK-u...cret"
    assert "LTAI-user-secret" not in response.text
    assert "SK-user-secret" not in response.text


def test_media_relay_config_route_persists_and_masks_cloudinary_keys(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_PROVIDER", "aliyun_oss")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_TTL_SECONDS", 1800)
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_ENDPOINT", "env.endpoint")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_BUCKET", "env-bucket")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_AK", "env-ak-secret")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_SK", "env-sk-secret")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_CLOUD_NAME", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_KEY", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_SECRET", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_FOLDER", "relay")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "cloudinary",
            "ttlSeconds": 900,
            "cloudName": "demo-cloud",
            "apiKey": "cloudinary-api-key-secret",
            "apiSecret": "cloudinary-api-secret",
            "apiFolder": "dramaclaw-relay",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "database"
    assert data["provider"] == "cloudinary"
    assert data["ttlSeconds"] == 900
    assert data["cloudName"] == "demo-cloud"
    assert data["apiFolder"] == "dramaclaw-relay"
    assert data["cloudinaryApiKeyPreview"] == "clou...cret"
    assert data["cloudinaryApiSecretPreview"] == "clou...cret"
    assert data["configured"] is True
    assert "cloudinary-api-key-secret" not in response.text
    assert "cloudinary-api-secret" not in response.text


def test_media_relay_config_route_persists_minio_and_masks_root_credentials(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    response = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "minio",
            "ttlSeconds": 900,
            "endpoint": "media-minio",
            "publicEndpoint": "https://media.example.com",
            "port": 9000,
            "useSSL": False,
            "bucket": "staging",
            "accessKeyId": "minio-root-user",
            "accessKeySecret": "minio-root-secret",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "minio"
    assert data["minioEndpoint"] == "media-minio"
    assert data["minioPublicEndpoint"] == "https://media.example.com"
    assert data["minioPort"] == 9000
    assert data["minioBucket"] == "staging"
    assert data["minioAccessKeyPreview"] == "mini...user"
    assert data["minioSecretKeyPreview"] == "mini...cret"
    assert data["configured"] is True
    assert "minio-root-user" not in response.text
    assert "minio-root-secret" not in response.text


def test_media_relay_config_rejects_non_https_minio_public_endpoint(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "minio",
            "endpoint": "media-minio",
            "publicEndpoint": "http://media.example.com",
            "bucket": "staging",
            "accessKeyId": "minio-user",
            "accessKeySecret": "minio-secret",
        },
    )

    assert response.status_code == 400
    assert "publicEndpoint must be an HTTPS origin" in response.json()["detail"]


def test_media_relay_config_rejects_minio_ttl_over_seven_days(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "minio",
            "ttlSeconds": 7 * 24 * 60 * 60 + 1,
            "endpoint": "media-minio",
            "publicEndpoint": "https://media.example.com",
            "bucket": "staging",
            "accessKeyId": "minio-user",
            "accessKeySecret": "minio-secret",
        },
    )

    assert response.status_code == 400
    assert "TTL must not exceed 7 days" in response.json()["detail"]


def test_media_relay_switching_provider_preserves_inactive_credentials(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    minio = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "minio",
            "endpoint": "media-minio",
            "publicEndpoint": "https://media.example.com",
            "bucket": "staging",
            "accessKeyId": "minio-access",
            "accessKeySecret": "minio-secret",
        },
    )
    assert minio.status_code == 200

    oss = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "endpoint": "oss.example.com",
            "bucket": "oss-bucket",
            "accessKeyId": "oss-access",
            "accessKeySecret": "oss-secret",
        },
    )

    assert oss.status_code == 200
    data = oss.json()["data"]
    assert data["endpoint"] == "oss.example.com"
    assert data["bucket"] == "oss-bucket"
    assert data["minioEndpoint"] == "media-minio"
    assert data["minioBucket"] == "staging"
    assert data["minioAccessKeyPreview"] == "mini...cess"
    assert data["minioSecretKeyPreview"] == "mini...cret"


def test_media_relay_config_route_supports_partial_credential_updates(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_PROVIDER", "aliyun_oss")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_TTL_SECONDS", 1800)
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_ENDPOINT", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_BUCKET", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_AK", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_SK", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_CLOUD_NAME", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_KEY", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_SECRET", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_FOLDER", "")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    initial = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "ttlSeconds": 900,
            "endpoint": "oss-cn-shanghai.aliyuncs.com",
            "bucket": "user-relay",
            "accessKeyId": "LTAI-old-secret",
            "accessKeySecret": "SK-old-secret",
        },
    )
    assert initial.status_code == 200

    updated = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "ttlSeconds": 1200,
            "endpoint": "oss-cn-beijing.aliyuncs.com",
            "bucket": "user-relay",
            "accessKeyId": "LTAI-new-secret",
            "accessKeySecret": "",
        },
    )

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["ttlSeconds"] == 1200
    assert data["endpoint"] == "oss-cn-beijing.aliyuncs.com"
    assert data["accessKeyIdPreview"] == "LTAI...cret"
    assert data["accessKeySecretPreview"] == "SK-o...cret"
    assert data["configured"] is True
    assert "LTAI-new-secret" not in updated.text
    assert "SK-old-secret" not in updated.text


def test_media_relay_config_route_preserves_inactive_provider_credentials(
    monkeypatch, tmp_path
):
    _isolate_settings_db(monkeypatch, tmp_path)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_PROVIDER", "aliyun_oss")
    monkeypatch.setattr(model_gateway.app_config, "MEDIA_RELAY_TTL_SECONDS", 1800)
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_ENDPOINT", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_BUCKET", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_AK", "")
    monkeypatch.setattr(model_gateway.app_config, "OSS_RELAY_SK", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_CLOUD_NAME", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_KEY", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_API_SECRET", "")
    monkeypatch.setattr(model_gateway.app_config, "CLOUDINARY_RELAY_FOLDER", "")

    app = FastAPI()
    app.include_router(model_gateway.router)
    client = TestClient(app)

    oss = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "endpoint": "oss.example.com",
            "bucket": "oss-bucket",
            "accessKeyId": "oss-access-key",
            "accessKeySecret": "oss-secret-key",
        },
    )
    assert oss.status_code == 200

    cloudinary = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "cloudinary",
            "cloudName": "demo-cloud",
            "apiKey": "cloudinary-api-key",
            "apiSecret": "cloudinary-api-secret",
        },
    )
    assert cloudinary.status_code == 200
    cloudinary_data = cloudinary.json()["data"]
    assert cloudinary_data["accessKeyIdPreview"] == "oss-...-key"
    assert cloudinary_data["accessKeySecretPreview"] == "oss-...-key"

    cloudinary_partial = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "cloudinary",
            "cloudName": "demo-cloud",
            "apiKey": "",
            "apiSecret": "cloudinary-new-secret",
        },
    )
    assert cloudinary_partial.status_code == 200
    cloudinary_partial_data = cloudinary_partial.json()["data"]
    assert cloudinary_partial_data["cloudinaryApiKeyPreview"] == "clou...-key"
    assert cloudinary_partial_data["cloudinaryApiSecretPreview"] == "clou...cret"

    switched_back = client.post(
        "/model-gateway/media-relay/config",
        json={
            "provider": "aliyun_oss",
            "endpoint": "oss.example.com",
            "bucket": "oss-bucket",
        },
    )
    assert switched_back.status_code == 200
    switched_data = switched_back.json()["data"]
    assert switched_data["configured"] is True
    assert switched_data["cloudinaryApiKeyPreview"] == "clou...-key"
    assert switched_data["cloudinaryApiSecretPreview"] == "clou...cret"


def test_media_relay_status_prefers_database_config(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_media_relay_config(
        provider="aliyun_oss",
        ttl_seconds=600,
        endpoint="db.endpoint",
        bucket="db-bucket",
        access_key_id="db-ak-secret",
        access_key_secret="db-sk-secret",
    )

    status = model_gateway._media_relay_status()

    assert status["source"] == "database"
    assert status["ttlSeconds"] == 600
    assert status["endpoint"] == "db.endpoint"
    assert status["bucket"] == "db-bucket"
    assert status["configured"] is True


def test_ee_media_relay_ignores_ce_database_config(monkeypatch, tmp_path):
    _isolate_settings_db(monkeypatch, tmp_path)
    save_media_relay_config(
        provider="aliyun_oss",
        ttl_seconds=600,
        endpoint="stale-ce.endpoint",
        bucket="stale-ce-bucket",
        access_key_id="stale-ce-ak",
        access_key_secret="stale-ce-sk",
    )
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://control-plane")
    monkeypatch.setattr(config, "OSS_RELAY_ENDPOINT", "ee.endpoint")
    monkeypatch.setattr(config, "OSS_RELAY_BUCKET", "ee-bucket")
    monkeypatch.setattr(config, "OSS_RELAY_AK", "ee-ak")
    monkeypatch.setattr(config, "OSS_RELAY_SK", "ee-sk")

    status = model_gateway._media_relay_status()

    assert status["source"] == "environment"
    assert status["endpoint"] == "ee.endpoint"
    assert status["bucket"] == "ee-bucket"
    assert status["configured"] is True
