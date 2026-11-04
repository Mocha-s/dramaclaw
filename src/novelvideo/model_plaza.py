"""上游模型广场：一个模型一条说明、一个实收价。

广场是上游中转站的面板接口（`GET /api/v1/model-plaza`），是我们能拿到的唯一
同时带模型说明和定价的来源（key 面的 `/v1/models` 只有 id 和 display_name）。
按上游模型名把说明和实收价贴到画布模型目录上；拉不到就当作没有，不影响选模型。

这个接口实测要 5–14 秒（响应约 200KB），所以只让进程内的第一次调用等：
之后命中缓存直接返回，缓存过期也先把旧数据交出去、在后台刷新的那份。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from novelvideo.model_gateway_settings import (
    _is_external_http_url,
    get_third_party_gateway_groups,
)

logger = logging.getLogger("novelvideo.model_plaza")

PLAZA_PATH = "/api/v1/model-plaza"
CACHE_TTL_SECONDS = 600.0
# 失败缓存短一些：上游抖动一会儿不该让整个下拉十分钟没有说明和价格。
FAILURE_TTL_SECONDS = 60.0
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 20.0

_CACHE_LOCK = threading.Lock()
_REFRESH_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"expires_at": 0.0, "payload": None}
_REFRESHING = False


def _plaza_endpoint() -> tuple[str, str] | None:
    """第一个能当广场用的第三方分组：同一个中转站的域名 + 该分组的 key。"""
    for group in get_third_party_gateway_groups():
        parsed = urlsplit(str(group.get("baseUrl") or "").strip())
        origin = f"{parsed.scheme}://{parsed.netloc}"
        api_key = str(group.get("apiKey") or "").strip()
        if not parsed.netloc or not api_key or not _is_external_http_url(origin):
            continue
        return origin, api_key
    return None


def _unwrap(payload: dict[str, Any]) -> dict[str, Any]:
    """面板接口把内容包在 `data` 里，别拿顶层当正文。"""
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _fetch_payload() -> dict[str, Any] | None:
    endpoint = _plaza_endpoint()
    if endpoint is None:
        return None
    origin, api_key = endpoint
    try:
        with httpx.Client(
            trust_env=False,
            timeout=REQUEST_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = client.get(
                f"{origin}{PLAZA_PATH}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
        if response.status_code >= 400 or len(response.content) > MAX_RESPONSE_BYTES:
            return None
        payload = response.json()
    except Exception:  # noqa: BLE001 - 广场只是装饰，任何失败都不该冒泡到选模型
        logger.debug("model plaza fetch failed", exc_info=True)
        return None
    return _unwrap(payload) if isinstance(payload, dict) else None


def _store(payload: dict[str, Any] | None) -> None:
    with _CACHE_LOCK:
        _CACHE["payload"] = payload
        _CACHE["expires_at"] = time.monotonic() + (
            CACHE_TTL_SECONDS if payload is not None else FAILURE_TTL_SECONDS
        )


def _refresh_in_background() -> None:
    global _REFRESHING
    with _REFRESH_LOCK:
        if _REFRESHING:
            return
        _REFRESHING = True

    def run() -> None:
        global _REFRESHING
        try:
            _store(_fetch_payload())
        finally:
            with _REFRESH_LOCK:
                _REFRESHING = False

    threading.Thread(target=run, name="model-plaza-refresh", daemon=True).start()


def _load_payload() -> dict[str, Any] | None:
    now = time.monotonic()
    with _CACHE_LOCK:
        cached = _CACHE["payload"]
        fresh = now < float(_CACHE["expires_at"] or 0.0)
    if isinstance(cached, dict):
        if not fresh:
            _refresh_in_background()
        return cached
    # 从没拉到过：这一轮进程的第一次只能等，否则这次运行里永远看不到价格。
    payload = _fetch_payload()
    _store(payload)
    return payload


def _billing_unit(pricing: dict[str, Any]) -> str:
    return "image" if str(pricing.get("billing_mode") or "") == "image" else "request"


def _price_tiers(pricing: dict[str, Any], rate: float) -> list[dict[str, Any]]:
    """广场的档位价（按分辨率/时长分档）：已乘倍率、去重、按价格升序。"""
    default_unit = _billing_unit(pricing)
    tiers: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    intervals = pricing.get("intervals")
    for interval in intervals if isinstance(intervals, list) else []:
        if not isinstance(interval, dict):
            continue
        label = str(interval.get("tier_label") or "").strip()
        value = interval.get("per_request_price")
        if not isinstance(value, (int, float)) or value <= 0:
            value = interval.get("video_price_per_second")
        if not label or not isinstance(value, (int, float)) or value <= 0:
            continue
        tier = (label, round(float(value) * rate, 4))
        if tier in seen:
            continue
        seen.add(tier)
        tiers.append({"label": tier[0], "value": tier[1]})
    return sorted(tiers, key=lambda tier: tier["value"]) if default_unit else tiers


def _tier_price(pricing: dict[str, Any]) -> tuple[float, str, bool] | None:
    """一个 pricing 块里的价位：目录价、单位、是否只是档位起价。"""
    unit = _billing_unit(pricing)
    per_request = pricing.get("per_request_price")
    if isinstance(per_request, (int, float)) and per_request > 0:
        return float(per_request), unit, False
    per_second = pricing.get("video_price_per_second")
    if isinstance(per_second, (int, float)) and per_second > 0:
        return float(per_second), "second", False
    # 只有档位才有价（按分辨率/时长分档）时就报最低那档，并标记为起价。
    options: list[tuple[float, str]] = []
    intervals = pricing.get("intervals")
    for interval in intervals if isinstance(intervals, list) else []:
        if not isinstance(interval, dict):
            continue
        value = interval.get("per_request_price")
        if isinstance(value, (int, float)) and value > 0:
            options.append((float(value), unit))
            continue
        value = interval.get("video_price_per_second")
        if isinstance(value, (int, float)) and value > 0:
            options.append((float(value), "second"))
    if not options:
        return None
    value, chosen_unit = min(options, key=lambda option: option[0])
    return value, chosen_unit, True


def get_model_usage_index() -> dict[str, dict[str, Any]]:
    """上游模型名 -> {description, priceValue, priceUnit, priceFrom}。

    `priceValue` 已经乘过分组倍率，就是广场页面上那个实收价。
    """
    payload = _load_payload()
    groups = payload.get("groups") if isinstance(payload, dict) else None
    if not isinstance(groups, list):
        return {}
    index: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            continue
        raw_rate = group.get("rate_multiplier")
        rate = float(raw_rate) if isinstance(raw_rate, (int, float)) and raw_rate > 0 else 1.0
        models = group.get("models")
        for model in models if isinstance(models, list) else []:
            if not isinstance(model, dict):
                continue
            name = str(model.get("name") or "").strip()
            if not name or name in index:
                continue
            pricing = model.get("pricing") if isinstance(model.get("pricing"), dict) else {}
            usage: dict[str, Any] = {}
            description = str(
                model.get("description") or pricing.get("description") or ""
            ).strip()
            if description:
                usage["description"] = description
            tiers = _price_tiers(pricing, rate)
            # 只有一档就等于没有分档，别把单档当档位列表显示。
            if len({tier["value"] for tier in tiers}) >= 2:
                usage["priceTiers"] = tiers
            price = _tier_price(pricing)
            if price is not None:
                value, unit, is_from = price
                usage["priceValue"] = round(value * rate, 4)
                usage["priceUnit"] = unit
                if is_from:
                    usage["priceFrom"] = True
            if usage:
                index[name] = usage
    return index


def attach_model_usage(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按上游模型名给目录条目补说明和价格；拿不到就原样返回。"""
    index = get_model_usage_index()
    if not index:
        return catalog
    result: list[dict[str, Any]] = []
    for entry in catalog:
        name = str(entry.get("upstreamModel") or entry.get("gatewayModel") or "").strip()
        usage = index.get(name)
        result.append({**entry, **usage} if usage else entry)
    return result
