"""Model gateway configuration endpoints for CE."""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from novelvideo import config as app_config
from novelvideo.chat.codex_app_server import restart_shared_codex_runtime_when_idle
from novelvideo.model_gateway_settings import (
    AGENT_LLM_MODE_INHERIT,
    AGENT_LLM_MODE_THIRD_PARTY,
    MODE_CUSTOM,
    CUSTOM_LLM_MODE_ADVANCED,
    CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
    MODE_OFFICIAL,
    MODE_HYBRID,
    MODE_SUB2API,
    SUB2API_PROTOCOLS,
    build_media_relay_status,
    build_model_gateway_status,
    get_model_gateway_settings,
    get_effective_media_relay_config,
    get_official_media_catalog_update_status,
    normalize_relay_base_url,
    normalize_api_key,
    parse_comfyui_channel_workflows,
    save_media_relay_config,
    save_agent_llm_config,
    save_official_media_catalog_auto_update,
    save_official_newapi_key,
    save_relayclaw_brainclaw_key,
    save_custom_newapi_gateway,
    save_sub2api_groups,
    get_sub2api_groups,
    save_third_party_gateway_groups,
    get_third_party_gateway_groups,
    set_model_gateway_mode,
    set_custom_llm_mode,
)
from novelvideo.official_media_catalog_remote import (
    check_official_media_catalog_update,
)
from novelvideo.model_gateway_runtime import refresh_model_gateway_runtime
from novelvideo.model_gateway_protocols import (
    extract_model_names,
    model_discovery_request,
    normalize_gateway_protocol,
    normalize_protocol_base_url,
    validate_protocol_capabilities,
)
from novelvideo.service_operation_gate import (
    ServiceOperationExcluded,
    require_legacy_local_service_operation,
)
from novelvideo.shared.runtime_env import is_ce_effective
from novelvideo.media_model_request_schema import validate_media_model_catalog_config
from novelvideo.storage.media_relay import MINIO_MAX_PRESIGNED_TTL_SECONDS
from novelvideo.newapi_provisioner import (
    build_channel_payload,
    build_provisioner_status,
    create_or_reuse_relay_token,
    delete_channel_by_name,
    ensure_newapi_setup,
    ensure_admin_access_token,
    fetch_provider_channel_models,
    get_provisioner_config,
    list_channel_types,
    mask_token,
    NewApiSetupCredentials,
    ServiceControlEgressDenied,
    require_provisioner_enabled,
    upsert_channel,
    update_provider_channel_credentials,
)

router = APIRouter(prefix="/model-gateway")


def _refresh_runtime_after_gateway_write() -> dict[str, Any]:
    """Refresh caches and invalidate the effective Agent route on every worker."""

    runtime = refresh_model_gateway_runtime()
    runtime["codexAppServer"] = restart_shared_codex_runtime_when_idle()
    return runtime


OFFICIAL_ONLY_MEDIA_MODEL_NAMES = {
    "seedance-2.0-value",
    "seedance-2.0-fast-value",
}
COMFY_WORKFLOW_MANAGED_CONFIG_KEY = "_dcManagedByWorkflow"


def _default_comfyui_media_model_config(
    model: str, *, workflow_ids: list[str] | None = None
) -> dict[str, Any]:
    route_tokens = {
        token
        for value in (workflow_ids or [model])
        for token in str(value or "").strip().lower().replace("-", "_").split("_")
    }
    supported_modes: list[str] = []
    reference_limits: dict[str, int | bool] = {}
    is_minimax_h3_local = model.strip().lower() == "minimax-h3-local"
    resolution_options = (
        ["480p", "768p", "1080p"]
        if is_minimax_h3_local
        else ["480p", "640p"]
    )
    ratio_options = (
        ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]
        if is_minimax_h3_local
        else ["16:9", "1:1"]
        if "i2v" in route_tokens
        else ["1:1", "16:9"]
    )
    if "t2v" in route_tokens or not route_tokens.intersection({"i2v", "r2v"}):
        supported_modes.append("text_to_video")
    if "i2v" in route_tokens:
        supported_modes.extend(
            ["first_frame"]
            if is_minimax_h3_local
            else ["image_to_video", "image_reference"]
        )
        reference_limits["referenceImageMax"] = 1
    if "r2v" in route_tokens:
        supported_modes.append("all_reference")
        reference_limits = {
            "referenceImageMax": 9,
            "referenceVideoMax": 3,
            "referenceAudioMax": 3,
        }
    return {
        "request": {"endpoint": "video/generations", "parameters": []},
        "resolutionOptions": resolution_options,
        "ratioOptions": ratio_options,
        "minDuration": 4,
        "maxDuration": 15,
        "supportedModes": supported_modes,
        **reference_limits,
        COMFY_WORKFLOW_MANAGED_CONFIG_KEY: True,
    }


def _comfyui_media_model_config(
    model: str,
    previous: dict[str, Any] | None,
    *,
    workflow_ids: list[str] | None = None,
) -> dict[str, Any]:
    current = previous if isinstance(previous, dict) else {}
    # Older channel saves created workflow models with only a request block.
    # Backfill those records, while leaving any user-authored capabilities intact.
    if set(current).issubset({"request", COMFY_WORKFLOW_MANAGED_CONFIG_KEY}):
        return {
            **_default_comfyui_media_model_config(
                model,
                workflow_ids=workflow_ids,
            ),
            **current,
        }
    return current


def require_ce_gateway_management() -> None:
    """Reject CE-local gateway mutations from an EE-composed process."""
    try:
        require_legacy_local_service_operation()
    except ServiceOperationExcluded as exc:
        raise PermissionError(exc.code) from None
    if not is_ce_effective():
        raise ServiceControlEgressDenied()
    require_provisioner_enabled()


def require_ce_gateway_settings_management() -> None:
    """Allow external gateway settings when the local NewAPI provisioner is off."""
    try:
        require_legacy_local_service_operation()
    except ServiceOperationExcluded as exc:
        raise PermissionError(exc.code) from None
    if not is_ce_effective():
        raise ServiceControlEgressDenied()


class OfficialGatewayBody(BaseModel):
    new_api_api_key: str = Field(alias="newApiApiKey")


class OfficialMediaCatalogPreferencesBody(BaseModel):
    auto_update: bool = Field(alias="autoUpdate")


class BrainClawGatewayBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    new_api_api_key: str | None = Field(default=None, alias="newApiApiKey")


class Sub2ApiGatewayBody(BaseModel):
    groups: list[dict[str, Any]] = Field(default_factory=list)


class Sub2ApiModelsBody(BaseModel):
    id: str = ""
    protocol: str
    base_url: str = Field(alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")


class CustomLlmModeBody(BaseModel):
    mode: str


class AgentLlmConfigBody(BaseModel):
    mode: str
    base_url: str | None = Field(default=None, alias="baseUrl")
    api_key: str | None = Field(default=None, alias="apiKey")
    model: str | None = None


class MediaRelayConfigBody(BaseModel):
    provider: str = "aliyun_oss"
    ttl_seconds: int = Field(default=1800, alias="ttlSeconds")
    endpoint: str | None = None
    bucket: str | None = None
    access_key_id: str | None = Field(default=None, alias="accessKeyId")
    access_key_secret: str | None = Field(default=None, alias="accessKeySecret")
    cloud_name: str | None = Field(default=None, alias="cloudName")
    cloudinary_api_key: str | None = Field(default=None, alias="apiKey")
    cloudinary_api_secret: str | None = Field(default=None, alias="apiSecret")
    cloudinary_folder: str | None = Field(default=None, alias="apiFolder")
    public_endpoint: str | None = Field(default=None, alias="publicEndpoint")
    port: int | None = None
    use_ssl: bool | None = Field(default=None, alias="useSSL")


class NewApiDatabaseBody(BaseModel):
    sql_dsn: str | None = Field(default=None, alias="sqlDsn")
    sqlite_path: str | None = Field(default=None, alias="sqlitePath")
    admin_username: str | None = Field(default=None, alias="adminUsername")


class NewApiInitBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    setup_username: str | None = Field(default=None, alias="setupUsername")
    setup_password: str | None = Field(default=None, alias="setupPassword")
    setup_confirm_password: str | None = Field(
        default=None, alias="setupConfirmPassword"
    )
    token_name: str | None = Field(default=None, alias="tokenName")
    group: str = "default"
    unlimited_quota: bool = Field(default=True, alias="unlimitedQuota")
    remain_quota: int = Field(default=0, alias="remainQuota")
    expired_time: int = Field(default=-1, alias="expiredTime")
    reuse_existing: bool = Field(default=True, alias="reuseExisting")


class CreateChannelBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    provider: str = "ali"
    type: int | None = None
    name: str | None = None
    upstream_key: str | None = Field(default=None, alias="upstreamKey")
    model_mapping: dict[str, str] = Field(alias="modelMapping")
    group: str = "default"
    priority: int | None = None
    weight: int = 0
    base_url: str | None = Field(default=None, alias="baseUrl")
    test_model: str | None = Field(default=None, alias="testModel")
    settings: dict[str, Any] = Field(default_factory=dict)


class ChannelSpec(BaseModel):
    provider: str = "ali"
    type: int | None = None
    name: str | None = None
    upstream_key: str | None = Field(default=None, alias="upstreamKey")
    model_mapping: dict[str, str] = Field(alias="modelMapping")
    group: str = "default"
    priority: int | None = None
    weight: int = 0
    base_url: str | None = Field(default=None, alias="baseUrl")
    test_model: str | None = Field(default=None, alias="testModel")
    settings: dict[str, Any] = Field(default_factory=dict)


class CreateChannelsBatchBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    channels: list[ChannelSpec] = Field(min_length=1)


class ProviderChannelConfigBody(BaseModel):
    provider: str
    type: int | None = None
    upstream_key: str | None = Field(default=None, alias="upstreamKey")
    base_url: str | None = Field(default=None, alias="baseUrl")
    priority: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class SaveProviderChannelsBody(BaseModel):
    channels: list[ProviderChannelConfigBody] = Field(default_factory=list)
    preserve_unmentioned: bool = Field(default=False, alias="preserveUnmentioned")


class SyncProviderChannelBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    provider: str
    upstream_key: str | None = Field(default=None, alias="upstreamKey")
    base_url: str | None = Field(default=None, alias="baseUrl")


class ProviderChannelModelsBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    provider: str
    type: int | None = None


class MediaModelConfigBody(BaseModel):
    provider: str
    upstream_model: str | None = Field(default=None, alias="upstreamModel")
    media_type: str | None = Field(default=None, alias="mediaType")
    label: str | None = None
    enabled: bool = True
    sort_order: int = Field(default=100, alias="sortOrder")
    config: dict[str, Any] = Field(default_factory=dict)


class SaveMediaModelsBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    models: dict[str, MediaModelConfigBody] = Field(default_factory=dict)


class SaveEmbeddingModelBody(BaseModel):
    new_api_base_url: str | None = Field(default=None, alias="newApiBaseUrl")
    database: NewApiDatabaseBody | None = None
    provider: str
    upstream_model: str = Field(alias="upstreamModel")
    dimension: int
    batch_size: int | None = Field(default=None, alias="batchSize")
    send_dimensions: bool = Field(default=True, alias="sendDimensions")


def _permission_error(exc: PermissionError) -> HTTPException:
    return HTTPException(status_code=403, detail=str(exc))


def _get_provisioner_config_from_request(
    new_api_base_url: str | None,
    database: NewApiDatabaseBody | None,
):
    return get_provisioner_config(
        new_api_base_url,
        sql_dsn=database.sql_dsn if database else None,
        sqlite_path=database.sqlite_path if database else None,
        admin_username=database.admin_username if database else None,
    )


def _save_request_database_config(
    cfg,
    database: NewApiDatabaseBody | None,
) -> None:
    if database is None:
        return
    save_newapi_database_config(
        sql_dsn=cfg.sql_dsn,
        sqlite_path=cfg.sqlite_path,
        admin_username=cfg.admin_username,
    )


def _setup_credentials_from_request(body: NewApiInitBody) -> NewApiSetupCredentials:
    username = (body.setup_username or "").strip()
    if not username and body.database and body.database.admin_username:
        username = body.database.admin_username.strip()
    return NewApiSetupCredentials(
        username=username,
        password=body.setup_password or "",
        confirm_password=body.setup_confirm_password or "",
        self_use_mode_enabled=True,
        demo_site_enabled=False,
    )


def _build_channel_payload_from_spec(
    spec: ChannelSpec | CreateChannelBody,
) -> dict[str, Any]:
    saved_channel = get_newapi_provider_channel(spec.provider) or {}
    return build_channel_payload(
        provider=spec.provider,
        channel_type=spec.type or int(saved_channel.get("type") or 0) or None,
        name=spec.name,
        upstream_key=spec.upstream_key or saved_channel.get("upstreamKey", ""),
        model_mapping=spec.model_mapping,
        group=spec.group,
        priority=(
            int(saved_channel.get("priority") or 0)
            if spec.priority is None
            else spec.priority
        ),
        weight=spec.weight,
        base_url=spec.base_url or saved_channel.get("baseUrl", ""),
        test_model=spec.test_model,
        other_settings=spec.settings or saved_channel.get("settings", {}),
    )


def _build_media_model_channel_specs(
    models: dict[str, MediaModelConfigBody],
) -> tuple[list[ChannelSpec], dict[str, dict[str, Any]]]:
    if not models:
        raise ValueError("models must be a non-empty JSON object")

    grouped: dict[str, dict[str, str]] = {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_model, item in models.items():
        model = str(raw_model or "").strip()
        if not model:
            raise ValueError("models contains an empty model name")
        if model in OFFICIAL_ONLY_MEDIA_MODEL_NAMES:
            raise ValueError(f"media model {model} is official-channel only")
        provider = str(item.provider or "").strip().lower()
        if not provider:
            raise ValueError(f"provider is required for media model {model}")
        upstream_model = (item.upstream_model or "").strip() or model
        media_type = str(item.media_type or "").strip().lower()
        if not media_type:
            if model in {"LingShan-G2", "LingShan-NB-2"} or model.startswith(
                "seedream-"
            ):
                media_type = "image"
            elif model in {"index-tts-2", "LingShan-MU-11"}:
                media_type = "audio"
            else:
                media_type = "video"
        if media_type not in {"image", "video", "audio"}:
            raise ValueError(f"invalid mediaType for media model {model}")
        model_config = dict(item.config)
        if media_type in {"image", "video"}:
            model_config.setdefault(
                "request",
                {
                    "endpoint": (
                        "images/generations"
                        if media_type == "image"
                        else "video/generations"
                    ),
                    "parameters": [],
                },
            )
            validate_media_model_catalog_config(model_config, media_type)
        grouped.setdefault(provider, {})[model] = upstream_model
        normalized[model] = {
            "provider": provider,
            "upstreamModel": "" if upstream_model == model else upstream_model,
            "mediaType": media_type,
            "label": str(item.label or model).strip() or model,
            "enabled": bool(item.enabled),
            "sortOrder": int(item.sort_order),
            "config": model_config,
        }

    specs = [
        ChannelSpec(
            provider=provider,
            type=63 if provider == "comfyui" else None,
            modelMapping=mapping,
        )
        for provider, mapping in grouped.items()
    ]
    return specs, normalized


def _build_embedding_model_channel_spec(
    body: SaveEmbeddingModelBody,
) -> tuple[ChannelSpec, dict[str, Any]]:
    provider = str(body.provider or "").strip().lower()
    upstream_model = str(body.upstream_model or "").strip()
    dimension = int(body.dimension)
    batch_size = int(body.batch_size or 0)
    if not provider:
        raise ValueError("provider is required for embedding model")
    if not upstream_model:
        raise ValueError("upstreamModel is required for embedding model")
    if dimension <= 0:
        raise ValueError("dimension must be positive")
    if body.batch_size is not None and batch_size <= 0:
        raise ValueError("batchSize must be positive")
    normalized = {
        "provider": provider,
        "upstreamModel": upstream_model,
        "dimension": dimension,
        # Kept in the response/config schema for compatibility with older
        # clients. Runtime request behavior is controlled by the internal
        # EmbeddingModelSpec, not by this user-supplied field.
        "sendDimensions": True,
        "internalModel": "DC-cognee-embedding",
    }
    if batch_size > 0:
        normalized["batchSize"] = batch_size
    return (
        ChannelSpec(
            provider=provider,
            modelMapping={"DC-cognee-embedding": upstream_model},
        ),
        normalized,
    )


def _mask_sent_channel_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **payload,
        "channel": {
            **payload["channel"],
            "key": mask_token(payload["channel"]["key"]),
        },
    }


def _media_relay_status() -> dict[str, Any]:
    return build_media_relay_status(
        env_provider=app_config.MEDIA_RELAY_PROVIDER,
        env_ttl_seconds=app_config.MEDIA_RELAY_TTL_SECONDS,
        env_endpoint=app_config.OSS_RELAY_ENDPOINT,
        env_bucket=app_config.OSS_RELAY_BUCKET,
        env_access_key_id=app_config.OSS_RELAY_AK,
        env_access_key_secret=app_config.OSS_RELAY_SK,
        env_cloud_name=app_config.CLOUDINARY_RELAY_CLOUD_NAME,
        env_cloudinary_api_key=app_config.CLOUDINARY_RELAY_API_KEY,
        env_cloudinary_api_secret=app_config.CLOUDINARY_RELAY_API_SECRET,
        env_cloudinary_folder=app_config.CLOUDINARY_RELAY_FOLDER,
        env_minio_endpoint=app_config.MINIO_RELAY_ENDPOINT,
        env_minio_public_endpoint=app_config.MINIO_RELAY_PUBLIC_ENDPOINT,
        env_minio_port=app_config.MINIO_RELAY_PORT,
        env_minio_use_ssl=app_config.MINIO_RELAY_USE_SSL,
        env_minio_bucket=app_config.MINIO_RELAY_BUCKET,
        env_minio_access_key=app_config.MINIO_RELAY_ACCESS_KEY,
        env_minio_secret_key=app_config.MINIO_RELAY_SECRET_KEY,
    )


def _provisioner_status() -> dict[str, Any]:
    if is_ce_effective():
        return build_provisioner_status()
    return {
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


@router.get("/config")
async def get_model_gateway_config() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            **build_model_gateway_status(
                official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
                official_api_key=app_config.NEWAPI_API_KEY,
            ),
            "provisioner": _provisioner_status(),
            "mediaRelay": _media_relay_status(),
        },
    }


def _require_ce_media_catalog_management() -> None:
    if not is_ce_effective():
        raise PermissionError("official media catalog management is only available in CE")


@router.get("/official/media-catalog")
async def get_official_media_catalog_status() -> dict[str, Any]:
    try:
        _require_ce_media_catalog_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    return {"ok": True, "data": get_official_media_catalog_update_status()}


@router.post("/official/media-catalog/preferences")
async def save_official_media_catalog_preferences(
    body: OfficialMediaCatalogPreferencesBody,
) -> dict[str, Any]:
    try:
        _require_ce_media_catalog_management()
        status = save_official_media_catalog_auto_update(body.auto_update)
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    return {"ok": True, "data": status}


@router.post("/official/media-catalog/check")
async def check_official_media_catalog() -> dict[str, Any]:
    try:
        _require_ce_media_catalog_management()
        updated, status = await check_official_media_catalog_update()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "data": {**status, "updated": updated}}


@router.post("/official/enable")
async def enable_official_gateway() -> dict[str, Any]:
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    status = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    if not status["official"]["configured"]:
        raise HTTPException(
            status_code=400,
            detail="official NewAPI gateway is not configured",
        )
    set_model_gateway_mode(MODE_OFFICIAL)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/custom/enable")
async def enable_custom_gateway() -> dict[str, Any]:
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    status = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    if not status["thirdParty"]["configured"]:
        raise HTTPException(
            status_code=400, detail="At least one valid third-party gateway group is required"
        )
    set_model_gateway_mode(MODE_CUSTOM)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/third-party/config")
async def save_third_party_gateway_config(body: Sub2ApiGatewayBody) -> dict[str, Any]:
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    if not body.groups:
        save_third_party_gateway_groups([], activate=False)
        runtime = _refresh_runtime_after_gateway_write()
        return {
            "ok": True,
            "data": build_model_gateway_status(
                official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
                official_api_key=app_config.NEWAPI_API_KEY,
            ),
            "runtime": runtime,
        }
    existing = {group["id"]: group for group in get_third_party_gateway_groups()}
    groups: list[dict[str, Any]] = []
    for submitted in body.groups:
        group = dict(submitted)
        protocol = normalize_gateway_protocol(group.get("protocol"))
        if protocol not in SUB2API_PROTOCOLS:
            raise HTTPException(status_code=400, detail="protocol must be openai, gemini, or anthropic")
        base_url = str(group.get("baseUrl") or "").strip().rstrip("/")
        parsed_base_url = urlsplit(base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise HTTPException(status_code=400, detail="each group requires an HTTP(S) Base URL")
        group_id = str(group.get("id") or "").strip()
        previous = existing.get(group_id)
        api_key = normalize_api_key(group.get("apiKey"))
        if not api_key and previous:
            if base_url != str(previous.get("baseUrl") or "").rstrip("/"):
                raise HTTPException(
                    status_code=400,
                    detail=f"API Key is required when changing the Base URL for {group_id}",
                )
            api_key = str(previous.get("apiKey") or "")
        if not api_key:
            raise HTTPException(status_code=400, detail=f"API Key is required for {group_id or 'new group'}")
        try:
            validate_protocol_capabilities(protocol, list(group.get("capabilities") or []))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        group["apiKey"] = api_key
        # Image edit request shape is protocol-derived for new/rewritten groups;
        # unchanged legacy group data keeps its hidden compatibility value.
        previous_mappings = previous.get("modelMappings", []) if previous else []
        previous_by_pattern = {
            str(mapping.get("requestPattern") or ""): mapping
            for mapping in previous_mappings
            if isinstance(mapping, dict)
        }
        preserve_legacy_shape = bool(
            previous
            and base_url == str(previous.get("baseUrl") or "").rstrip("/")
            and protocol == str(previous.get("protocol") or "").lower()
        )
        rewritten_mappings = []
        for mapping in group.get("modelMappings", []):
            if not isinstance(mapping, dict):
                continue
            previous_mapping = previous_by_pattern.get(str(mapping.get("requestPattern") or ""))
            unchanged = (
                preserve_legacy_shape
                and previous_mapping is not None
                and mapping.get("upstreamModel") == previous_mapping.get("upstreamModel")
            )
            rewritten_mappings.append(
                dict(mapping)
                if unchanged
                else {key: value for key, value in mapping.items() if key != "imageEditFormat"}
            )
        group["modelMappings"] = rewritten_mappings
        groups.append(group)
    try:
        save_third_party_gateway_groups(groups, activate=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/sub2api/config")
async def save_sub2api_gateway_config(body: Sub2ApiGatewayBody) -> dict[str, Any]:
    """Compatibility alias for the generic third-party configuration route."""
    return await save_third_party_gateway_config(body)


@router.post("/third-party/models")
async def fetch_third_party_models(body: Sub2ApiModelsBody) -> dict[str, Any]:
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    protocol = normalize_gateway_protocol(body.protocol)
    if protocol not in SUB2API_PROTOCOLS:
        raise HTTPException(status_code=400, detail="protocol must be openai, gemini, or anthropic")
    base_url = str(body.base_url or "").strip().rstrip("/")
    parsed_base_url = urlsplit(base_url)
    if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
        raise HTTPException(status_code=400, detail="Base URL must use HTTP or HTTPS")
    existing = next(
        (group for group in get_third_party_gateway_groups() if group["id"] == body.id.strip()),
        None,
    )
    api_key = normalize_api_key(body.api_key)
    if not api_key and existing and existing["baseUrl"].rstrip("/") == base_url:
        api_key = str(existing.get("apiKey") or "")
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key is required to fetch models")

    endpoint, headers, params = model_discovery_request(protocol, base_url, api_key)
    models: list[str] = []
    seen: set[str] = set()
    try:
        with httpx.Client(
            trust_env=False,
            timeout=httpx.Timeout(20.0),
            follow_redirects=False,
        ) as client:
            for _page in range(10):
                response = client.get(endpoint, headers=headers, params=params)
                if response.status_code >= 400:
                    raise HTTPException(status_code=502, detail="Third-party gateway rejected model discovery")
                try:
                    payload = response.json()
                except ValueError:
                    raise HTTPException(status_code=502, detail="Third-party gateway returned an invalid model list") from None
                try:
                    page_models = extract_model_names(protocol, payload)
                except ValueError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                for model in page_models:
                    if model not in seen:
                        seen.add(model)
                        models.append(model)
                if protocol != "gemini" or not payload.get("nextPageToken"):
                    break
                params = {"pageSize": 1000, "pageToken": str(payload["nextPageToken"])}
    except HTTPException:
        raise
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Could not reach third-party gateway model discovery") from None
    return {"ok": True, "data": {"models": models}}


@router.post("/sub2api/models")
async def fetch_sub2api_models(body: Sub2ApiModelsBody) -> dict[str, Any]:
    return await fetch_third_party_models(body)


@router.post("/third-party/enable")
async def enable_third_party_gateway() -> dict[str, Any]:
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    status = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    if not status["thirdParty"]["configured"]:
        raise HTTPException(status_code=400, detail="At least one third-party gateway group is required")
    set_model_gateway_mode(MODE_CUSTOM)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/sub2api/enable")
async def enable_sub2api_gateway() -> dict[str, Any]:
    return await enable_third_party_gateway()


@router.post("/hybrid/enable")
async def enable_hybrid_gateway() -> dict[str, Any]:
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    status = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    if not status["official"]["configured"] or not status["thirdParty"]["configured"]:
        raise HTTPException(
            status_code=400,
            detail="Hybrid requires an official API key and at least one valid third-party gateway group",
        )
    set_model_gateway_mode(MODE_HYBRID)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/official/config")
async def save_official_gateway_config(body: OfficialGatewayBody) -> dict[str, Any]:
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    api_key = normalize_api_key(body.new_api_api_key)
    if not api_key:
        raise HTTPException(status_code=400, detail="newApiApiKey is required")
    save_official_newapi_key(api_key=api_key, activate=True)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/agent/config")
async def save_agent_gateway_config(body: AgentLlmConfigBody) -> dict[str, Any]:
    """Save the CE Agent route independently from media gateway selection."""
    try:
        require_ce_gateway_settings_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    if body.mode not in {AGENT_LLM_MODE_INHERIT, AGENT_LLM_MODE_THIRD_PARTY}:
        raise HTTPException(status_code=400, detail="unsupported Agent LLM mode")

    if body.mode == AGENT_LLM_MODE_THIRD_PARTY:
        settings = get_model_gateway_settings()
        saved_base_url = normalize_relay_base_url(
            settings.get("agent_llm_base_url", "")
        )
        base_url = normalize_relay_base_url(body.base_url or saved_base_url)
        api_key = normalize_api_key(body.api_key)
        model = str(body.model or settings.get("agent_llm_model", "")).strip()
        endpoint_changed = bool(body.base_url) and base_url != saved_base_url
        has_saved_key = bool(normalize_api_key(settings.get("agent_llm_api_key", "")))
        if not base_url:
            raise HTTPException(status_code=400, detail="baseUrl is required")
        if not model:
            raise HTTPException(status_code=400, detail="model is required")
        if not api_key and (not has_saved_key or endpoint_changed):
            raise HTTPException(status_code=400, detail="apiKey is required")
        save_agent_llm_config(
            mode=body.mode,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
    else:
        save_agent_llm_config(mode=body.mode)

    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/custom/brainclaw/config")
async def save_custom_brainclaw_config(
    body: BrainClawGatewayBody,
) -> dict[str, Any]:
    """Save the BrainClaw endpoint for Custom mode (does not switch the active mode)."""
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    current = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    api_key = normalize_api_key(body.new_api_api_key)
    base_url = normalize_relay_base_url(body.new_api_base_url)
    # A custom endpoint must carry its own key. The previous condition accepted
    # a non-empty apiKeyPreview as proof one existed, but the preview falls back
    # to the official key — so saving a custom URL with an empty key was
    # accepted, and every later request sent the official RelayClaw credential
    # to that host.
    from novelvideo.model_gateway_settings import _is_official_relay_url

    target_is_official = _is_official_relay_url(base_url or current["brainclaw"]["baseUrl"])
    has_dedicated_key = bool(current["brainclaw"].get("dedicatedKeyConfigured"))
    if not api_key and not has_dedicated_key and not target_is_official:
        raise HTTPException(
            status_code=400,
            detail="newApiApiKey is required for a custom BrainClaw endpoint")
    if not api_key and not current["brainclaw"]["apiKeyPreview"]:
        raise HTTPException(status_code=400, detail="newApiApiKey is required")
    if body.new_api_base_url is not None and not base_url:
        raise HTTPException(status_code=400, detail="newApiBaseUrl is required")
    save_relayclaw_brainclaw_key(
        api_key=api_key,
        base_url=base_url,
    )
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/custom/brainclaw/enable")
async def enable_custom_brainclaw() -> dict[str, Any]:
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    status = build_model_gateway_status(
        official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
        official_api_key=app_config.NEWAPI_API_KEY,
    )
    if not status["brainclaw"]["configured"]:
        raise HTTPException(
            status_code=400, detail="RelayClaw API key is not configured"
        )
    set_custom_llm_mode(CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/custom/llm-mode")
async def save_custom_llm_routing_mode(body: CustomLlmModeBody) -> dict[str, Any]:
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    if body.mode not in {
        CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
        CUSTOM_LLM_MODE_ADVANCED,
    }:
        raise HTTPException(status_code=400, detail="unsupported custom LLM mode")
    if body.mode == CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW:
        status = build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        )
        if not status["brainclaw"]["configured"]:
            raise HTTPException(
                status_code=400, detail="RelayClaw API key is not configured"
            )
    set_custom_llm_mode(body.mode)
    runtime = _refresh_runtime_after_gateway_write()
    return {
        "ok": True,
        "data": build_model_gateway_status(
            official_base_url=app_config.OFFICIAL_NEWAPI_BASE_URL,
            official_api_key=app_config.NEWAPI_API_KEY,
        ),
        "runtime": runtime,
    }


@router.post("/media-relay/config")
async def save_media_relay_settings(body: MediaRelayConfigBody) -> dict[str, Any]:
    try:
        require_ce_gateway_management()
    except PermissionError as exc:
        raise _permission_error(exc) from exc
    provider = body.provider.strip().lower()
    if provider not in {"aliyun_oss", "cloudinary", "minio"}:
        raise HTTPException(status_code=400, detail="unsupported media relay provider")
    if body.ttl_seconds <= 0:
        raise HTTPException(status_code=400, detail="ttlSeconds must be positive")
    if provider == "minio" and body.ttl_seconds > MINIO_MAX_PRESIGNED_TTL_SECONDS:
        raise HTTPException(
            status_code=400,
            detail="MinIO presigned URL TTL must not exceed 7 days",
        )
    current = get_effective_media_relay_config(
        env_provider=app_config.MEDIA_RELAY_PROVIDER,
        env_ttl_seconds=app_config.MEDIA_RELAY_TTL_SECONDS,
        env_endpoint=app_config.OSS_RELAY_ENDPOINT,
        env_bucket=app_config.OSS_RELAY_BUCKET,
        env_access_key_id=app_config.OSS_RELAY_AK,
        env_access_key_secret=app_config.OSS_RELAY_SK,
        env_cloud_name=app_config.CLOUDINARY_RELAY_CLOUD_NAME,
        env_cloudinary_api_key=app_config.CLOUDINARY_RELAY_API_KEY,
        env_cloudinary_api_secret=app_config.CLOUDINARY_RELAY_API_SECRET,
        env_cloudinary_folder=app_config.CLOUDINARY_RELAY_FOLDER,
        env_minio_endpoint=app_config.MINIO_RELAY_ENDPOINT,
        env_minio_public_endpoint=app_config.MINIO_RELAY_PUBLIC_ENDPOINT,
        env_minio_port=app_config.MINIO_RELAY_PORT,
        env_minio_use_ssl=app_config.MINIO_RELAY_USE_SSL,
        env_minio_bucket=app_config.MINIO_RELAY_BUCKET,
        env_minio_access_key=app_config.MINIO_RELAY_ACCESS_KEY,
        env_minio_secret_key=app_config.MINIO_RELAY_SECRET_KEY,
    )

    def merge_field(value: str | None, saved: str, *, secret: bool = False) -> str:
        if value is None:
            return saved
        normalized = value.strip()
        if secret and not normalized:
            return saved
        return normalized

    endpoint = (
        merge_field(body.endpoint, current.endpoint)
        if provider == "aliyun_oss"
        else current.endpoint
    )
    bucket = (
        merge_field(body.bucket, current.bucket)
        if provider == "aliyun_oss"
        else current.bucket
    )
    access_key_id = (
        merge_field(body.access_key_id, current.access_key_id, secret=True)
        if provider == "aliyun_oss"
        else current.access_key_id
    )
    access_key_secret = (
        merge_field(body.access_key_secret, current.access_key_secret, secret=True)
        if provider == "aliyun_oss"
        else current.access_key_secret
    )
    cloud_name = merge_field(body.cloud_name, current.cloud_name)
    cloudinary_api_key = merge_field(
        body.cloudinary_api_key, current.cloudinary_api_key, secret=True
    )
    cloudinary_api_secret = merge_field(
        body.cloudinary_api_secret, current.cloudinary_api_secret, secret=True
    )
    cloudinary_folder = merge_field(
        body.cloudinary_folder, current.cloudinary_folder
    ).strip("/")
    minio_endpoint = (
        merge_field(body.endpoint, current.minio_endpoint)
        if provider == "minio"
        else current.minio_endpoint
    )
    minio_public_endpoint = (
        merge_field(body.public_endpoint, current.minio_public_endpoint).rstrip("/")
        if provider == "minio"
        else current.minio_public_endpoint
    )
    minio_port = (
        body.port if body.port is not None else current.minio_port
    ) if provider == "minio" else current.minio_port
    minio_use_ssl = (
        body.use_ssl if body.use_ssl is not None else current.minio_use_ssl
    ) if provider == "minio" else current.minio_use_ssl
    minio_bucket = (
        merge_field(body.bucket, current.minio_bucket)
        if provider == "minio"
        else current.minio_bucket
    )
    minio_access_key = (
        merge_field(body.access_key_id, current.minio_access_key, secret=True)
        if provider == "minio"
        else current.minio_access_key
    )
    minio_secret_key = (
        merge_field(body.access_key_secret, current.minio_secret_key, secret=True)
        if provider == "minio"
        else current.minio_secret_key
    )
    if provider == "cloudinary":
        required = {
            "cloudName": cloud_name,
            "apiKey": cloudinary_api_key,
            "apiSecret": cloudinary_api_secret,
        }
    elif provider == "aliyun_oss":
        required = {
            "endpoint": endpoint,
            "bucket": bucket,
            "accessKeyId": access_key_id,
            "accessKeySecret": access_key_secret,
        }
    else:
        required = {
            "endpoint": minio_endpoint,
            "publicEndpoint": minio_public_endpoint,
            "bucket": minio_bucket,
            "accessKeyId": minio_access_key,
            "accessKeySecret": minio_secret_key,
        }
        if not 1 <= int(minio_port) <= 65535:
            raise HTTPException(status_code=400, detail="port must be between 1 and 65535")
        parsed_internal_endpoint = urlsplit(
            minio_endpoint if "://" in minio_endpoint else f"//{minio_endpoint}"
        )
        try:
            internal_port = parsed_internal_endpoint.port
        except ValueError:
            internal_port = -1
        if (
            not parsed_internal_endpoint.hostname
            or parsed_internal_endpoint.scheme not in {"", "http", "https"}
            or parsed_internal_endpoint.username is not None
            or parsed_internal_endpoint.password is not None
            or parsed_internal_endpoint.path not in {"", "/"}
            or parsed_internal_endpoint.query
            or parsed_internal_endpoint.fragment
            or internal_port == -1
            or (internal_port is not None and not 1 <= internal_port <= 65535)
        ):
            raise HTTPException(
                status_code=400,
                detail="endpoint must be a host or HTTP(S) origin without a path",
            )
        parsed_public_endpoint = urlsplit(minio_public_endpoint)
        try:
            public_port = parsed_public_endpoint.port
        except ValueError:
            public_port = -1
        if (
            parsed_public_endpoint.scheme != "https"
            or not parsed_public_endpoint.hostname
            or parsed_public_endpoint.username is not None
            or parsed_public_endpoint.password is not None
            or parsed_public_endpoint.path not in {"", "/"}
            or parsed_public_endpoint.query
            or parsed_public_endpoint.fragment
            or public_port == -1
            or (public_port is not None and not 1 <= public_port <= 65535)
        ):
            raise HTTPException(
                status_code=400,
                detail="publicEndpoint must be an HTTPS origin without a path",
            )
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise HTTPException(
            status_code=400, detail=f"missing fields: {', '.join(missing)}"
        )
    save_media_relay_config(
        provider=provider,
        ttl_seconds=body.ttl_seconds,
        endpoint=endpoint,
        bucket=bucket,
        access_key_id=access_key_id,
        access_key_secret=access_key_secret,
        cloud_name=cloud_name,
        cloudinary_api_key=cloudinary_api_key,
        cloudinary_api_secret=cloudinary_api_secret,
        cloudinary_folder=cloudinary_folder,
        minio_endpoint=minio_endpoint,
        minio_public_endpoint=minio_public_endpoint,
        minio_port=int(minio_port),
        minio_use_ssl=bool(minio_use_ssl),
        minio_bucket=minio_bucket,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
    )
    return {"ok": True, "data": _media_relay_status()}


def _newapi_admin_not_portable() -> None:
    raise HTTPException(
        status_code=410,
        detail="NewAPI administration is not portable to third-party gateways; manage channels in the selected gateway.",
    )


@router.post("/custom/newapi/init")
@router.post("/custom/newapi/provider-channels")
@router.delete("/custom/newapi/comfyui")
@router.get("/custom/newapi/channel-types")
@router.post("/custom/newapi/provider-channel/models")
@router.post("/custom/newapi/provider-channel/sync")
@router.post("/custom/newapi/channels")
@router.post("/custom/newapi/channels/batch")
@router.post("/custom/newapi/embedding-model")
@router.post("/custom/newapi/media-models")
async def legacy_newapi_admin_not_portable(_request: Request) -> None:
    _newapi_admin_not_portable()
