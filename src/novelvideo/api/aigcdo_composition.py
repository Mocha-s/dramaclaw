"""Mount only owner-scoped APIs; legacy execution cannot inherit a shared Key."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection

from novelvideo.aigcdo_deployment import AigcdoDeployment
from novelvideo.aigcdo_gateway import AigcdoGatewayError
from novelvideo.aigcdo_model_runtime import user_key_scope
from novelvideo.api.auth import (
    AUTH_COOKIE_NAME, _bearer_token_from_request, _enforce_agent_request_boundary,
    _reject_unsupported_credential_classes, _verify_agent_bearer, get_api_user,
)
from novelvideo.api.routes.aigcdo_auth import create_aigcdo_auth_router, require_aigcdo_origin
from novelvideo.api.routes.aigcdo_billing import create_aigcdo_billing_router
from novelvideo.api.routes.aigcdo_payments import create_aigcdo_payments_router
from novelvideo.ports.auth_contract import AuthError, AuthFailureReason

_PUBLIC = {
    ("GET", "/api/v1/config"),
    ("GET", "/api/v1/auth/ui-config"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/login/2fa"),
    ("POST", "/api/v1/auth/logout"),
}
# Installation-wide editable state that has no per-user form yet.
_WITHHELD = ("/freezone/agent-config", "/freezone/skill-imports")
# Offered only while this host can isolate each user's Agent worker (deployment.agent_ready).
_AGENT = "/api/v1/chat"
_MANAGEMENT = ("/api/v1/model-gateway", "/api/v1/config/task-limits", "/api/v1/diagnostics")
_LOOPBACK = {"127.0.0.1", "::1"}


_PENDING = {
    "ok": False, "code": "aigcdo_integration_pending",
    "error": "This API is not yet connected to the AIGCDO user runtime",
}


class _Pending(Exception):
    pass


class AigcdoBoundary:
    def __init__(self, app, deployment: AigcdoDeployment):
        self.app = app
        self.deployment = deployment

    async def _run(self, reference: str, scope, receive, send):
        # Model calls and grants made while serving spend/bind this session's own key.
        key = await self.deployment.execution.request_key(reference)
        async with self.deployment.execution.session_scope(reference):
            with user_key_scope(key):
                await self.app(scope, receive, send)

    async def _agent(self, request: Request) -> str:
        """A sandboxed worker on this host calling back with its short-lived token."""
        token = _bearer_token_from_request(request)
        client = request.scope.get("client") or ("", 0)
        if (not token or not self.deployment.agent_ready or client[0] not in _LOOPBACK
                or any(name in request.headers for name in ("forwarded", "x-forwarded-for"))):
            raise HTTPException(401, "Agent authentication is not available")
        user = await _verify_agent_bearer(token)
        _enforce_agent_request_boundary(request, user)
        request.state.aigcdo_user = user
        return await self.deployment.execution.agent_parent(token)

    async def _websocket(self, scope, receive, send):
        connection = HTTPConnection(scope)
        try:
            # Browsers attach the cookie to any site's WebSocket; the Origin is the CSRF check.
            if (scope.get("path") != _AGENT + "/ws" or not self.deployment.agent_ready
                    or connection.headers.get("authorization")
                    or connection.headers.get("origin") != self.deployment.origin):
                raise AuthError(AuthFailureReason.INVALID)
            _reject_unsupported_credential_classes(connection)
            cookie = connection.cookies.get(AUTH_COOKIE_NAME)
            await self.deployment.auth.verify_session(cookie)
            reference = self.deployment.auth.store._hash(cookie)
        except Exception:
            await send({"type": "websocket.close", "code": 1008})
            return
        await self._run(reference, scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await self._websocket(scope, receive, send)
            return
        path = scope.get("path", "")
        protected = path == "/api" or path.startswith(("/api/", "/static/"))
        if scope["type"] != "http" or not protected:
            await self.app(scope, receive, send)
            return

        async def no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        request = Request(scope)
        reference = None
        try:
            _reject_unsupported_credential_classes(request)
            if request.headers.get("authorization"):
                reference = await self._agent(request)
            else:
                require_aigcdo_origin(request, self.deployment.origin)
                if (request.method, path) not in _PUBLIC:
                    cookie = request.cookies.get(AUTH_COOKIE_NAME)
                    request.state.aigcdo_user = await self.deployment.auth.verify_session(cookie)
                    reference = self.deployment.auth.store._hash(cookie)
            if reference is not None:
                if any(path == prefix or path.startswith(prefix + "/") for prefix in _MANAGEMENT):
                    raise HTTPException(
                        410 if request.state.aigcdo_user["role"] == "admin" else 403,
                        "Legacy platform configuration is not available",
                    )
                if any(part in path for part in _WITHHELD) or (
                    _AGENT in path and not self.deployment.agent_ready
                ):
                    raise _Pending()
        except _Pending:
            response = JSONResponse(_PENDING, status_code=503)
        except HTTPException as exc:
            response = JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)
        except AuthError as exc:
            response = JSONResponse(
                {"ok": False, "error": "Invalid session"},
                status_code=403 if exc.reason == AuthFailureReason.USER_SUSPENDED else 401,
            )
        except AigcdoGatewayError as exc:
            response = JSONResponse({"ok": False, "code": exc.code, "error": str(exc)}, status_code=exc.status_code)
        except Exception:
            response = JSONResponse({"ok": False, "error": "Authentication service unavailable"}, status_code=503)
        else:
            if reference is not None:
                await self._run(reference, scope, receive, no_store)
            else:
                await self.app(scope, receive, no_store)
            return
        await response(scope, receive, no_store)


def configure_aigcdo_app(application, deployment: AigcdoDeployment) -> None:
    from novelvideo.api import api_router, register_verification_routes

    application.state.aigcdo_deployment = deployment
    application.add_middleware(AigcdoBoundary, deployment=deployment)

    @application.exception_handler(Exception)
    async def internal_error(request: Request, exc: Exception):
        return JSONResponse(
            {"ok": False, "error": "Internal service error"}, status_code=500,
            headers={"Cache-Control": "no-store"},
        )

    async def authenticated_user(request: Request) -> dict:
        user = getattr(request.state, "aigcdo_user", None)
        if user is None:
            raise HTTPException(401, "Invalid session")
        return user

    application.dependency_overrides[get_api_user] = authenticated_user
    router = APIRouter(prefix="/api/v1")
    router.include_router(create_aigcdo_auth_router(
        deployment.auth, deployment.origin, application_keys=deployment.application_keys,
    ))
    router.include_router(create_aigcdo_billing_router(deployment.billing))
    router.include_router(create_aigcdo_payments_router(deployment.payments))
    # Registered first, so the AIGCDO auth routes shadow the single-user ones. Every creative
    # route authorises through the owner-only project port and runs on the caller's key;
    # the boundary refuses whatever _WITHHELD and _MANAGEMENT name.
    register_verification_routes()
    application.include_router(router)
    application.include_router(api_router)

    @application.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def unavailable(path: str, request: Request):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            require_aigcdo_origin(request, deployment.origin)
        return JSONResponse(_PENDING, status_code=503)
