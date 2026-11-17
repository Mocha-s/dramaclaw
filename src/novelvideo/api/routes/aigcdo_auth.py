"""Composable, same-origin Cookie authentication routes for AIGCDO."""

from __future__ import annotations

import json
import logging
from typing import Annotated, TypeVar
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from novelvideo.aigcdo_application_keys import AigcdoApplicationKeys, ApplicationKeyError
from novelvideo.aigcdo_gateway import AigcdoGatewayError, GatewayLoginChallenge
from novelvideo.aigcdo_sessions import AigcdoAuthPort, SESSION_TTL
from novelvideo.api.auth import AUTH_COOKIE_NAME
from novelvideo.ports.auth_contract import AuthError, AuthFailureReason, LoginResult

logger = logging.getLogger(__name__)
CHALLENGE_COOKIE = "st_auth_challenge"
_BODY_LIMIT = 16 * 1024
_Model = TypeVar("_Model", bound=BaseModel)
_Email = Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
_Password = Annotated[SecretStr, Field(min_length=1, max_length=4096)]
# A single-use Cloudflare Turnstile response; the gateway is the one that verifies it.
_Turnstile = Annotated[str, Field(max_length=4096, pattern=r"^[A-Za-z0-9._-]*$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class _Login(_Input):
    username: _Email
    password: _Password
    turnstile_token: _Turnstile = ""


class _Register(_Input):
    email: _Email
    password: Annotated[SecretStr, Field(min_length=6, max_length=4096)]
    verify_code: Annotated[str, Field(max_length=64)] = ""
    turnstile_token: _Turnstile = ""


class _SecondFactor(_Input):
    code: Annotated[str, Field(pattern=r"^[0-9]{6}$")]


async def _body(request: Request, model: type[_Model]) -> _Model:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415, "JSON body required")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > _BODY_LIMIT:
            raise HTTPException(413, "Authentication request too large")
        content.extend(chunk)
    try:
        data = json.loads(content)
        # JSON escape sequences can represent lone surrogates that HTTPX cannot encode.
        json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return model.model_validate(data)
    except (ValueError, ValidationError):
        # FastAPI's default validation detail may echo input, including passwords.
        raise HTTPException(400, "Invalid authentication request") from None


class AigcdoAPIRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                response = await original(request)
            except AigcdoGatewayError as exc:
                response = JSONResponse(
                    {"ok": False, "error": str(exc), "code": exc.code}, status_code=exc.status_code,
                )
            except AuthError as exc:
                suspended = exc.reason == AuthFailureReason.USER_SUSPENDED
                response = JSONResponse(
                    {"ok": False, "error": "Access denied" if suspended else "Invalid session"},
                    status_code=403 if suspended else 401,
                )
            except HTTPException as exc:
                response = JSONResponse(
                    {"ok": False, "error": exc.detail}, status_code=exc.status_code,
                )
            response.headers["Cache-Control"] = "no-store"
            return response

        return handle


def create_aigcdo_auth_router(
    auth: AigcdoAuthPort, app_origin: str, *,
    application_keys: AigcdoApplicationKeys | None = None,
) -> APIRouter:
    """Compose only with owner-scoped project, task and administrator boundaries."""
    if application_keys is not None and application_keys.auth is not auth:
        raise ValueError("application Keys must use the router's authentication service")
    origin = trusted_app_origin(app_origin)
    secure = urlsplit(origin).scheme == "https"

    def require_same_origin(request: Request) -> None:
        require_aigcdo_origin(request, origin)

    router = APIRouter(
        prefix="/auth", route_class=AigcdoAPIRoute, dependencies=[Depends(require_same_origin)],
    )

    def clear_challenge(response: JSONResponse) -> None:
        response.delete_cookie(
            CHALLENGE_COOKIE, path="/api/v1/auth", secure=secure, httponly=True, samesite="strict",
        )

    async def application_status(cookie: str) -> dict:
        if application_keys is None:
            raise HTTPException(503, "Application provisioning is not configured")
        try:
            key = await application_keys.ensure(cookie)
        except (ApplicationKeyError, AigcdoGatewayError) as exc:
            return {
                "status": "pending" if exc.status_code >= 500 else "blocked",
                "code": exc.code,
            }
        return {"status": "ready", "group_id": key.group_id}

    async def authenticated_response(result: LoginResult, request: Request) -> JSONResponse:
        old_cookie = request.cookies.get(AUTH_COOKIE_NAME)
        if old_cookie:
            try:
                await auth.revoke_session(old_cookie)
            except AigcdoGatewayError:
                logger.warning("Previous local session revoked; gateway logout unavailable")
        data = {**result.user.to_legacy_dict(), "credential_kind": "browser_session"}
        if application_keys is not None:
            data["application"] = await application_status(result.raw_cookie)
        response = JSONResponse({"ok": True, "data": data})
        response.set_cookie(
            AUTH_COOKIE_NAME, result.raw_cookie, max_age=SESSION_TTL,
            path="/", secure=secure, httponly=True, samesite="lax",
        )
        clear_challenge(response)
        return response

    @router.get("/ui-config")
    async def ui_config():
        settings = await auth.gateway.public_auth_settings()
        site_key = settings.turnstile_site_key if settings.turnstile_enabled else ""
        captcha = (settings.tencent_captcha_enabled or settings.aliyun_captcha_enabled
                   or (settings.turnstile_enabled and not site_key))
        return {"ok": True, "data": {
            "auth_provider": "aigcdo", "phone_otp_entry_visible": False,
            "registration_enabled": settings.registration_enabled,
            "registration_supported": not (
                captcha or settings.email_verify_enabled or settings.invitation_code_enabled
            ),
            "login_supported": not captcha,
            "turnstile_site_key": site_key,
            "login_agreement_enabled": settings.login_agreement_enabled,
            "login_agreement_revision": settings.login_agreement_revision,
            "login_agreement_documents": [document.model_dump() for document in settings.login_agreement_documents],
        }}

    @router.post("/login")
    async def login(request: Request):
        body = await _body(request, _Login)
        result = await auth.login(
            body.username, body.password.get_secret_value(), turnstile_token=body.turnstile_token,
        )
        if isinstance(result, GatewayLoginChallenge):
            response = JSONResponse({"ok": True, "data": {"requires_2fa": True}}, status_code=202)
            response.set_cookie(
                CHALLENGE_COOKIE, auth.store.seal_login_challenge(result), max_age=300,
                path="/api/v1/auth", secure=secure, httponly=True, samesite="strict",
            )
            return response
        return await authenticated_response(result, request)

    @router.post("/register")
    async def register(request: Request):
        body = await _body(request, _Register)
        result = await auth.register(
            body.email, body.password.get_secret_value(), verify_code=body.verify_code,
            turnstile_token=body.turnstile_token,
        )
        return await authenticated_response(result, request)

    @router.post("/login/2fa")
    async def login_2fa(request: Request):
        body = await _body(request, _SecondFactor)
        token = auth.store.open_login_challenge(request.cookies.get(CHALLENGE_COOKIE, ""))
        return await authenticated_response(await auth.login_2fa(token, body.code), request)

    @router.get("/me")
    async def me(request: Request):
        user = await auth.verify_session(request.cookies.get(AUTH_COOKIE_NAME))
        return {"ok": True, "data": user}

    @router.post("/application")
    async def ensure_application(request: Request):
        await _body(request, _Input)
        await require_aigcdo_account(request, auth)
        return {"ok": True, "data": await application_status(request.cookies.get(AUTH_COOKIE_NAME, ""))}

    @router.post("/logout")
    async def logout(request: Request):
        response = JSONResponse({"ok": True})
        cookie = request.cookies.get(AUTH_COOKIE_NAME)
        if cookie:
            try:
                await auth.revoke_session(cookie)
            except AigcdoGatewayError:
                response = JSONResponse({
                    "ok": False, "local_session_revoked": True,
                    "error": "Local session revoked; gateway logout unavailable",
                }, status_code=503)
        response.delete_cookie(
            AUTH_COOKIE_NAME, path="/", secure=secure, httponly=True, samesite="lax",
        )
        clear_challenge(response)
        return response

    return router


def trusted_app_origin(app_origin: str) -> str:
    origin = app_origin.rstrip("/")
    parsed = urlsplit(origin)
    if (
        not parsed.hostname or parsed.username or parsed.password or parsed.path
        or parsed.query or parsed.fragment
        or (parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        ))
    ):
        raise ValueError("app_origin must be an HTTPS origin or loopback HTTP origin")
    return origin


def require_aigcdo_origin(request: Request, origin: str) -> None:
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.headers.get("origin") != origin or request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Untrusted authentication request origin")


async def require_aigcdo_account(request: Request, auth: AigcdoAuthPort) -> None:
    """Bind a private page's identity to this request's Cookie, never to a supplied user ID."""
    expected = request.headers.getlist("x-aigcdo-user-id")
    if not expected:
        return
    if len(expected) != 1 or not expected[0] or len(expected[0]) > 128:
        raise HTTPException(400, "Invalid account identity header")
    user = await auth.verify_session(request.cookies.get(AUTH_COOKIE_NAME))
    if user["id"] != expected[0]:
        raise AigcdoGatewayError("session_changed")
