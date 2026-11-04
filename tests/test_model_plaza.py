from __future__ import annotations

import time

import httpx
import pytest
import respx

from novelvideo import model_plaza
from novelvideo.model_gateway_settings import CAPABILITY_IMAGE

PLAZA_URL = "https://relay.example/api/v1/model-plaza"

# 面板接口把正文包在 data 里，这里照抄真实形状。
PAYLOAD = {
    "code": 0,
    "data": {
        "description": "",
        "groups": [
            {
                "name": "生图渠道专用",
                "platform": "openai",
                "rate_multiplier": 0.5,
                "models": [
                    {
                        "name": "gpt-image-2",
                        "description": "批量图片创作与蒙版编辑",
                        "pricing": {
                            "billing_mode": "image",
                            "per_request_price": 0.21,
                            "intervals": [],
                        },
                    },
                    {
                        "name": "sd16-seedance-2.0",
                        "description": "人物短片",
                        "pricing": {
                            "billing_mode": "per_request",
                            "per_request_price": None,
                            "intervals": [
                                {"tier_label": "480p", "per_request_price": 48},
                                {"tier_label": "720p", "per_request_price": 67},
                            ],
                        },
                    },
                    {
                        "name": "seedance2.0-720p",
                        "pricing": {
                            "billing_mode": "per_second",
                            "video_price_per_second": 0.2,
                        },
                    },
                    {
                        "name": "no-price",
                        "description": "只有说明",
                        "pricing": {"billing_mode": "request"},
                    },
                ],
            }
        ],
    },
}

CATALOG = [
    {"catalogId": "gpt-image-2", "upstreamModel": "gpt-image-2", "label": "gpt-image-2"},
    {"catalogId": "sd16-seedance-2.0", "upstreamModel": "sd16-seedance-2.0", "label": "sd16"},
    {"catalogId": "seedance2.0-720p", "upstreamModel": "seedance2.0-720p", "label": "sd720"},
    {"catalogId": "no-price", "upstreamModel": "no-price", "label": "无价"},
    {"catalogId": "unlisted", "upstreamModel": "unlisted", "label": "广场没有"},
]


@pytest.fixture(autouse=True)
def _clear_plaza_cache(monkeypatch):
    monkeypatch.setattr(model_plaza, "_CACHE", {"expires_at": 0.0, "payload": None})
    monkeypatch.setattr(model_plaza, "_REFRESHING", False)
    monkeypatch.setattr(
        model_plaza, "_plaza_endpoint", lambda: ("https://relay.example", "sk-test")
    )


@respx.mock
def test_attach_model_usage_adds_description_and_discounted_price():
    respx.get(PLAZA_URL).mock(return_value=httpx.Response(200, json=PAYLOAD))

    entries = {entry["catalogId"]: entry for entry in model_plaza.attach_model_usage(CATALOG)}

    assert entries["gpt-image-2"]["description"] == "批量图片创作与蒙版编辑"
    # 实收价 = 目录价 × 分组倍率，和广场页面一致。
    assert entries["gpt-image-2"]["priceValue"] == 0.105
    assert entries["gpt-image-2"]["priceUnit"] == "image"
    assert "priceFrom" not in entries["gpt-image-2"]

    # 只有档位有价时报最低档，并标记为起价。
    assert entries["sd16-seedance-2.0"]["priceValue"] == 24.0
    assert entries["sd16-seedance-2.0"]["priceUnit"] == "request"
    assert entries["sd16-seedance-2.0"]["priceFrom"] is True

    assert entries["seedance2.0-720p"]["priceValue"] == 0.1
    assert entries["seedance2.0-720p"]["priceUnit"] == "second"

    # 只有说明的条目只多一个 description；广场里没有的条目原样保留。
    assert entries["no-price"] == {**CATALOG[3], "description": "只有说明"}
    assert entries["unlisted"] == CATALOG[4]


@respx.mock
def test_attach_model_usage_accepts_an_unwrapped_payload():
    respx.get(PLAZA_URL).mock(return_value=httpx.Response(200, json=PAYLOAD["data"]))

    entries = {entry["catalogId"]: entry for entry in model_plaza.attach_model_usage(CATALOG)}

    assert entries["gpt-image-2"]["priceValue"] == 0.105


@respx.mock
def test_attach_model_usage_keeps_catalog_when_plaza_rejects_us():
    respx.get(PLAZA_URL).mock(return_value=httpx.Response(401, json={"code": 401}))

    assert model_plaza.attach_model_usage(CATALOG) == CATALOG


@respx.mock
def test_attach_model_usage_keeps_catalog_when_plaza_is_unreachable():
    respx.get(PLAZA_URL).mock(side_effect=httpx.ConnectError("boom"))

    assert model_plaza.attach_model_usage(CATALOG) == CATALOG


def test_expired_cache_is_served_without_waiting_for_the_relay(monkeypatch):
    """过期也先给旧数据：这个接口要 5–14 秒，不能让选模型等它。"""
    stale = PAYLOAD["data"]
    monkeypatch.setattr(
        model_plaza,
        "_CACHE",
        {"expires_at": time.monotonic() - 1, "payload": stale},
    )
    monkeypatch.setattr(model_plaza, "_fetch_payload", lambda: None)

    assert model_plaza.get_model_usage_index()["gpt-image-2"]["priceValue"] == 0.105


def test_plaza_endpoint_skips_groups_without_a_usable_public_host(monkeypatch):
    monkeypatch.setattr(
        model_plaza,
        "get_third_party_gateway_groups",
        lambda: [
            {
                "baseUrl": "http://localhost:3000/v1",
                "apiKey": "sk-local",
                "capabilities": [CAPABILITY_IMAGE],
                "modelMappings": [],
            },
            {
                "baseUrl": "https://relay.example/v1",
                "apiKey": "sk-test",
                "capabilities": [CAPABILITY_IMAGE],
                "modelMappings": [],
            },
        ],
    )

    assert model_plaza._plaza_endpoint() == ("https://relay.example", "sk-test")
