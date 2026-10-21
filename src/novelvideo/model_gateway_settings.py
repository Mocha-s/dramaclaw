"""Runtime model gateway settings.

CE persists the selected official or bundled-NewAPI gateway in local settings,
which are its sole runtime credential source. EE has a control-plane DSN and
keeps its deployment environment as the sole credential source.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from novelvideo.official_defaults import (
    DEFAULT_COGNEE_EMBEDDING_DIM,
    DEFAULT_COGNEE_EMBEDDING_MODEL,
    DEFAULT_COGNEE_EMBEDDING_PROVIDER,
    DEFAULT_EMBEDDING_BATCH_SIZE,
    OFFICIAL_NEWAPI_BASE_URL,
)
from novelvideo.official_media_catalog_schema import (
    catalog_version as _catalog_version,
    validate_official_media_catalog as _validate_official_media_catalog,
)
from novelvideo.shared.runtime_env import uses_local_ce_runtime
from novelvideo.sqlite_pragmas import configure_sqlite_connection

MODE_OFFICIAL = "official"
MODE_CUSTOM = "custom"
MODE_HYBRID = "hybrid"
MODE_SUB2API = "sub2api"
VALID_MODES = {MODE_OFFICIAL, MODE_CUSTOM, MODE_HYBRID, MODE_SUB2API}
CAPABILITY_TEXT = "text"
CAPABILITY_EMBEDDING = "embedding"
CAPABILITY_IMAGE = "image"
CAPABILITY_VIDEO = "video"
CAPABILITY_AUDIO = "audio"
SUB2API_CAPABILITIES = (
    CAPABILITY_TEXT,
    CAPABILITY_EMBEDDING,
    CAPABILITY_IMAGE,
    CAPABILITY_VIDEO,
    CAPABILITY_AUDIO,
)
SUB2API_PROTOCOLS = {"openai", "gemini"}
SUB2API_IMAGE_EDIT_FORMATS = {
    "dc-media",
    "images",
    "input_reference",
    "multipart",
}
SUB2API_VIDEO_ENDPOINTS = {"videos", "video/generations"}
CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW = "relayclaw_brainclaw"
CUSTOM_LLM_MODE_ADVANCED = "advanced"
VALID_CUSTOM_LLM_MODES = {
    CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
    CUSTOM_LLM_MODE_ADVANCED,
}
AGENT_LLM_MODE_INHERIT = "inherit"
AGENT_LLM_MODE_THIRD_PARTY = "third_party"
VALID_AGENT_LLM_MODES = {AGENT_LLM_MODE_INHERIT, AGENT_LLM_MODE_THIRD_PARTY}
PLACEHOLDER_API_KEYS = {
    "your_newapi_token",
    "your_model_api_key",
    "your_api_key",
    "your_dc_key",
}
OFFICIAL_MEDIA_CATALOG_AUTO_UPDATE_KEY = "official_media_catalog_auto_update"
OFFICIAL_MEDIA_CATALOG_LAST_CHECKED_KEY = "official_media_catalog_last_checked_at"
OFFICIAL_MEDIA_CATALOG_REMOTE_URL_KEY = "official_media_catalog_remote_url"
OFFICIAL_MEDIA_CATALOG_ETAG_KEY = "official_media_catalog_etag"
OFFICIAL_MEDIA_CATALOG_REVISION_KEY = "official_media_catalog_revision"
OFFICIAL_MEDIA_CATALOG_PUBLISHED_AT_KEY = "official_media_catalog_published_at"
OFFICIAL_MEDIA_CATALOG_SHA256_KEY = "official_media_catalog_sha256"
OFFICIAL_MEDIA_CATALOG_LAST_ERROR_KEY = "official_media_catalog_last_error"
_OFFICIAL_MEDIA_CATALOG_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True)
class EffectiveNewApiConfig:
    mode: str
    source: str
    base_url: str
    api_key: str
    protocol: str = "openai"
    model: str = ""
    native_base_url: str = ""


@dataclass(frozen=True)
class EffectiveLlmConfig:
    mode: str
    source: str
    base_url: str
    api_key: str
    model: str
    is_brainclaw: bool


@dataclass(frozen=True)
class EffectiveMediaRelayConfig:
    source: str
    provider: str
    ttl_seconds: int
    endpoint: str
    bucket: str
    access_key_id: str
    access_key_secret: str
    cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = ""
    minio_endpoint: str = ""
    minio_public_endpoint: str = ""
    minio_port: int = 9000
    minio_use_ssl: bool = False
    minio_bucket: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""


@dataclass(frozen=True)
class EffectiveCogneeEmbeddingConfig:
    source: str
    provider: str
    model: str
    dimensions: str
    upstream_provider: str
    upstream_model: str
    batch_size: str = ""


def mask_secret(value: str) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    if len(clean) <= 10:
        return "*" * len(clean)
    return f"{clean[:4]}...{clean[-4:]}"


def normalize_api_key(value: str | None) -> str:
    clean = str(value or "").strip()
    if not clean:
        return ""
    lowered = clean.lower()
    if lowered in PLACEHOLDER_API_KEYS:
        return ""
    if lowered.startswith("your_") or lowered.startswith("<your_"):
        return ""
    return clean


def normalize_gateway_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_MODES else MODE_OFFICIAL


def normalize_capability(value: str | None) -> str:
    capability = str(value or CAPABILITY_TEXT).strip().lower()
    if capability not in SUB2API_CAPABILITIES:
        raise ValueError(f"unsupported model capability: {capability}")
    return capability


def _normalize_sub2api_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        raise ValueError("Sub2API groups must be a list")
    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    names: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("each Sub2API group must be an object")
        group_id = str(group.get("id") or "").strip()
        name = str(group.get("name") or "").strip()
        protocol = str(group.get("protocol") or "").strip().lower()
        base_url = normalize_sub2api_base_url(str(group.get("baseUrl") or ""))
        api_key = normalize_api_key(str(group.get("apiKey") or ""))
        raw_capabilities = group.get("capabilities", [])
        raw_models = group.get("models", [])
        raw_mappings = group.get("modelMappings")
        if not isinstance(raw_capabilities, list) or not isinstance(raw_models, list):
            raise ValueError("Sub2API capabilities and models must be lists")
        capabilities = sorted({normalize_capability(value) for value in raw_capabilities})
        if raw_mappings is None:
            mappings = [
                {"requestPattern": str(value or "").strip(), "upstreamModel": str(value or "").strip()}
                for value in raw_models
            ]
        elif isinstance(raw_mappings, list):
            mappings = []
            for item in raw_mappings:
                if not isinstance(item, dict):
                    continue
                mapping = {
                    "requestPattern": str(item.get("requestPattern") or "").strip(),
                    "upstreamModel": str(item.get("upstreamModel") or "").strip(),
                }
                image_edit_format = str(item.get("imageEditFormat") or "").strip().lower()
                if image_edit_format:
                    if image_edit_format not in SUB2API_IMAGE_EDIT_FORMATS:
                        raise ValueError(
                            "unsupported Sub2API image edit format: "
                            + image_edit_format
                        )
                    mapping["imageEditFormat"] = image_edit_format
                video_endpoint = str(item.get("videoEndpoint") or "").strip().strip("/").lower()
                if video_endpoint:
                    if video_endpoint not in SUB2API_VIDEO_ENDPOINTS:
                        raise ValueError(
                            "unsupported Sub2API video endpoint: " + video_endpoint
                        )
                    mapping["videoEndpoint"] = video_endpoint
                mappings.append(mapping)
        else:
            raise ValueError("Sub2API modelMappings must be a list")
        mappings = list({(item["requestPattern"], item["upstreamModel"]): item for item in mappings if item["requestPattern"] and item["upstreamModel"]}.values())
        if not group_id or not name or not base_url or not api_key:
            raise ValueError("Sub2API groups require id, name, baseUrl, and apiKey")
        if protocol not in SUB2API_PROTOCOLS:
            raise ValueError("unsupported Sub2API protocol")
        parsed_base_url = urlsplit(base_url)
        if parsed_base_url.scheme not in {"http", "https"} or not parsed_base_url.netloc:
            raise ValueError("Sub2API Base URL must use HTTP or HTTPS")
        if not capabilities or not mappings:
            raise ValueError("Sub2API groups require capabilities and models")
        if group_id in ids or name.casefold() in names:
            raise ValueError("Sub2API group ids and names must be unique")
        if any("*" in item["requestPattern"] and not item["requestPattern"].endswith("*") for item in mappings):
            raise ValueError("Sub2API model patterns only support a trailing *")
        ids.add(group_id)
        names.add(name.casefold())
        normalized.append(
            {
                "id": group_id,
                "name": name,
                "protocol": protocol,
                "baseUrl": base_url,
                "apiKey": api_key,
                "capabilities": capabilities,
                "modelMappings": mappings,
            }
        )
    return normalized


def save_sub2api_groups(groups: list[dict[str, Any]], *, activate: bool = False) -> None:
    normalized = _normalize_sub2api_groups(groups)
    values = {
        "sub2api_groups": json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ),
        "sub2api_base_url": "",
        **{f"sub2api_api_key_{capability}": "" for capability in SUB2API_CAPABILITIES},
    }
    if activate:
        values["model_gateway_mode"] = MODE_SUB2API
    _write_many(values)


def get_sub2api_groups(*, masked: bool = False) -> list[dict[str, Any]]:
    raw = get_model_gateway_settings().get("sub2api_groups", "")
    try:
        groups = json.loads(raw) if raw else []
    except json.JSONDecodeError:
        return []
    if not isinstance(groups, list):
        return []
    if not groups:
        # Migrate settings written by the first Sub2API version in memory.
        settings = get_model_gateway_settings()
        legacy_url = normalize_sub2api_base_url(settings.get("sub2api_base_url", ""))
        groups = [
            {
                "id": capability,
                "name": capability.title(),
                "protocol": "openai",
                "baseUrl": legacy_url,
                "apiKey": settings.get(f"sub2api_api_key_{capability}", ""),
                "capabilities": [capability],
                "models": ["*"],
            }
            for capability in SUB2API_CAPABILITIES
            if settings.get(f"sub2api_api_key_{capability}")
        ]
    result: list[dict[str, Any]] = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        item = dict(group)
        if masked:
            item["apiKeyPreview"] = mask_secret(str(item.pop("apiKey", "")))
        result.append(item)
    return result


def _resolve_sub2api_group(
    *, capability: str, model: str
) -> dict[str, Any] | None:
    capability = normalize_capability(capability)
    wanted_model = str(model or "").strip()
    matches: list[tuple[int, dict[str, Any], str]] = []
    for group in get_sub2api_groups():
        if capability not in group.get("capabilities", []):
            continue
        mappings = group.get("modelMappings") or [
            {"requestPattern": model, "upstreamModel": model}
            for model in group.get("models", [])
        ]
        for mapping in mappings:
            pattern = str(mapping.get("requestPattern") or "").strip()
            upstream_model = str(mapping.get("upstreamModel") or "").strip()
            if not pattern or not upstream_model:
                continue
            if pattern == "*":
                matches.append((0, group, wanted_model if upstream_model == "*" else upstream_model))
            elif pattern.endswith("*") and wanted_model.startswith(pattern[:-1]):
                matches.append(
                    (
                        len(pattern) - 1,
                        group,
                        wanted_model if upstream_model == "*" else upstream_model,
                    )
                )
            elif pattern == wanted_model:
                matches.append(
                    (10**9, group, wanted_model if upstream_model == "*" else upstream_model)
                )
    if not matches and not wanted_model:
        defaults = [
            (group, str(mapping.get("upstreamModel") or ""))
            for group in get_sub2api_groups()
            if capability in group.get("capabilities", [])
            for mapping in (group.get("modelMappings") or [])
            if mapping.get("requestPattern") == "*"
        ]
        if not defaults:
            candidates = [
                (group, mapping)
                for group in get_sub2api_groups()
                if capability in group.get("capabilities", [])
                for mapping in (group.get("modelMappings") or [])
            ]
            if len(candidates) == 1:
                return candidates[0][0], str(candidates[0][1].get("upstreamModel") or "")
        return defaults[0] if len(defaults) == 1 else None
    if not matches:
        return None
    best_score = max(score for score, _group, _model in matches)
    best_matches = [
        (group, upstream_model)
        for score, group, upstream_model in matches
        if score == best_score
    ]
    if len(best_matches) != 1:
        return None
    return best_matches[0]


def normalize_custom_llm_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_CUSTOM_LLM_MODES else CUSTOM_LLM_MODE_ADVANCED


def normalize_agent_llm_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in VALID_AGENT_LLM_MODES else AGENT_LLM_MODE_INHERIT


def normalize_relay_base_url(value: str | None) -> str:
    base = str(value or "").strip().rstrip("/")
    if not base:
        return ""
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def normalize_sub2api_base_url(value: str | None) -> str:
    """Preserve Sub2API version paths such as /v1, /api/v3, and /v1beta."""
    return str(value or "").strip().rstrip("/")


def _sub2api_openai_compat_base_url(group: dict[str, Any]) -> str:
    base_url = normalize_sub2api_base_url(str(group.get("baseUrl") or ""))
    protocol = str(group.get("protocol") or "").strip().lower()
    if protocol == "gemini" and base_url.endswith("/v1beta"):
        base_url = base_url[: -len("/v1beta")]
    if base_url.endswith(("/v1", "/v3", "/api/v1", "/api/v3")):
        return base_url
    return f"{base_url}/v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _settings_db_path() -> Path:
    from novelvideo import config

    return Path(config.STATE_DIR) / "local" / "settings.db"


def _connect() -> sqlite3.Connection:
    path = _settings_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(3):
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            configure_sqlite_connection(conn)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """)
            conn.commit()
            return conn
        except sqlite3.OperationalError as exc:
            if conn is not None:
                conn.close()
            retryable = any(
                marker in str(exc).lower()
                for marker in (
                    "disk i/o error",
                    "database is locked",
                    "database is busy",
                )
            )
            if not retryable or attempt == 2:
                raise
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            if conn is not None:
                conn.close()
            raise
    raise RuntimeError("failed to open model gateway settings database")


def _read_all() -> dict[str, str]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT key, value FROM runtime_settings").fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}
    finally:
        conn.close()


def _uses_ce_gateway_settings() -> bool:
    """Return whether this process owns the CE-local gateway settings database."""
    return uses_local_ce_runtime()


def _write_many(values: dict[str, str]) -> None:
    now = _now_iso()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for key, value in values.items():
            conn.execute(
                """
                INSERT INTO runtime_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value or ""), now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_model_gateway_mode(mode: str) -> None:
    _write_many({"model_gateway_mode": normalize_gateway_mode(mode)})


def set_custom_llm_mode(mode: str) -> None:
    """Choose how Custom mode routes LLM traffic.

    This is a setting *inside* Custom mode: it only matters while
    ``model_gateway_mode`` is ``custom``, and choosing it never activates
    Custom mode. Official and Hybrid always use BrainClaw and ignore it.
    """
    _write_many({"custom_llm_mode": normalize_custom_llm_mode(mode)})


def save_relayclaw_brainclaw_key(
    *,
    api_key: str = "",
    base_url: str = "",
) -> None:
    """Persist the BrainClaw LLM endpoint and select BrainClaw for Custom mode.

    Like :func:`set_custom_llm_mode`, this does not change the active gateway
    mode; activating Custom stays with the explicit enable action.
    """
    values = {"custom_llm_mode": CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW}
    clean_api_key = str(api_key or "").strip()
    clean_base_url = normalize_relay_base_url(base_url)
    if clean_api_key:
        values["brainclaw_newapi_api_key"] = clean_api_key
    if clean_base_url:
        values["brainclaw_newapi_base_url"] = clean_base_url
    _write_many(values)


def save_agent_llm_config(
    *, mode: str, base_url: str = "", api_key: str = "", model: str = ""
) -> None:
    """Persist an Agent-only LLM route without changing media gateway mode."""
    normalized_mode = normalize_agent_llm_mode(mode)
    values = {"agent_llm_mode": normalized_mode}
    if normalized_mode == AGENT_LLM_MODE_THIRD_PARTY:
        clean_base_url = normalize_relay_base_url(base_url)
        clean_api_key = normalize_api_key(api_key)
        clean_model = str(model or "").strip()
        if clean_base_url:
            values["agent_llm_base_url"] = clean_base_url
        if clean_api_key:
            values["agent_llm_api_key"] = clean_api_key
        if clean_model:
            values["agent_llm_model"] = clean_model
    _write_many(values)


def save_official_newapi_key(
    *,
    api_key: str,
    activate: bool = True,
) -> None:
    values = {
        "official_newapi_api_key": str(api_key or "").strip(),
    }
    if activate:
        values["model_gateway_mode"] = MODE_OFFICIAL
    _write_many(values)


def save_custom_newapi_gateway(
    *,
    base_url: str,
    api_key: str,
    admin_base_url: str = "",
    token_name: str = "",
    token_id: int | str = "",
    activate: bool = True,
) -> None:
    values = {
        "custom_newapi_base_url": normalize_relay_base_url(base_url),
        "custom_newapi_api_key": str(api_key or "").strip(),
        "custom_newapi_admin_base_url": str(admin_base_url or "").strip().rstrip("/"),
        "custom_newapi_token_name": str(token_name or "").strip(),
        "custom_newapi_token_id": str(token_id or "").strip(),
    }
    if activate:
        values["model_gateway_mode"] = MODE_CUSTOM
    _write_many(values)


def save_sub2api_gateway(
    *,
    base_url: str,
    keys: dict[str, str],
    activate: bool = False,
) -> None:
    groups = [
        {
            "id": capability,
            "name": capability.title(),
            "protocol": "openai",
            "baseUrl": normalize_sub2api_base_url(base_url),
            "apiKey": keys.get(capability, ""),
            "capabilities": [capability],
            "models": ["*"],
        }
        for capability in SUB2API_CAPABILITIES
        if normalize_api_key(keys.get(capability, ""))
    ]
    save_sub2api_groups(groups, activate=activate)


def save_newapi_database_config(
    *,
    sql_dsn: str,
    sqlite_path: str = "",
    admin_username: str = "",
) -> None:
    _write_many(
        {
            "custom_newapi_db_sql_dsn": str(sql_dsn or "").strip(),
            "custom_newapi_db_sqlite_path": str(sqlite_path or "").strip(),
            "custom_newapi_admin_username": str(admin_username or "").strip(),
        }
    )


def _decode_provider_channels(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    channels: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        channels.append(
            {
                "provider": provider,
                "type": max(0, int(item.get("type") or 0)),
                "upstreamKey": str(item.get("upstreamKey") or "").strip(),
                "baseUrl": str(item.get("baseUrl") or "").strip().rstrip("/"),
                "priority": int(item.get("priority") or 0),
                "settings": (
                    item.get("settings")
                    if isinstance(item.get("settings"), dict)
                    else {}
                ),
            }
        )
    return channels


def _decode_media_model_mappings(value: str | None) -> dict[str, dict[str, Any]]:
    if not value:
        return {}
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}

    mappings: dict[str, dict[str, Any]] = {}
    for model, item in raw.items():
        model_name = str(model or "").strip()
        if not model_name or not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider:
            continue
        media_type = str(item.get("mediaType") or "").strip().lower()
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        mapping: dict[str, Any] = {
            "provider": provider,
            "upstreamModel": str(item.get("upstreamModel") or "").strip(),
        }
        if media_type in {"image", "video", "audio"}:
            mapping["mediaType"] = media_type
        if str(item.get("label") or "").strip():
            mapping["label"] = str(item.get("label") or "").strip()
        if "enabled" in item:
            mapping["enabled"] = item.get("enabled") is not False
        if "sortOrder" in item:
            mapping["sortOrder"] = int(item.get("sortOrder") or 100)
        if config:
            mapping["config"] = config
        mappings[model_name] = mapping
    return mappings


def _decode_embedding_model_config(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}

    provider = str(raw.get("provider") or "").strip().lower()
    upstream_model = str(raw.get("upstreamModel") or "").strip()
    dimensions = _int_setting(
        str(raw.get("dimension") or raw.get("dimensions") or ""), 0
    )
    batch_size = _int_setting(
        str(raw.get("batchSize") or raw.get("batch_size") or ""), 0
    )
    if not provider or not upstream_model or dimensions <= 0:
        return {}
    result: dict[str, Any] = {
        "provider": provider,
        "upstreamModel": upstream_model,
        "dimension": dimensions,
        # Retain the field for API compatibility, but request behavior is an
        # internal model contract and cannot be disabled by saved CE settings.
        "sendDimensions": True,
        "internalModel": "DC-cognee-embedding",
    }
    if batch_size > 0:
        result["batchSize"] = batch_size
    return result


def get_newapi_provider_channels() -> list[dict[str, Any]]:
    settings = get_model_gateway_settings()
    return _decode_provider_channels(settings.get("custom_newapi_provider_channels"))


def get_newapi_provider_channel(provider: str) -> dict[str, Any] | None:
    wanted = str(provider or "").strip().lower()
    if not wanted:
        return None
    for channel in get_newapi_provider_channels():
        if channel["provider"] == wanted:
            return channel
    return None


def parse_comfyui_channel_workflows(
    settings: dict[str, Any],
) -> tuple[list[str], list[str]]:
    comfyui = settings.get("comfyui")
    if not isinstance(comfyui, dict):
        raise ValueError("ComfyUI settings are required")
    routes = comfyui.get("workflow_routes")
    if routes is not None:
        if not isinstance(routes, list) or not routes:
            raise ValueError("ComfyUI requires at least one workflow route")
        route_ids: list[str] = []
        configured_model = str(comfyui.get("model_name") or "").strip()
        models: set[str] = {configured_model} if configured_model else set()
        for route in routes:
            if not isinstance(route, dict):
                raise ValueError("each ComfyUI workflow route must be an object")
            route_id = str(route.get("id") or "").strip()
            workflow = route.get("workflow")
            match = route.get("match")
            route_models = match.get("models") if isinstance(match, dict) else None
            if not route_id or route_id in route_ids:
                raise ValueError("each ComfyUI workflow route requires a unique id")
            if route_models is not None:
                if (
                    not isinstance(route_models, list)
                    or len(route_models) != 1
                    or not str(route_models[0] or "").strip()
                ):
                    raise ValueError(
                        "each ComfyUI workflow route accepts at most one model name"
                    )
                models.add(str(route_models[0]).strip())
            if not isinstance(workflow, dict) or not workflow:
                raise ValueError(
                    "each ComfyUI workflow route requires an API Format JSON object"
                )
            if not any(
                isinstance(node, dict) and ("class_type" in node or "inputs" in node)
                for node in workflow.values()
            ):
                raise ValueError(
                    f"ComfyUI workflow {route_id} must use exported API Format"
                )
            route_ids.append(route_id)
        if len(models) != 1:
            raise ValueError("a ComfyUI channel supports one model name")
        return sorted(models), route_ids

    workflows = comfyui.get("workflow_by_model")
    if not isinstance(workflows, dict) or not workflows:
        raise ValueError("ComfyUI requires at least one model workflow")
    for model, workflow in workflows.items():
        if (
            not str(model or "").strip()
            or not isinstance(workflow, dict)
            or not workflow
        ):
            raise ValueError(
                "each ComfyUI workflow requires a model name and JSON object"
            )
        if not any(
            isinstance(node, dict) and ("class_type" in node or "inputs" in node)
            for node in workflow.values()
        ):
            raise ValueError(
                f"ComfyUI workflow for {model} must use exported API Format"
            )
    return (
        [str(model).strip() for model in workflows],
        [str(model) for model in workflows],
    )


def save_newapi_provider_channels(
    channels: list[dict[str, Any]],
    *,
    preserve_unmentioned: bool = False,
) -> list[dict[str, Any]]:
    current_settings = get_model_gateway_settings()
    existing_channels = _decode_provider_channels(
        current_settings.get("custom_newapi_provider_channels")
    )
    existing_by_provider = {
        channel["provider"]: channel for channel in existing_channels
    }
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in channels:
        provider = str(item.get("provider") or "").strip().lower()
        if not provider or provider in seen:
            continue
        seen.add(provider)
        previous = existing_by_provider.get(provider, {})
        upstream_key = str(item.get("upstreamKey") or "").strip() or previous.get(
            "upstreamKey",
            "",
        )
        base_url = str(item.get("baseUrl") or "").strip().rstrip("/")
        channel_type = max(
            0,
            int(item.get("type") or previous.get("type") or 0),
        )
        if provider == "comfyui" and channel_type == 0:
            channel_type = 63
        raw_priority = item.get("priority")
        priority = int(
            previous.get("priority", 0) if raw_priority is None else raw_priority
        )
        raw_settings = item.get("settings", previous.get("settings", {}))
        channel_settings = raw_settings if isinstance(raw_settings, dict) else {}
        if provider == "comfyui":
            if not base_url:
                raise ValueError("baseUrl is required for provider comfyui")
            parse_comfyui_channel_workflows(channel_settings)
        if not upstream_key and provider != "comfyui":
            raise ValueError(f"upstreamKey is required for provider {provider}")
        normalized.append(
            {
                "provider": provider,
                "type": channel_type,
                "upstreamKey": upstream_key,
                "baseUrl": base_url,
                "priority": priority,
                "settings": channel_settings,
            }
        )
    if preserve_unmentioned:
        normalized.extend(
            channel
            for provider, channel in existing_by_provider.items()
            if provider not in seen
        )
    values = {
        "custom_newapi_provider_channels": json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    }
    if not preserve_unmentioned:
        remaining_providers = {channel["provider"] for channel in normalized}
        removed_providers = set(existing_by_provider) - remaining_providers
        if removed_providers:
            media_mappings = _decode_media_model_mappings(
                current_settings.get("custom_newapi_media_model_mappings")
            )
            media_mappings = {
                model: mapping
                for model, mapping in media_mappings.items()
                if mapping.get("provider") not in removed_providers
            }
            values["custom_newapi_media_model_mappings"] = json.dumps(
                media_mappings,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            embedding_model = _decode_embedding_model_config(
                current_settings.get("custom_newapi_embedding_model")
            )
            if embedding_model.get("provider") in removed_providers:
                values["custom_newapi_embedding_model"] = "{}"
    _write_many(values)
    return normalized


def get_newapi_media_model_mappings() -> dict[str, dict[str, Any]]:
    if not _uses_ce_gateway_settings():
        return {}
    settings = get_model_gateway_settings()
    return _decode_media_model_mappings(
        settings.get("custom_newapi_media_model_mappings")
    )


def save_newapi_media_model_mappings(
    mappings: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    from novelvideo.media_model_request_schema import (
        normalize_media_model_catalog_config,
        validate_media_model_catalog_config,
    )

    normalized: dict[str, dict[str, Any]] = {}
    for model, item in mappings.items():
        model_name = str(model or "").strip()
        if not model_name:
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if not provider:
            raise ValueError(f"provider is required for media model {model_name}")
        media_type = str(item.get("mediaType") or "").strip().lower()
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        if media_type in {"image", "video"}:
            config = normalize_media_model_catalog_config(config)
            validate_media_model_catalog_config(config, media_type)
        normalized_item: dict[str, Any] = {
            "provider": provider,
            "upstreamModel": str(item.get("upstreamModel") or "").strip(),
        }
        if media_type in {"image", "video", "audio"}:
            normalized_item["mediaType"] = media_type
        label = str(item.get("label") or "").strip()
        if label:
            normalized_item["label"] = label
        if "enabled" in item:
            normalized_item["enabled"] = item.get("enabled") is not False
        if "sortOrder" in item:
            normalized_item["sortOrder"] = int(item.get("sortOrder") or 100)
        if config:
            normalized_item["config"] = config
        normalized[model_name] = normalized_item
    _write_many(
        {
            "custom_newapi_media_model_mappings": json.dumps(
                normalized,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        }
    )
    return normalized


def build_newapi_media_model_mappings_status() -> dict[str, dict[str, Any]]:
    return get_newapi_media_model_mappings()


def _official_media_catalog_bundle_path() -> Path:
    return Path(__file__).with_name("official_media_models.json")


def _official_media_catalog_cache_path() -> Path:
    from novelvideo import config

    return Path(config.STATE_DIR) / "local" / "official_media_models.json"


def _read_official_media_catalog(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("official media model configuration is invalid") from exc
    try:
        return _validate_official_media_catalog(payload)
    except ValueError as exc:
        raise RuntimeError("official media model configuration is invalid") from exc


def _effective_official_media_catalog() -> tuple[dict[str, Any], str]:
    bundled = _read_official_media_catalog(_official_media_catalog_bundle_path())
    cache_path = _official_media_catalog_cache_path()
    if cache_path.is_file():
        try:
            cached = _read_official_media_catalog(cache_path)
            if _catalog_version(cached) >= _catalog_version(bundled):
                return cached, "remote"
        except RuntimeError:
            pass
    return bundled, "bundled"


def _official_media_catalog_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_official_media_catalog_update_status() -> dict[str, Any]:
    settings = _read_all()
    payload, source = _effective_official_media_catalog()
    digest = _official_media_catalog_digest(payload)
    metadata_matches = settings.get(OFFICIAL_MEDIA_CATALOG_SHA256_KEY) == digest
    return {
        "autoUpdate": settings.get(OFFICIAL_MEDIA_CATALOG_AUTO_UPDATE_KEY, "0")
        != "0",
        "source": source,
        "schemaVersion": int(payload.get("version") or 1),
        "catalogVersion": str(
            payload.get("catalogVersion") or payload.get("version") or "1"
        ),
        "modelCount": len(payload["mediaModels"]),
        "lastCheckedAt": settings.get(OFFICIAL_MEDIA_CATALOG_LAST_CHECKED_KEY, ""),
        "sha256": digest,
        "revision": (
            settings.get(OFFICIAL_MEDIA_CATALOG_REVISION_KEY, "")
            if metadata_matches
            else ""
        ),
        "publishedAt": (
            settings.get(OFFICIAL_MEDIA_CATALOG_PUBLISHED_AT_KEY, "")
            if metadata_matches
            else ""
        ),
        "remoteUrl": settings.get(OFFICIAL_MEDIA_CATALOG_REMOTE_URL_KEY, ""),
        "lastError": settings.get(OFFICIAL_MEDIA_CATALOG_LAST_ERROR_KEY, ""),
    }


def save_official_media_catalog_auto_update(enabled: bool) -> dict[str, Any]:
    _write_many({OFFICIAL_MEDIA_CATALOG_AUTO_UPDATE_KEY: "1" if enabled else "0"})
    return get_official_media_catalog_update_status()


def get_official_media_catalog_remote_etag(source_url: str) -> str:
    settings = _read_all()
    if settings.get(OFFICIAL_MEDIA_CATALOG_REMOTE_URL_KEY) != str(source_url).strip():
        return ""
    payload, _source = _effective_official_media_catalog()
    if settings.get(OFFICIAL_MEDIA_CATALOG_SHA256_KEY) != _official_media_catalog_digest(
        payload
    ):
        return ""
    return settings.get(OFFICIAL_MEDIA_CATALOG_ETAG_KEY, "")


def record_official_media_catalog_check(
    *, source_url: str, etag: str = "", error: str = ""
) -> dict[str, Any]:
    values = {
        OFFICIAL_MEDIA_CATALOG_LAST_CHECKED_KEY: _now_iso(),
        OFFICIAL_MEDIA_CATALOG_REMOTE_URL_KEY: str(source_url or "").strip(),
        OFFICIAL_MEDIA_CATALOG_LAST_ERROR_KEY: str(error or "").strip()[:500],
        OFFICIAL_MEDIA_CATALOG_ETAG_KEY: str(etag or "").strip(),
    }
    _write_many(values)
    return get_official_media_catalog_update_status()


def install_official_media_catalog(
    payload: dict[str, Any],
    *,
    source_url: str,
    expected_sha256: str = "",
    revision: str = "",
    published_at: str = "",
    etag: str = "",
) -> tuple[bool, dict[str, Any]]:
    validated = _validate_official_media_catalog(payload)
    candidate_digest = _official_media_catalog_digest(validated)
    normalized_expected_digest = str(expected_sha256 or "").strip().lower()
    if normalized_expected_digest and candidate_digest != normalized_expected_digest:
        raise ValueError("official media catalog SHA256 does not match manifest")
    with _OFFICIAL_MEDIA_CATALOG_WRITE_LOCK:
        current, _source = _effective_official_media_catalog()
        candidate_version = _catalog_version(validated)
        current_version = _catalog_version(current)
        current_digest = _official_media_catalog_digest(current)
        if candidate_version < current_version:
            raise ValueError("official media catalog downgrade is not allowed")
        if candidate_version == current_version and candidate_digest != current_digest:
            raise ValueError(
                "official media catalog version already exists with different content"
            )
        updated = candidate_digest != current_digest
        if updated:
            cache_path = _official_media_catalog_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=cache_path.parent,
                    prefix=f".{cache_path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(
                        json.dumps(validated, ensure_ascii=False, indent=2) + "\n"
                    )
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                temporary_path.replace(cache_path)
            finally:
                if temporary_path is not None:
                    temporary_path.unlink(missing_ok=True)
    _write_many(
        {
            OFFICIAL_MEDIA_CATALOG_LAST_CHECKED_KEY: _now_iso(),
            OFFICIAL_MEDIA_CATALOG_REMOTE_URL_KEY: str(source_url or "").strip(),
            OFFICIAL_MEDIA_CATALOG_ETAG_KEY: str(etag or "").strip(),
            OFFICIAL_MEDIA_CATALOG_REVISION_KEY: str(revision or "").strip(),
            OFFICIAL_MEDIA_CATALOG_PUBLISHED_AT_KEY: str(published_at or "").strip(),
            OFFICIAL_MEDIA_CATALOG_SHA256_KEY: candidate_digest,
            OFFICIAL_MEDIA_CATALOG_LAST_ERROR_KEY: "",
        }
    )
    return updated, get_official_media_catalog_update_status()


def get_official_media_model_mappings() -> dict[str, dict[str, Any]]:
    payload, _source = _effective_official_media_catalog()
    models = payload["mediaModels"]
    return {
        str(model): dict(item)
        for model, item in models.items()
        if str(model).strip() and isinstance(item, dict)
    }


def _media_model_catalog(
    mappings: dict[str, dict[str, Any]],
    media_type: str,
    *,
    provider: str | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    from novelvideo.media_model_request_schema import normalize_media_model_catalog_config

    wanted = str(media_type or "").strip().lower()
    if wanted not in {"image", "video"}:
        return []
    result: list[dict[str, Any]] = []
    for model, item in mappings.items():
        if provider and item.get("provider") != provider:
            continue
        disabled = item.get("enabled") is False
        if item.get("mediaType") != wanted or (disabled and not include_disabled):
            continue
        config = item.get("config") if isinstance(item.get("config"), dict) else {}
        config = normalize_media_model_catalog_config(config)
        config.setdefault(
            "request",
            {
                "endpoint": (
                    "images/generations" if wanted == "image" else "video/generations"
                ),
                "parameters": [],
            },
        )
        gateway_model = str(item.get("upstreamModel") or model)
        api_model = model if wanted == "image" else f"newapi_{model}"
        aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        result.append(
            {
                **config,
                "catalogId": model,
                "catalog_id": model,
                "id": model,
                "providerId": "newapi",
                "provider": "newapi",
                "apiModel": api_model,
                "api_model": api_model,
                "gatewayModel": gateway_model,
                "gateway_model": gateway_model,
                "aliases": [str(alias) for alias in aliases if str(alias).strip()],
                "label": str(item.get("label") or model),
                "sortOrder": int(item.get("sortOrder") or 100),
                **({"enabled": False} if disabled else {}),
            }
        )
    return sorted(result, key=lambda entry: (int(entry["sortOrder"]), str(entry["id"])))


def get_official_media_model_catalog(media_type: str) -> list[dict[str, Any]]:
    return _media_model_catalog(get_official_media_model_mappings(), media_type)


def get_bundled_media_model_catalog(media_type: str) -> list[dict[str, Any]]:
    """Read release-bundled capabilities without local settings or update caches."""
    payload = _read_official_media_catalog(_official_media_catalog_bundle_path())
    return _media_model_catalog(payload["mediaModels"], media_type)


def get_ce_media_model_catalog(
    media_type: str,
    *,
    provider: str | None = None,
    include_disabled: bool = False,
) -> list[dict[str, Any]]:
    """Expose CE-local media settings using the EE catalog response contract."""
    return _media_model_catalog(
        get_newapi_media_model_mappings(),
        media_type,
        provider=provider,
        include_disabled=include_disabled,
    )


def get_sub2api_media_model_catalog(media_type: str) -> list[dict[str, Any]]:
    capability = str(media_type or "").strip().lower()
    if capability not in {CAPABILITY_IMAGE, CAPABILITY_VIDEO}:
        return []
    catalog: list[dict[str, Any]] = []
    for group in get_sub2api_groups(masked=True):
        if capability not in group.get("capabilities", []):
            continue
        for mapping in group.get("modelMappings", []):
            request_model = str(mapping.get("requestPattern") or "").strip()
            upstream_model = str(mapping.get("upstreamModel") or "").strip()
            if not request_model or request_model.endswith("*") or not upstream_model:
                continue
            api_model = request_model if capability == CAPABILITY_IMAGE else f"newapi_{request_model}"
            if capability == CAPABILITY_IMAGE:
                request = {
                    "endpoint": "images/generations",
                    "referenceFormat": mapping.get("imageEditFormat") or "images",
                    "parameters": [],
                }
            else:
                request = {
                    "endpoint": mapping.get("videoEndpoint") or "videos",
                    "parameters": [],
                }
            catalog_entry: dict[str, Any] = {
                    "catalogId": request_model,
                    "catalog_id": request_model,
                    "id": request_model,
                    "providerId": "newapi",
                    "provider": "newapi",
                    "apiModel": api_model,
                    "api_model": api_model,
                    "gatewayModel": upstream_model,
                    "gateway_model": upstream_model,
                    "upstreamModel": upstream_model,
                    "upstream_model": upstream_model,
                    "label": f"{group['name']} · {request_model}",
                    "mediaType": capability,
                    "sortOrder": 100,
                    "request": request,
                }
            if capability == CAPABILITY_IMAGE and (
                "gpt-image-2" in request_model.lower()
                or "gpt-image-2" in upstream_model.lower()
            ):
                catalog_entry["referenceImageMax"] = 9
            if capability == CAPABILITY_VIDEO and (
                request_model.lower() == "sd17-seedance-2.5-2"
                or upstream_model.lower() == "sd17-seedance-2.5-2"
            ):
                catalog_entry.update(
                    {
                        "referenceImageMax": 30,
                        "minDuration": 10,
                        "maxDuration": 30,
                        "resolutionOptions": ["720p"],
                    }
                )
            catalog.append(catalog_entry)
    return catalog


def get_newapi_embedding_model_config() -> dict[str, Any]:
    settings = get_model_gateway_settings()
    return _decode_embedding_model_config(settings.get("custom_newapi_embedding_model"))


def save_newapi_embedding_model_config(
    *,
    provider: str,
    upstream_model: str,
    dimension: int | str,
    batch_size: int | str | None = None,
    send_dimensions: bool = True,
) -> dict[str, Any]:
    normalized_provider = str(provider or "").strip().lower()
    normalized_upstream_model = str(upstream_model or "").strip()
    normalized_dimension = _int_setting(str(dimension), 0)
    normalized_batch_size = _int_setting(str(batch_size or ""), 0)
    if not normalized_provider:
        raise ValueError("provider is required for embedding model")
    if not normalized_upstream_model:
        raise ValueError("upstreamModel is required for embedding model")
    if normalized_dimension <= 0:
        raise ValueError("dimension must be positive")
    if batch_size not in (None, "") and normalized_batch_size <= 0:
        raise ValueError("batchSize must be positive")
    config = {
        "provider": normalized_provider,
        "upstreamModel": normalized_upstream_model,
        "dimension": normalized_dimension,
        "sendDimensions": True,
        "internalModel": "DC-cognee-embedding",
    }
    if normalized_batch_size > 0:
        config["batchSize"] = normalized_batch_size
    _write_many(
        {
            "custom_newapi_embedding_model": json.dumps(
                config,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        }
    )
    return config


def build_newapi_embedding_model_status() -> dict[str, Any]:
    return get_newapi_embedding_model_config()


def build_newapi_provider_channels_status() -> list[dict[str, Any]]:
    return [
        {
            "provider": channel["provider"],
            "type": channel.get("type", 0),
            "configured": bool(channel["upstreamKey"])
            or (
                channel["provider"] == "comfyui"
                and bool(channel["baseUrl"])
                and bool(channel.get("settings"))
            ),
            "upstreamKeyPreview": mask_secret(channel["upstreamKey"]),
            "baseUrl": channel["baseUrl"],
            "priority": channel.get("priority", 0),
            "settings": channel.get("settings", {}),
        }
        for channel in get_newapi_provider_channels()
    ]


def save_media_relay_config(
    *,
    provider: str,
    ttl_seconds: int,
    endpoint: str = "",
    bucket: str = "",
    access_key_id: str = "",
    access_key_secret: str = "",
    cloud_name: str = "",
    cloudinary_api_key: str = "",
    cloudinary_api_secret: str = "",
    cloudinary_folder: str = "",
    minio_endpoint: str = "",
    minio_public_endpoint: str = "",
    minio_port: int = 9000,
    minio_use_ssl: bool = False,
    minio_bucket: str = "",
    minio_access_key: str = "",
    minio_secret_key: str = "",
) -> None:
    _write_many(
        {
            "media_relay_provider": str(provider or "").strip().lower(),
            "media_relay_ttl_seconds": str(int(ttl_seconds)),
            "oss_relay_endpoint": str(endpoint or "").strip(),
            "oss_relay_bucket": str(bucket or "").strip(),
            "oss_relay_ak": str(access_key_id or "").strip(),
            "oss_relay_sk": str(access_key_secret or "").strip(),
            "cloudinary_relay_cloud_name": str(cloud_name or "").strip(),
            "cloudinary_relay_api_key": str(cloudinary_api_key or "").strip(),
            "cloudinary_relay_api_secret": str(cloudinary_api_secret or "").strip(),
            "cloudinary_relay_folder": str(cloudinary_folder or "").strip().strip("/"),
            "minio_relay_endpoint": str(minio_endpoint or "").strip(),
            "minio_relay_public_endpoint": str(minio_public_endpoint or "")
            .strip()
            .rstrip("/"),
            "minio_relay_port": str(int(minio_port)),
            "minio_relay_use_ssl": "1" if minio_use_ssl else "0",
            "minio_relay_bucket": str(minio_bucket or "").strip(),
            "minio_relay_access_key": str(minio_access_key or "").strip(),
            "minio_relay_secret_key": str(minio_secret_key or "").strip(),
        }
    )


def get_model_gateway_settings() -> dict[str, str]:
    data = _read_all() if _uses_ce_gateway_settings() else {}
    data.setdefault("model_gateway_mode", MODE_OFFICIAL)
    if _uses_ce_gateway_settings():
        data.setdefault("custom_llm_mode", CUSTOM_LLM_MODE_ADVANCED)
    return data


def get_effective_newapi_config(
    *,
    explicit_config: EffectiveNewApiConfig | None = None,
    official_base_url: str | None = None,
    official_api_key: str | None = None,
    capability: str = CAPABILITY_TEXT,
    model: str = "",
) -> EffectiveNewApiConfig:
    if explicit_config is not None:
        if type(explicit_config) is not EffectiveNewApiConfig:
            raise TypeError("explicit_config must be an EffectiveNewApiConfig")
        return explicit_config
    if not _uses_ce_gateway_settings():
        return EffectiveNewApiConfig(
            mode=MODE_OFFICIAL,
            source="environment",
            base_url=normalize_relay_base_url(
                os.environ.get("NEWAPI_BASE_URL", "")
                or official_base_url
                or OFFICIAL_NEWAPI_BASE_URL
            ),
            api_key=normalize_api_key(
                official_api_key
                if official_api_key is not None
                else os.environ.get("NEWAPI_API_KEY", "")
            ),
        )

    capability = normalize_capability(capability)
    settings = get_model_gateway_settings()
    mode = normalize_gateway_mode(settings.get("model_gateway_mode"))
    return get_ce_newapi_config_for_mode(mode, capability=capability, model=model)


def get_ce_newapi_config_for_mode(
    mode: str,
    *,
    capability: str = CAPABILITY_TEXT,
    model: str = "",
) -> EffectiveNewApiConfig:
    """Return CE credentials for one gateway without changing the active mode.

    Embedding projects can remain bound to the gateway that created their vector
    space even when the installation's general model gateway is switched later.
    """

    if not _uses_ce_gateway_settings():
        raise RuntimeError("CE model gateway settings are not available in EE")

    settings = get_model_gateway_settings()
    mode = normalize_gateway_mode(mode)
    capability = normalize_capability(capability)
    if mode == MODE_SUB2API:
        group = _resolve_sub2api_group(capability=capability, model=model)
        if group is None:
            return EffectiveNewApiConfig(
                mode=MODE_SUB2API,
                source="sub2api",
                base_url="",
                api_key="",
            )
        return EffectiveNewApiConfig(
            mode=MODE_SUB2API,
            source="sub2api",
            base_url=_sub2api_openai_compat_base_url(group[0]),
            api_key=group[0]["apiKey"],
            protocol=group[0]["protocol"],
            model=group[1],
            native_base_url=(
                normalize_sub2api_base_url(str(group[0].get("baseUrl") or ""))
                if str(group[0].get("protocol") or "").strip().lower() == "gemini"
                else ""
            ),
        )
    if mode == MODE_CUSTOM:
        return EffectiveNewApiConfig(
            mode=MODE_CUSTOM,
            source="custom",
            base_url=normalize_relay_base_url(
                settings.get("custom_newapi_base_url", "")
            ),
            api_key=normalize_api_key(settings.get("custom_newapi_api_key", "")),
        )
    db_official_api_key = normalize_api_key(settings.get("official_newapi_api_key", ""))
    return EffectiveNewApiConfig(
        mode=mode,
        source="hybrid" if mode == MODE_HYBRID else "official",
        base_url=normalize_relay_base_url(OFFICIAL_NEWAPI_BASE_URL),
        api_key=db_official_api_key,
    )


def _is_official_relay_url(base_url: str) -> bool:
    """Whether a base URL is the official RelayClaw endpoint.

    Compared after normalisation so a trailing slash or a missing /v1 does not
    decide whether a credential may travel.
    """
    return normalize_relay_base_url(base_url or "") == normalize_relay_base_url(
        OFFICIAL_NEWAPI_BASE_URL
    )


def get_effective_llm_config(*, model: str = "") -> EffectiveLlmConfig:
    """Resolve LLM independently from media and embedding gateways."""
    if not _uses_ce_gateway_settings():
        base_url = normalize_relay_base_url(
            os.environ.get("NEWAPI_BASE_URL", "") or OFFICIAL_NEWAPI_BASE_URL
        )
        api_key = normalize_api_key(os.environ.get("NEWAPI_API_KEY", ""))
        is_brainclaw = base_url == normalize_relay_base_url(OFFICIAL_NEWAPI_BASE_URL)
        return EffectiveLlmConfig(
            mode=MODE_OFFICIAL if is_brainclaw else MODE_CUSTOM,
            source="environment",
            base_url=base_url,
            api_key=api_key,
            model="brainclaw" if is_brainclaw else "",
            is_brainclaw=is_brainclaw,
        )

    settings = get_model_gateway_settings()
    gateway_mode = normalize_gateway_mode(settings.get("model_gateway_mode"))
    custom_llm_mode = normalize_custom_llm_mode(settings.get("custom_llm_mode"))
    if gateway_mode in {MODE_OFFICIAL, MODE_HYBRID}:
        return EffectiveLlmConfig(
            mode=gateway_mode,
            source="hybrid" if gateway_mode == MODE_HYBRID else "official",
            base_url=normalize_relay_base_url(OFFICIAL_NEWAPI_BASE_URL),
            api_key=normalize_api_key(settings.get("official_newapi_api_key", "")),
            model="brainclaw",
            is_brainclaw=True,
        )
    if gateway_mode == MODE_SUB2API:
        backend = (
            os.environ.get("DRAMACLAW_CHAT_BACKEND")
            or os.environ.get("SUPERTALE_CHAT_BACKEND")
            or "codex"
        ).strip().lower()
        selected_model = str(model or "").strip() or (
            str(os.environ.get("HERMES_MODEL", "DC-hermes-LLM") or "DC-hermes-LLM").strip()
            if backend == "hermes"
            else str(os.environ.get("CODEX_MODEL", "DC-codex-agent-LLM") or "").strip()
        )
        gateway = get_ce_newapi_config_for_mode(
            MODE_SUB2API,
            capability=CAPABILITY_TEXT,
            model=selected_model,
        )
        return EffectiveLlmConfig(
            mode=MODE_SUB2API,
            source=MODE_SUB2API,
            base_url=gateway.base_url,
            api_key=gateway.api_key,
            model=gateway.model,
            is_brainclaw=False,
        )
    if custom_llm_mode == CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW:
        brainclaw_base_url = normalize_relay_base_url(
            settings.get("brainclaw_newapi_base_url", "")
            or OFFICIAL_NEWAPI_BASE_URL
        )
        # The official key may only be reused when the endpoint is the official
        # one. Falling back unconditionally sends a RelayClaw credential to
        # whatever host the operator typed — a third party, or a local gateway
        # that logs it — and nothing in the request looks wrong: billing,
        # audit and tenant attribution all follow a key the operator never
        # meant to expose there.
        brainclaw_api_key = normalize_api_key(
            settings.get("brainclaw_newapi_api_key", "")
            or (settings.get("official_newapi_api_key", "")
                if _is_official_relay_url(brainclaw_base_url) else "")
        )
        return EffectiveLlmConfig(
            mode=CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW,
            source=(
                "custom"
                if settings.get("brainclaw_newapi_base_url", "")
                or settings.get("brainclaw_newapi_api_key", "")
                else "official"
            ),
            base_url=brainclaw_base_url,
            api_key=brainclaw_api_key,
            model="brainclaw",
            is_brainclaw=True,
        )
    custom = get_ce_newapi_config_for_mode(MODE_CUSTOM)
    return EffectiveLlmConfig(
        mode=CUSTOM_LLM_MODE_ADVANCED,
        source=custom.source,
        base_url=custom.base_url,
        api_key=custom.api_key,
        model="",
        is_brainclaw=False,
    )


def get_effective_agent_llm_config() -> EffectiveLlmConfig:
    """Resolve the Agent-only LLM route without affecting business text models."""
    if not _uses_ce_gateway_settings():
        return get_effective_llm_config()

    settings = get_model_gateway_settings()
    agent_llm_mode = normalize_agent_llm_mode(settings.get("agent_llm_mode"))
    if agent_llm_mode != AGENT_LLM_MODE_THIRD_PARTY:
        return get_effective_llm_config()
    return EffectiveLlmConfig(
        mode=AGENT_LLM_MODE_THIRD_PARTY,
        source=AGENT_LLM_MODE_THIRD_PARTY,
        base_url=normalize_relay_base_url(settings.get("agent_llm_base_url", "")),
        api_key=normalize_api_key(settings.get("agent_llm_api_key", "")),
        model=str(settings.get("agent_llm_model", "")).strip(),
        is_brainclaw=False,
    )


def _int_setting(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def _bool_setting(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_effective_media_relay_config(
    *,
    explicit_config: EffectiveMediaRelayConfig | None = None,
    env_provider: str | None = None,
    env_ttl_seconds: int | str | None = None,
    env_endpoint: str | None = None,
    env_bucket: str | None = None,
    env_access_key_id: str | None = None,
    env_access_key_secret: str | None = None,
    env_cloud_name: str | None = None,
    env_cloudinary_api_key: str | None = None,
    env_cloudinary_api_secret: str | None = None,
    env_cloudinary_folder: str | None = None,
    env_minio_endpoint: str | None = None,
    env_minio_public_endpoint: str | None = None,
    env_minio_port: int | str | None = None,
    env_minio_use_ssl: bool | str | None = None,
    env_minio_bucket: str | None = None,
    env_minio_access_key: str | None = None,
    env_minio_secret_key: str | None = None,
) -> EffectiveMediaRelayConfig:
    if explicit_config is not None:
        if type(explicit_config) is not EffectiveMediaRelayConfig:
            raise TypeError("explicit_config must be an EffectiveMediaRelayConfig")
        return explicit_config
    settings = get_model_gateway_settings() if _uses_ce_gateway_settings() else {}
    db_provider = str(settings.get("media_relay_provider", "")).strip().lower()
    db_endpoint = str(settings.get("oss_relay_endpoint", "")).strip()
    db_bucket = str(settings.get("oss_relay_bucket", "")).strip()
    db_access_key_id = str(settings.get("oss_relay_ak", "")).strip()
    db_access_key_secret = str(settings.get("oss_relay_sk", "")).strip()
    db_cloud_name = str(settings.get("cloudinary_relay_cloud_name", "")).strip()
    db_cloudinary_api_key = str(settings.get("cloudinary_relay_api_key", "")).strip()
    db_cloudinary_api_secret = str(
        settings.get("cloudinary_relay_api_secret", "")
    ).strip()
    db_cloudinary_folder = (
        str(settings.get("cloudinary_relay_folder", "")).strip().strip("/")
    )
    db_minio_endpoint = str(settings.get("minio_relay_endpoint", "")).strip()
    db_minio_public_endpoint = (
        str(settings.get("minio_relay_public_endpoint", "")).strip().rstrip("/")
    )
    db_minio_bucket = str(settings.get("minio_relay_bucket", "")).strip()
    db_minio_access_key = str(settings.get("minio_relay_access_key", "")).strip()
    db_minio_secret_key = str(settings.get("minio_relay_secret_key", "")).strip()
    has_db_config = any(
        [
            db_provider,
            db_endpoint,
            db_bucket,
            db_access_key_id,
            db_access_key_secret,
            db_cloud_name,
            db_cloudinary_api_key,
            db_cloudinary_api_secret,
            db_cloudinary_folder,
            db_minio_endpoint,
            db_minio_public_endpoint,
            db_minio_bucket,
            db_minio_access_key,
            db_minio_secret_key,
        ]
    )
    if has_db_config:
        return EffectiveMediaRelayConfig(
            source="database",
            provider=db_provider or "aliyun_oss",
            ttl_seconds=_int_setting(settings.get("media_relay_ttl_seconds"), 1800),
            endpoint=db_endpoint,
            bucket=db_bucket,
            access_key_id=db_access_key_id,
            access_key_secret=db_access_key_secret,
            cloud_name=db_cloud_name,
            cloudinary_api_key=db_cloudinary_api_key,
            cloudinary_api_secret=db_cloudinary_api_secret,
            cloudinary_folder=db_cloudinary_folder,
            minio_endpoint=db_minio_endpoint,
            minio_public_endpoint=db_minio_public_endpoint,
            minio_port=_int_setting(settings.get("minio_relay_port"), 9000),
            minio_use_ssl=_bool_setting(settings.get("minio_relay_use_ssl"), False),
            minio_bucket=db_minio_bucket,
            minio_access_key=db_minio_access_key,
            minio_secret_key=db_minio_secret_key,
        )

    raw_ttl = (
        env_ttl_seconds
        if env_ttl_seconds is not None
        else os.environ.get(
            "MEDIA_RELAY_TTL_SECONDS",
            "1800",
        )
    )
    return EffectiveMediaRelayConfig(
        source="environment",
        provider=str(
            env_provider or os.environ.get("MEDIA_RELAY_PROVIDER", "aliyun_oss")
        )
        .strip()
        .lower(),
        ttl_seconds=_int_setting(str(raw_ttl), 1800),
        endpoint=str(env_endpoint or os.environ.get("OSS_RELAY_ENDPOINT", "")).strip(),
        bucket=str(env_bucket or os.environ.get("OSS_RELAY_BUCKET", "")).strip(),
        access_key_id=str(
            env_access_key_id or os.environ.get("OSS_RELAY_AK", "")
        ).strip(),
        access_key_secret=str(
            env_access_key_secret or os.environ.get("OSS_RELAY_SK", "")
        ).strip(),
        cloud_name=str(
            env_cloud_name or os.environ.get("CLOUDINARY_RELAY_CLOUD_NAME", "")
        ).strip(),
        cloudinary_api_key=str(
            env_cloudinary_api_key or os.environ.get("CLOUDINARY_RELAY_API_KEY", "")
        ).strip(),
        cloudinary_api_secret=str(
            env_cloudinary_api_secret
            or os.environ.get("CLOUDINARY_RELAY_API_SECRET", "")
        ).strip(),
        cloudinary_folder=str(
            env_cloudinary_folder or os.environ.get("CLOUDINARY_RELAY_FOLDER", "")
        )
        .strip()
        .strip("/"),
        minio_endpoint=str(
            env_minio_endpoint or os.environ.get("MINIO_RELAY_ENDPOINT", "")
        ).strip(),
        minio_public_endpoint=str(
            env_minio_public_endpoint
            or os.environ.get("MINIO_RELAY_PUBLIC_ENDPOINT", "")
        ).strip().rstrip("/"),
        minio_port=_int_setting(
            str(
                env_minio_port
                if env_minio_port is not None
                else os.environ.get("MINIO_RELAY_PORT", "9000")
            ),
            9000,
        ),
        minio_use_ssl=_bool_setting(
            env_minio_use_ssl
            if env_minio_use_ssl is not None
            else os.environ.get("MINIO_RELAY_USE_SSL"),
            False,
        ),
        minio_bucket=str(
            env_minio_bucket or os.environ.get("MINIO_RELAY_BUCKET", "")
        ).strip(),
        minio_access_key=str(
            env_minio_access_key or os.environ.get("MINIO_RELAY_ACCESS_KEY", "")
        ).strip(),
        minio_secret_key=str(
            env_minio_secret_key or os.environ.get("MINIO_RELAY_SECRET_KEY", "")
        ).strip(),
    )


def get_effective_cognee_embedding_config(
    *,
    env_provider: str | None = None,
    env_model: str | None = None,
    env_dimensions: str | int | None = None,
    llm_provider: str | None = None,
) -> EffectiveCogneeEmbeddingConfig:
    saved: dict[str, Any] = {}
    if _uses_ce_gateway_settings():
        gateway = get_effective_newapi_config()
        if gateway.mode == MODE_CUSTOM:
            saved = get_newapi_embedding_model_config()
    if saved:
        saved_batch_size = str(
            saved.get("batchSize")
            or os.environ.get("EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE)
        ).strip()
        if saved_batch_size:
            saved_batch_size = str(_int_setting(saved_batch_size, 0) or "")
        return EffectiveCogneeEmbeddingConfig(
            source="database",
            provider="newapi",
            model=str(saved["internalModel"]),
            dimensions=str(saved["dimension"]),
            upstream_provider=str(saved["provider"]),
            upstream_model=str(saved["upstreamModel"]),
            batch_size=saved_batch_size or DEFAULT_EMBEDDING_BATCH_SIZE,
        )

    # Product runtime always sends embeddings through newAPI. Keep the
    # arguments for API compatibility, but do not let legacy provider settings
    # bypass the gateway.
    del env_provider, llm_provider
    provider = DEFAULT_COGNEE_EMBEDDING_PROVIDER
    default_model = DEFAULT_COGNEE_EMBEDDING_MODEL
    model = str(
        env_model or os.environ.get("COGNEE_EMBEDDING_MODEL", default_model)
    ).strip()
    dimensions = (
        str(
            env_dimensions
            if env_dimensions is not None
            else os.environ.get("COGNEE_EMBEDDING_DIM", DEFAULT_COGNEE_EMBEDDING_DIM)
        ).strip()
        or DEFAULT_COGNEE_EMBEDDING_DIM
    )
    batch_size = str(
        os.environ.get("EMBEDDING_BATCH_SIZE", DEFAULT_EMBEDDING_BATCH_SIZE)
    ).strip()
    if batch_size:
        batch_size = str(_int_setting(batch_size, 0) or "")
    if not batch_size:
        batch_size = DEFAULT_EMBEDDING_BATCH_SIZE
    return EffectiveCogneeEmbeddingConfig(
        source="environment",
        provider=provider,
        model=model,
        dimensions=dimensions,
        upstream_provider="",
        upstream_model="",
        batch_size=batch_size,
    )


def build_model_gateway_status(
    *,
    official_base_url: str | None = None,
    official_api_key: str | None = None,
) -> dict[str, Any]:
    uses_ce_settings = _uses_ce_gateway_settings()
    settings = get_model_gateway_settings() if uses_ce_settings else {}
    official_base_url_value = normalize_relay_base_url(
        OFFICIAL_NEWAPI_BASE_URL
        if uses_ce_settings
        else (
            os.environ.get("NEWAPI_BASE_URL", "")
            or official_base_url
            or OFFICIAL_NEWAPI_BASE_URL
        )
    )
    env_official_api_key = (
        ""
        if uses_ce_settings
        else normalize_api_key(
            official_api_key
            if official_api_key is not None
            else os.environ.get("NEWAPI_API_KEY", "")
        )
    )
    db_official_api_key = (
        normalize_api_key(settings.get("official_newapi_api_key", ""))
        if uses_ce_settings
        else ""
    )
    official_api_key_value = (
        db_official_api_key if uses_ce_settings else env_official_api_key
    )
    custom_base_url = (
        normalize_relay_base_url(settings.get("custom_newapi_base_url", ""))
        if uses_ce_settings
        else ""
    )
    custom_api_key = (
        normalize_api_key(settings.get("custom_newapi_api_key", ""))
        if uses_ce_settings
        else ""
    )
    sub2api_groups = get_sub2api_groups(masked=True) if uses_ce_settings else []
    sub2api_configured = bool(sub2api_groups)
    sub2api_text_configured = any(CAPABILITY_TEXT in group.get("capabilities", []) for group in sub2api_groups)
    effective = get_effective_newapi_config(
        official_base_url=official_base_url,
        official_api_key=official_api_key,
    )
    effective_llm = get_effective_llm_config()
    agent_llm_mode = normalize_agent_llm_mode(settings.get("agent_llm_mode"))
    agent_llm_base_url = normalize_relay_base_url(
        settings.get("agent_llm_base_url", "")
    )
    agent_llm_api_key = normalize_api_key(settings.get("agent_llm_api_key", ""))
    agent_llm_model = str(settings.get("agent_llm_model", "")).strip()
    custom_llm_mode = normalize_custom_llm_mode(settings.get("custom_llm_mode"))
    brainclaw_base_url = normalize_relay_base_url(
        settings.get("brainclaw_newapi_base_url", "") or OFFICIAL_NEWAPI_BASE_URL
    )
    # Same rule as the effective config: the official key is only shown as the
    # BrainClaw key when the endpoint is the official one.
    dedicated_brainclaw_key = normalize_api_key(
        settings.get("brainclaw_newapi_api_key", "")
    )
    brainclaw_api_key = dedicated_brainclaw_key or (
        official_api_key_value if _is_official_relay_url(brainclaw_base_url) else ""
    )
    return {
        "mode": effective.mode,
        "effective": {
            "source": effective.source,
            "baseUrl": effective.base_url,
            "apiKeyPreview": mask_secret(effective.api_key),
            "configured": (
                sub2api_configured
                if effective.mode == MODE_SUB2API
                else bool(effective.base_url and effective.api_key)
            ),
        },
        "llmEffective": {
            "mode": effective_llm.mode,
            "source": effective_llm.source,
            "baseUrl": effective_llm.base_url,
            "apiKeyPreview": mask_secret(effective_llm.api_key),
            "configured": (
                sub2api_text_configured
                if effective_llm.mode == MODE_SUB2API
                else bool(effective_llm.base_url and effective_llm.api_key)
            ),
            "model": effective_llm.model,
            "brainclaw": effective_llm.is_brainclaw,
        },
        "agent": {
            "mode": agent_llm_mode,
            "baseUrl": agent_llm_base_url,
            "apiKeyPreview": mask_secret(agent_llm_api_key),
            "model": agent_llm_model,
            "configured": bool(
                agent_llm_base_url and agent_llm_api_key and agent_llm_model
            ),
        },
        "official": {
            "baseUrl": official_base_url_value,
            "apiKeyPreview": mask_secret(official_api_key_value),
            "configured": bool(official_base_url_value and official_api_key_value),
            "source": "database" if uses_ce_settings else "environment",
            "environment": {
                "baseUrl": official_base_url_value,
                "apiKeyPreview": mask_secret(env_official_api_key),
                "configured": bool(official_base_url_value and env_official_api_key),
            },
        },
        "brainclaw": {
            "baseUrl": brainclaw_base_url,
            "apiKeyPreview": mask_secret(brainclaw_api_key),
            # Distinct from apiKeyPreview, which is non-empty even when it is
            # only the official key showing through. A caller asking "is a
            # BrainClaw key configured?" must read this: the preview answers a
            # different question and treating it as this one is what allowed a
            # custom endpoint to be saved with no dedicated key at all.
            "dedicatedKeyConfigured": bool(dedicated_brainclaw_key),
            "configured": bool(brainclaw_base_url and brainclaw_api_key),
        },
        "custom": {
            "llmMode": custom_llm_mode,
            "baseUrl": custom_base_url,
            "apiKeyPreview": mask_secret(custom_api_key),
            "configured": bool(custom_base_url and custom_api_key),
            "adminBaseUrl": settings.get("custom_newapi_admin_base_url", ""),
            "tokenName": settings.get("custom_newapi_token_name", ""),
            "tokenId": settings.get("custom_newapi_token_id", ""),
        },
        "sub2api": {
            "groups": sub2api_groups,
            "configured": sub2api_configured,
        },
    }


def build_newapi_database_status(
    *,
    sql_dsn: str | None = None,
    sqlite_path: str | None = None,
    admin_username: str | None = None,
) -> dict[str, Any]:
    settings = get_model_gateway_settings()
    db_sql_dsn = str(settings.get("custom_newapi_db_sql_dsn", "")).strip()
    db_sqlite_path = str(settings.get("custom_newapi_db_sqlite_path", "")).strip()
    db_admin_username = str(settings.get("custom_newapi_admin_username", "")).strip()
    env_sql_dsn = str(
        sql_dsn if sql_dsn is not None else os.environ.get("NEWAPI_SQL_DSN", "")
    )
    env_sql_dsn = env_sql_dsn.strip()
    env_sqlite_path = str(
        sqlite_path
        if sqlite_path is not None
        else os.environ.get("NEWAPI_SQLITE_PATH", "")
    ).strip()
    if not db_sql_dsn and not env_sql_dsn:
        from novelvideo.config import STATE_DIR

        env_sql_dsn = "local"
        env_sqlite_path = env_sqlite_path or str(
            Path(STATE_DIR) / "newapi" / "one-api.db"
        )
    effective_sql_dsn = db_sql_dsn or env_sql_dsn
    effective_sqlite_path = db_sqlite_path or env_sqlite_path
    source = (
        "database"
        if any([db_sql_dsn, db_sqlite_path, db_admin_username])
        else "environment"
    )
    configured = bool(
        effective_sql_dsn and (effective_sql_dsn != "local" or effective_sqlite_path)
    )
    available = configured
    if effective_sql_dsn == "local":
        available = bool(
            effective_sqlite_path and Path(effective_sqlite_path).expanduser().is_file()
        )
    return {
        "configured": configured,
        "available": available,
        "source": source,
        "databaseType": "sqlite" if effective_sql_dsn == "local" else "external",
    }


def build_media_relay_status(
    *,
    env_provider: str | None = None,
    env_ttl_seconds: int | str | None = None,
    env_endpoint: str | None = None,
    env_bucket: str | None = None,
    env_access_key_id: str | None = None,
    env_access_key_secret: str | None = None,
    env_cloud_name: str | None = None,
    env_cloudinary_api_key: str | None = None,
    env_cloudinary_api_secret: str | None = None,
    env_cloudinary_folder: str | None = None,
    env_minio_endpoint: str | None = None,
    env_minio_public_endpoint: str | None = None,
    env_minio_port: int | str | None = None,
    env_minio_use_ssl: bool | str | None = None,
    env_minio_bucket: str | None = None,
    env_minio_access_key: str | None = None,
    env_minio_secret_key: str | None = None,
) -> dict[str, Any]:
    effective = get_effective_media_relay_config(
        env_provider=env_provider,
        env_ttl_seconds=env_ttl_seconds,
        env_endpoint=env_endpoint,
        env_bucket=env_bucket,
        env_access_key_id=env_access_key_id,
        env_access_key_secret=env_access_key_secret,
        env_cloud_name=env_cloud_name,
        env_cloudinary_api_key=env_cloudinary_api_key,
        env_cloudinary_api_secret=env_cloudinary_api_secret,
        env_cloudinary_folder=env_cloudinary_folder,
        env_minio_endpoint=env_minio_endpoint,
        env_minio_public_endpoint=env_minio_public_endpoint,
        env_minio_port=env_minio_port,
        env_minio_use_ssl=env_minio_use_ssl,
        env_minio_bucket=env_minio_bucket,
        env_minio_access_key=env_minio_access_key,
        env_minio_secret_key=env_minio_secret_key,
    )
    aliyun_configured = bool(
        effective.endpoint
        and effective.bucket
        and effective.access_key_id
        and effective.access_key_secret
    )
    cloudinary_configured = bool(
        effective.cloud_name
        and effective.cloudinary_api_key
        and effective.cloudinary_api_secret
    )
    minio_public_url = urlsplit(effective.minio_public_endpoint)
    try:
        minio_public_port_valid = minio_public_url.port is None or 1 <= minio_public_url.port <= 65535
    except ValueError:
        minio_public_port_valid = False
    minio_configured = bool(
        effective.minio_endpoint
        and effective.minio_public_endpoint
        and minio_public_url.scheme == "https"
        and minio_public_url.hostname
        and minio_public_url.username is None
        and minio_public_url.password is None
        and minio_public_url.path in {"", "/"}
        and not minio_public_url.query
        and not minio_public_url.fragment
        and minio_public_port_valid
        and effective.minio_bucket
        and effective.minio_access_key
        and effective.minio_secret_key
        and 1 <= effective.minio_port <= 65535
    )
    return {
        "source": effective.source,
        "provider": effective.provider,
        "ttlSeconds": effective.ttl_seconds,
        "endpoint": effective.endpoint,
        "bucket": effective.bucket,
        "accessKeyIdPreview": mask_secret(effective.access_key_id),
        "accessKeySecretPreview": mask_secret(effective.access_key_secret),
        "cloudName": effective.cloud_name,
        "cloudinaryApiKeyPreview": mask_secret(effective.cloudinary_api_key),
        "cloudinaryApiSecretPreview": mask_secret(effective.cloudinary_api_secret),
        "apiFolder": effective.cloudinary_folder,
        "minioEndpoint": effective.minio_endpoint,
        "minioPublicEndpoint": effective.minio_public_endpoint,
        "minioPort": effective.minio_port,
        "minioUseSSL": effective.minio_use_ssl,
        "minioBucket": effective.minio_bucket,
        "minioAccessKeyPreview": mask_secret(effective.minio_access_key),
        "minioSecretKeyPreview": mask_secret(effective.minio_secret_key),
        "configured": (
            cloudinary_configured
            if effective.provider == "cloudinary"
            else minio_configured
            if effective.provider == "minio"
            else aliyun_configured
        ),
    }
