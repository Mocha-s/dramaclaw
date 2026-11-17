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


def embedding_endpoint() -> dict | None:
    """Operator-configured embedding endpoint, or None when novel import is not offered."""
    base_url, api_key, model = (os.environ.get(name, "").strip() for name in EMBEDDING_ENV)
    dimensions = os.environ.get("AIGCDO_EMBEDDING_DIMENSIONS", "").strip() or "1024"
    if not (base_url or api_key or model):
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


def settings_rows() -> dict[str, str]:
    """What the legacy settings store would hold, for the scoped user only."""
    catalog = _catalog(os.environ.get(CATALOG_ENV, ""))
    key = scoped_user_key()
    rows = {
        "model_gateway_mode": "custom",
        "custom_llm_mode": "advanced",
        "third_party_gateway_migration_version": "1",
        "third_party_gateway_groups": json.dumps(
            [{**group, "apiKey": key} for group in catalog["groups"]], ensure_ascii=False,
        ),
        "third_party_capability_defaults": json.dumps(
            catalog["capabilityDefaults"], ensure_ascii=False,
        ),
    }
    embedding = embedding_endpoint()
    if embedding:
        # Only the vector size is settings-shaped; the endpoint and its key stay out of user rows.
        rows["custom_newapi_embedding_model"] = json.dumps({
            "provider": "operator", "upstreamModel": embedding["model"],
            "dimension": embedding["dimensions"],
        })
    if catalog["agentModel"]:
        rows.update(
            agent_llm_mode="third_party", agent_llm_base_url=GATEWAY_ORIGIN,
            agent_llm_api_key=key, agent_llm_model=catalog["agentModel"],
        )
    return rows
