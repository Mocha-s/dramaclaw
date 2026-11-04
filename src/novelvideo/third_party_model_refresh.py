"""Mirror every auto-enabled third-party gateway group's model list.

The manual fetch button only returns a list for the UI checkboxes. Without this
loop a model the upstream gateway removes stays routable forever, and a model it
adds is never reachable, because the saved mapping is the only record of both.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from novelvideo.model_gateway_protocols import (
    extract_model_names,
    model_discovery_request,
)
from novelvideo.model_gateway_settings import (
    get_third_party_gateway_groups,
    get_third_party_models_auto_fetch_last_at,
    record_third_party_models_fetch_attempt,
    save_third_party_gateway_groups,
    sync_model_mappings,
)

logger = logging.getLogger("novelvideo.third_party_model_refresh")

REFRESH_INTERVAL_SECONDS = 24 * 60 * 60
# shortcut: the loop wakes every few minutes and only fetches when due, so
# turning a group's switch on takes effect without a restart and without a long
# sleep that a restart would reset. Upgrade to a real scheduler if the fleet grows.
_POLL_SECONDS = 300


def discover_third_party_models(protocol: str, base_url: str, api_key: str) -> list[str]:
    """Fetch one gateway's model names.

    Mirrors the paging in ``POST /model-gateway/third-party/models``; that route
    raises HTTPException for the same failures, so the two stay separate for now.
    """
    endpoint, headers, params = model_discovery_request(protocol, base_url, api_key)
    models: list[str] = []
    seen: set[str] = set()
    with httpx.Client(
        trust_env=False,
        timeout=httpx.Timeout(20.0),
        follow_redirects=False,
    ) as client:
        for _page in range(10):
            response = client.get(endpoint, headers=headers, params=params)
            if response.status_code >= 400:
                raise ValueError("third-party gateway rejected model discovery")
            try:
                payload = response.json()
            except ValueError:
                raise ValueError(
                    "third-party gateway returned an invalid model list"
                ) from None
            for model in extract_model_names(protocol, payload):
                if model not in seen:
                    seen.add(model)
                    models.append(model)
            if protocol != "gemini" or not payload.get("nextPageToken"):
                break
            params = {"pageSize": 1000, "pageToken": str(payload["nextPageToken"])}
    return models


def _upstream_models(mappings: list[dict[str, Any]]) -> set[str]:
    return {str(mapping.get("upstreamModel") or "").strip() for mapping in mappings}


def _patterns(group: dict[str, Any]) -> list[tuple[str, bool]]:
    """A group's request patterns as (pattern, is_prefix); ``*`` claims nothing."""
    patterns: list[tuple[str, bool]] = []
    for mapping in group.get("modelMappings") or []:
        pattern = str(mapping.get("requestPattern") or "").strip()
        if not pattern or pattern == "*":
            continue
        patterns.append((pattern, pattern.endswith("*")))
    return patterns


def _claim_checker(patterns: list[tuple[str, bool]]) -> Callable[[str], bool]:
    def is_claimed(name: str) -> bool:
        return any(
            name == pattern or (is_prefix and name.startswith(pattern[:-1]))
            for pattern, is_prefix in patterns
        )

    return is_claimed


def refresh_third_party_gateway_models() -> dict[str, Any]:
    """Sync every auto-enabled group. Groups without the flag are never touched."""
    groups = get_third_party_gateway_groups()
    targets = [group for group in groups if group.get("autoFetch")]
    if not targets:
        return {"groups": 0, "refreshed": 0, "added": 0, "removed": 0}
    refreshed = 0
    added = 0
    removed = 0
    # Names another group already routes. It grows as groups add, so a name that
    # several gateways list stays with the first group in config order.
    auto_claims: dict[str, list[tuple[str, bool]]] = {}
    updated: list[dict[str, Any]] = []
    for group in groups:
        if not group.get("autoFetch"):
            updated.append(group)
            continue
        capabilities = group.get("capabilities") or []
        claims: list[tuple[str, bool]] = []
        for other in groups:
            if other["id"] == group["id"]:
                continue
            if not set(capabilities) & set(other.get("capabilities") or []):
                continue
            claims.extend(_patterns(other))
        for capability in capabilities:
            claims.extend(auto_claims.get(capability, []))
        try:
            discovered = discover_third_party_models(
                str(group.get("protocol") or ""),
                str(group.get("baseUrl") or ""),
                str(group.get("apiKey") or ""),
            )
        except (ValueError, httpx.HTTPError) as exc:
            # An unreachable gateway keeps its last known mappings.
            logger.warning(
                "third-party model refresh failed for group %s: %s",
                group.get("id"),
                exc,
            )
            updated.append(group)
            continue
        before = group.get("modelMappings") or []
        mappings = sync_model_mappings(
            before, discovered, capabilities, _claim_checker(claims)
        )
        if mappings is None:
            logger.info(
                "third-party model refresh left group %s alone: %d models listed, none of them its own",
                group.get("id"),
                len(discovered),
            )
            updated.append(group)
            continue
        added += len(_upstream_models(mappings) - _upstream_models(before))
        removed += len(_upstream_models(before) - _upstream_models(mappings))
        refreshed += 1
        for mapping in mappings:
            if mapping.get("auto"):
                for capability in capabilities:
                    auto_claims.setdefault(capability, []).append(
                        (str(mapping.get("requestPattern") or ""), False)
                    )
        updated.append({**group, "modelMappings": mappings})
    if refreshed:
        save_third_party_gateway_groups(updated)
    record_third_party_models_fetch_attempt()
    return {
        "groups": len(targets),
        "refreshed": refreshed,
        "added": added,
        "removed": removed,
    }


def auto_fetch_due(now: datetime | None = None) -> bool:
    last_at = get_third_party_models_auto_fetch_last_at()
    if not last_at:
        return True
    try:
        last = datetime.fromisoformat(last_at)
    except ValueError:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - last >= timedelta(
        seconds=REFRESH_INTERVAL_SECONDS
    )


async def run_third_party_model_refresh_updater() -> None:
    while True:
        try:
            if auto_fetch_due():
                summary = await asyncio.to_thread(refresh_third_party_gateway_models)
                if summary["groups"]:
                    logger.info("third-party model refresh %s", summary)
        except Exception:
            logger.warning("third-party model refresh failed", exc_info=True)
        await asyncio.sleep(_POLL_SECONDS)
