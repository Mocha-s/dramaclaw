"""Administrator-only settings beyond the single-user ones: credit ratio and announcements.

Administrators are the gateway accounts named in AIGCDO_ADMIN_USER_IDS; the boundary admits
only them to these routes and to the single-user settings routes.
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from novelvideo.aigcdo_billing import CreditDisplayPolicy
from novelvideo.api.routes.aigcdo_auth import AigcdoAPIRoute, _Input, _body
from novelvideo.runtime_settings import read_runtime_json, write_runtime_json

_POLICY_KEY = "aigcdo.credit_policy"
_ANNOUNCEMENTS_KEY = "aigcdo.announcements"


def stored_credit_policy(default: CreditDisplayPolicy) -> CreditDisplayPolicy:
    saved = read_runtime_json(_POLICY_KEY, None)
    try:
        return CreditDisplayPolicy(Decimal(saved["credits_per_usd"]), saved["decimals"], saved["version"])
    except (TypeError, KeyError, ValueError, InvalidOperation):
        return default


def announcements() -> list[dict]:
    saved = read_runtime_json(_ANNOUNCEMENTS_KEY, [])
    return saved if isinstance(saved, list) else []


class _Credits(_Input):
    credits_per_usd: Annotated[str, Field(pattern=r"^[0-9]{1,9}(\.[0-9]{1,6})?$")]
    decimals: Annotated[int, Field(ge=0, le=8)]


class _Announcement(_Input):
    id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    body: Annotated[str, Field(min_length=1, max_length=5000)]
    pinned: bool = False
    published_at: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")]


class _Announcements(_Input):
    items: Annotated[list[_Announcement], Field(max_length=50)]


def create_aigcdo_admin_router(deployment) -> APIRouter:
    router = APIRouter(route_class=AigcdoAPIRoute)
    @router.get("/announcements")
    async def public_announcements():
        # The shape the announcement drawer already reads (formerly a static JSON file).
        return JSONResponse({"announcements": [
            {"id": item["id"], "publishedAt": item["published_at"], "pinned": item["pinned"],
             "i18n": {"zh": {"title": item["title"], "body": item["body"]}}}
            for item in announcements()
        ]})

    @router.get("/admin/credits")
    async def credits():
        policy = deployment.billing.policy
        return {"ok": True, "data": {
            "credits_per_usd": format(policy.credits_per_unit, "f"), "decimals": policy.decimal_places,
        }}

    @router.post("/admin/credits")
    async def save_credits(request: Request):
        body = await _body(request, _Credits)
        try:
            # A new version per change: orders keep the ratio they were created under.
            policy = CreditDisplayPolicy(Decimal(body.credits_per_usd), body.decimals, f"admin-{int(time.time())}")
        except ValueError:
            raise HTTPException(400, "Invalid credit ratio") from None
        write_runtime_json(_POLICY_KEY, {
            "credits_per_usd": body.credits_per_usd, "decimals": body.decimals, "version": policy.version,
        })
        deployment.billing.policy = deployment.payments.policy = policy
        return {"ok": True}

    @router.get("/admin/announcements")
    async def list_announcements():
        return {"ok": True, "data": {"items": announcements()}}

    @router.post("/admin/announcements")
    async def save_announcements(request: Request):
        body = await _body(request, _Announcements)
        if len({item.id for item in body.items}) != len(body.items):
            raise HTTPException(400, "Duplicate announcement id")
        for item in body.items:
            try:
                # The drawer rejects the whole list if one entry is blank or has an impossible date.
                datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(400, "Invalid announcement date") from None
            if not item.title.strip() or not item.body.strip():
                raise HTTPException(400, "Announcement needs a title and a body")
        write_runtime_json(_ANNOUNCEMENTS_KEY, [item.model_dump() for item in body.items])
        return {"ok": True}

    return router
