"""Operator administration: a local account from the environment, not a gateway user.

The administrator owns the installation's settings (the single-user settings routes, mounted
unchanged), the credit display ratio and the announcements. It has no gateway key and no
projects, so it cannot generate or see user data.
"""

from __future__ import annotations

import hmac
import os
import secrets
import time
from decimal import Decimal, InvalidOperation
from typing import Annotated

from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field

from novelvideo.aigcdo_billing import CreditDisplayPolicy
from novelvideo.api.routes.aigcdo_auth import AigcdoAPIRoute, _Input, _body
from novelvideo.runtime_settings import read_runtime_json, write_runtime_json

ADMIN_COOKIE = "st_admin"
ADMIN_TTL = 12 * 3600
ADMIN_USER = {"id": "aigcdo-admin", "user_id": "aigcdo-admin", "username": "admin", "role": "admin",
              "credential_kind": "browser_session"}
_POLICY_KEY = "aigcdo.credit_policy"
_ANNOUNCEMENTS_KEY = "aigcdo.announcements"


class AigcdoAdmin:
    """Username/password from the environment; unset means there is no administrator."""

    def __init__(self, encryption_key: bytes) -> None:
        self.username = os.environ.get("AIGCDO_ADMIN_USERNAME", "").strip()
        self._password = os.environ.get("AIGCDO_ADMIN_PASSWORD", "")
        if bool(self.username) != bool(self._password) or (self._password and len(self._password) < 12):
            raise ValueError("administrator needs a username and a password of at least 12 characters")
        self._cipher = Fernet(encryption_key)
        self._failures: list[float] = []

    def login(self, username: str, password: str) -> str:
        now = time.monotonic()
        self._failures = [t for t in self._failures if t > now - 300]
        # shortcut: one global window, so an attacker can lock the admin out for 5 minutes;
        # switch to per-client limits when a trusted client address is available.
        if len(self._failures) >= 10:
            raise HTTPException(429, "Too many attempts")
        if not self.username or not (
            hmac.compare_digest(username.encode(), self.username.encode())
            & hmac.compare_digest(password.encode(), self._password.encode())
        ):
            self._failures.append(now)
            raise HTTPException(401, "Invalid administrator credentials")
        return self._cipher.encrypt(b"aigcdo-admin:" + secrets.token_bytes(8)).decode()

    def verify(self, cookie: str | None) -> bool:
        if not cookie or not self.username:
            return False
        try:
            return self._cipher.decrypt(cookie.encode(), ttl=ADMIN_TTL).startswith(b"aigcdo-admin:")
        except (InvalidToken, ValueError):
            return False


def stored_credit_policy(default: CreditDisplayPolicy) -> CreditDisplayPolicy:
    saved = read_runtime_json(_POLICY_KEY, None)
    try:
        return CreditDisplayPolicy(Decimal(saved["credits_per_usd"]), saved["decimals"], saved["version"])
    except (TypeError, KeyError, ValueError, InvalidOperation):
        return default


def announcements() -> list[dict]:
    saved = read_runtime_json(_ANNOUNCEMENTS_KEY, [])
    return saved if isinstance(saved, list) else []


class _Login(_Input):
    username: Annotated[str, Field(min_length=1, max_length=128)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]


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


def create_aigcdo_admin_router(deployment, secure: bool) -> APIRouter:
    router = APIRouter(route_class=AigcdoAPIRoute)
    admin: AigcdoAdmin = deployment.admin

    @router.post("/auth/admin/login")
    async def login(request: Request):
        body = await _body(request, _Login)
        response = JSONResponse({"ok": True, "data": {"username": admin.username}})
        response.set_cookie(
            ADMIN_COOKIE, admin.login(body.username, body.password), max_age=ADMIN_TTL,
            path="/api/v1", secure=secure, httponly=True, samesite="strict",
        )
        return response

    @router.post("/auth/admin/logout")
    async def logout():
        # shortcut: the cookie is a stateless 12-hour token, so a copied one outlives logout;
        # keep a server-side revocation list if admin sessions must be killable.
        response = JSONResponse({"ok": True})
        response.delete_cookie(ADMIN_COOKIE, path="/api/v1", secure=secure, httponly=True, samesite="strict")
        return response

    @router.get("/announcements")
    async def public_announcements():
        # The shape the announcement drawer already reads (formerly a static JSON file).
        return JSONResponse({"announcements": [
            {"id": item["id"], "publishedAt": item["published_at"], "pinned": item["pinned"],
             "i18n": {"zh": {"title": item["title"], "body": item["body"]}}}
            for item in announcements()
        ]})

    @router.get("/admin/session")
    async def session():
        return {"ok": True, "data": {"username": admin.username}}

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
        write_runtime_json(_ANNOUNCEMENTS_KEY, [item.model_dump() for item in body.items])
        return {"ok": True}

    return router
