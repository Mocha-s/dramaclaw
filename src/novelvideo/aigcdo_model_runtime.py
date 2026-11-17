"""Per-user gateway credentials for the existing generators.

The operator catalog says which models exist and how they are called. The key always
belongs to the user whose task or request is running: there is no shared key to fall
back to, so anything outside a user scope resolves to an empty credential and fails.
"""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

GATEWAY_ORIGIN = "https://api.aigcdo.top"
CATALOG_ENV = "AIGCDO_MODEL_CATALOG"
# Task children are one user's process and cannot inherit a ContextVar.
CHILD_KEY_ENV = "AIGCDO_SCOPED_API_KEY"
# What process-wide config (Cognee, env) holds instead of a key; never a credential.
PLACEHOLDER_KEY = "aigcdo-per-request"
# Shared model credentials an AIGCDO host must not carry: any of them would bill the operator.
SHARED_CREDENTIAL_ENV = (
    CHILD_KEY_ENV, "NEWAPI_API_KEY", "MODEL_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY",
    "EMBEDDING_API_KEY", "COGNEE_LLM_API_KEY", "COGNEE_EMBEDDING_API_KEY", "OPENROUTER_API_KEY",
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_AI_API_KEY", "XAI_API_KEY",
    "ARK_API_KEY", "VOLCENGINE_API_KEY", "VOLCENGINE_VISUAL_API_KEY", "DASHSCOPE_API_KEY",
    "HUIMENGI_API_KEY", "FAL_KEY", "FAL_API_KEY", "FISH_AUDIO_API_KEY", "SKETCH_GATE_API_KEY",
    "DRAMACLAW_SCENE_360_API_KEY", "BLOCK_WORLD_API_KEY", "ST_ORG_GATEWAY_API_KEY",
)
_GROUP_FIELDS = {"id", "name", "protocol", "capabilities", "modelMappings"}
_DEFAULT_FIELDS = {"textGroupId", "textModel", "textReasoningEffort"}
# The one model credential that is the operator's: embeddings are cheap, shared by the
# knowledge graph, and may live on any provider. Every other call spends the user's key.
EMBEDDING_ENV = ("AIGCDO_EMBEDDING_BASE_URL", "AIGCDO_EMBEDDING_API_KEY", "AIGCDO_EMBEDDING_MODEL")

_USER_KEY: ContextVar[str] = ContextVar("aigcdo_user_key", default="")
_ADMIN: ContextVar[bool] = ContextVar("aigcdo_admin", default=False)


def admin() -> bool:
    return _ADMIN.get()


@contextmanager
def admin_scope():
    """The administrator's request: stored settings are read and written as they are."""
    token = _ADMIN.set(True)
    try:
        yield
    finally:
        _ADMIN.reset(token)


def active() -> bool:
    from novelvideo.shared.runtime_env import auth_provider

    return auth_provider() == "aigcdo"


@contextmanager
def user_key_scope(api_key: str):
    token = _USER_KEY.set(api_key)
    try:
        yield
    finally:
        _USER_KEY.reset(token)


def scoped_user_key() -> str:
    return _USER_KEY.get() or os.environ.get(CHILD_KEY_ENV, "")


def embedding_endpoint(stored: dict[str, str] | None = None) -> dict | None:
    """Operator-configured embedding endpoint, or None when novel import is not offered.

    The environment wins; otherwise the administrator's embedding group in settings.
    """
    base_url, api_key, model = (os.environ.get(name, "").strip() for name in EMBEDDING_ENV)
    dimensions = os.environ.get("AIGCDO_EMBEDDING_DIMENSIONS", "").strip() or "1024"
    if not (base_url or api_key or model):
        if stored is None:
            from novelvideo.model_gateway_settings import _connect

            conn = _connect(user_read=True)
            try:
                stored = {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM runtime_settings")}
            finally:
                conn.close()
        try:
            defaults = json.loads(stored.get("third_party_capability_defaults") or "{}")
            saved = json.loads(stored.get("custom_newapi_embedding_model") or "{}")
        except ValueError:
            return None
        for group in _stored_groups(stored):
            if (group.get("id") == defaults.get("embeddingGroupId") and "embedding" in (group.get("capabilities") or [])
                    and defaults.get("embeddingModel") and group.get("apiKey")
                    and str(group.get("baseUrl") or "").startswith("https://") and not _gateway(group.get("baseUrl"))):
                # shortcut: 1024 unless the admin saved an embedding dimension; add a field if models differ.
                return {
                    "base_url": str(group["baseUrl"]).rstrip("/"), "api_key": str(group["apiKey"]),
                    "model": str(defaults["embeddingModel"]), "dimensions": int(saved.get("dimension") or 1024),
                }
        return None
    if not (base_url.startswith("https://") and api_key and model
            and dimensions.isdecimal() and int(dimensions) > 0):
        raise ValueError("embedding endpoint is incomplete")
    return {
        "base_url": base_url.rstrip("/"), "api_key": api_key, "model": model,
        "dimensions": int(dimensions),
    }


def load_catalog(path: str | Path) -> dict:
    """Validated operator catalog; rejects anything that is not model metadata."""
    from novelvideo.model_gateway_settings import _normalize_sub2api_groups

    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ValueError("model catalog is unreadable") from None
    if type(raw) is not dict or set(raw) - {"groups", "capabilityDefaults", "agentModel"}:
        raise ValueError("model catalog has unknown fields")
    groups = raw.get("groups")
    defaults = raw.get("capabilityDefaults", {})
    agent_model = raw.get("agentModel", "")
    if (
        type(groups) is not list or not groups
        # A credential or a foreign endpoint in the catalog would be a shared key by another name.
        or any(type(group) is not dict or set(group) - _GROUP_FIELDS for group in groups)
        or type(defaults) is not dict or set(defaults) - _DEFAULT_FIELDS
        or any(type(value) is not str for value in defaults.values())
        or type(agent_model) is not str
    ):
        raise ValueError("model catalog may only describe gateway models")
    normalized = _normalize_sub2api_groups(
        [{**group, "baseUrl": GATEWAY_ORIGIN, "apiKey": "catalog"} for group in groups]
    )
    return {
        "groups": [{k: v for k, v in group.items() if k != "apiKey"} for group in normalized],
        "capabilityDefaults": defaults,
        "agentModel": agent_model.strip(),
    }


@lru_cache(maxsize=1)
def _catalog(path: str) -> dict:
    return load_catalog(path)


_USER_HIDDEN = (
    "platform_gateway", "custom_newapi_", "official_newapi", "brainclaw_", "sub2api_", "agent_llm_", "aigcdo.",
)


def _gateway(url: object) -> bool:
    try:
        parts = urlsplit(str(url or ""))
    except ValueError:  # a malformed stored URL must not take every user's settings down
        return False
    return f"{parts.scheme}://{parts.netloc}".lower() == GATEWAY_ORIGIN


def _stored_groups(stored: dict[str, str]) -> list[dict]:
    try:
        groups = json.loads(stored.get("third_party_gateway_groups") or "[]")
    except ValueError:
        return []
    return [group for group in groups if type(group) is dict] if type(groups) is list else []


def user_rows(stored: dict[str, str]) -> dict[str, str]:
    """The administrator's settings as one user may use them.

    Gateway groups get the scoped user's own key (the administrator's is only for listing
    models and prices). Any other endpoint may only serve embeddings, on the administrator's
    key: text or media there would bill the operator for every user.
    """
    key = scoped_user_key()
    groups = _stored_groups(stored)
    catalog = None
    if not groups and os.environ.get(CATALOG_ENV, "").strip():
        # First boot: the optional catalog file seeds the model list until the admin saves one.
        catalog = _catalog(os.environ[CATALOG_ENV])
        groups = [{**group, "baseUrl": GATEWAY_ORIGIN} for group in catalog["groups"]]
    rows = {name: value for name, value in stored.items() if not name.startswith(_USER_HIDDEN)}
    rows.update(
        model_gateway_mode="custom", custom_llm_mode="advanced",
        third_party_gateway_migration_version="1",
        third_party_gateway_groups=json.dumps([
            {**group, "apiKey": key} if _gateway(group.get("baseUrl")) else group
            for group in groups
            if _gateway(group.get("baseUrl")) or group.get("capabilities") == ["embedding"]
        ], ensure_ascii=False),
    )
    if catalog is not None:
        rows["third_party_capability_defaults"] = json.dumps(catalog["capabilityDefaults"], ensure_ascii=False)
    embedding = embedding_endpoint(stored)
    if embedding:
        rows["custom_newapi_embedding_model"] = json.dumps({
            "provider": "operator", "upstreamModel": embedding["model"],
            "dimension": embedding["dimensions"],
        })
    agent_model = catalog["agentModel"] if catalog is not None else (
        stored.get("agent_llm_model", "") if _gateway(stored.get("agent_llm_base_url")) else ""
    )
    if agent_model:
        rows.update(
            agent_llm_mode="third_party", agent_llm_base_url=GATEWAY_ORIGIN,
            agent_llm_api_key=key, agent_llm_model=agent_model,
        )
    return rows


def agent_model() -> str:
    """The Agent model users get, or "" when the Agent is not offered."""
    from novelvideo.model_gateway_settings import _read_all

    with user_key_scope(""):
        token = _ADMIN.set(False)
        try:
            return _read_all().get("agent_llm_model", "")
        finally:
            _ADMIN.reset(token)
