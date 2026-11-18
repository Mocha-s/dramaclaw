from __future__ import annotations

import json
from contextlib import asynccontextmanager

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request

import novelvideo.aigcdo_sessions as sessions
from novelvideo.aigcdo_gateway import AigcdoGatewayClient
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo.api.routes.aigcdo_auth import create_aigcdo_auth_router
from novelvideo.ports.aigcdo_project import AigcdoProjectAccess, AigcdoProjectRegistry
from novelvideo.ports.auth_contract import AuthError
from novelvideo.ports.registry import register_port
from novelvideo.project_context import resolve_project_context

ORIGIN = "https://studio.example.test"


def public_settings(**changes):
    return {
        "registration_enabled": True, "email_verify_enabled": False,
        "invitation_code_enabled": False, "turnstile_enabled": False,
        "tencent_captcha_enabled": False, "aliyun_captcha_enabled": False,
        "login_agreement_enabled": True, "login_agreement_revision": "revision-1",
        "login_agreement_documents": [{"id": "terms", "title": "Terms", "content_md": "Terms text"}],
        "site_logo": "unneeded-logo", "unrelated_secret": "must-not-be-forwarded",
        **changes,
    }


async def test_public_auth_ui_config_filters_gateway_fields(tmp_path):
    def gateway(request):
        assert request.url.path == "/api/v1/settings/public"
        assert "authorization" not in request.headers
        return success(public_settings())

    async with http_app(tmp_path, gateway) as (client, _, _):
        response = await client.get("/api/v1/auth/ui-config")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["auth_provider"] == "aigcdo"
        assert data["registration_enabled"] and data["registration_supported"] and data["login_supported"]
        assert data["phone_otp_entry_visible"] is False
        assert data["login_agreement_documents"][0]["content_md"] == "Terms text"
        assert "unrelated_secret" not in response.text and "site_logo" not in response.text
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("flag", [
    "email_verify_enabled", "invitation_code_enabled",
    "tencent_captcha_enabled", "aliyun_captcha_enabled",
])
async def test_registration_ui_does_not_offer_unsupported_prerequisites(tmp_path, flag):
    async with http_app(tmp_path, lambda _: success(public_settings(**{flag: True}))) as (client, _, _):
        data = (await client.get("/api/v1/auth/ui-config")).json()["data"]
        assert data["registration_supported"] is False
        assert data["login_supported"] is (flag in {"email_verify_enabled", "invitation_code_enabled"})


@pytest.mark.parametrize("settings", [
    {}, public_settings(registration_enabled="yes"),
    public_settings(login_agreement_documents=[]),
    public_settings(login_agreement_revision=""),
])
async def test_invalid_auth_settings_are_not_treated_as_open_registration(tmp_path, settings):
    async with http_app(tmp_path, lambda _: success(settings)) as (client, _, _):
        response = await client.get("/api/v1/auth/ui-config")
        assert response.status_code == 502
        assert response.json()["code"] == "invalid_response"
        assert response.headers["cache-control"] == "no-store"


async def test_application_recovery_rejects_old_page_identity(tmp_path):
    async with http_app(tmp_path) as (client, _, _):
        await login(client)
        response = await client.post("/api/v1/auth/application", json={},
                                     headers={"X-AIGCDO-User-ID": "another-user"})
        assert response.status_code == 409
        assert response.json()["code"] == "session_changed"


def profile(user_id=73):
    return {
        "id": user_id, "email": f"creator{user_id}@example.test",
        "role": "user", "status": "active", "balance": "12.5", "frozen_balance": "0",
    }


def success(data):
    return httpx.Response(200, json={"code": 0, "data": data})


def session(user_id=73):
    return {
        "access_token": f"access-secret-{user_id}", "refresh_token": f"refresh-secret-{user_id}",
        "expires_in": 86400, "token_type": "Bearer", "user": profile(user_id),
    }


def default_gateway(request):
    if request.url.path.endswith("/me"):
        return success(profile(int(request.headers["authorization"].rsplit("-", 1)[1])))
    if request.url.path.endswith("/logout"):
        return success({"message": "logged out"})
    data = json.loads(request.content)
    user_id = 74 if data.get("email") == "bob@example.test" else 73
    return success(session(user_id))


@asynccontextmanager
async def http_app(tmp_path, handler=default_gateway):
    store = AigcdoSessionStore(tmp_path / "auth.db", Fernet.generate_key())
    async with AigcdoGatewayClient(transport=httpx.MockTransport(handler)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        app = FastAPI()
        app.include_router(create_aigcdo_auth_router(auth, ORIGIN), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            headers={"Origin": ORIGIN},
        ) as client:
            yield client, auth, app


async def login(client, email="creator@example.test"):
    return await client.post("/api/v1/auth/login", json={"username": email, "password": "test-password"})


async def test_login_cookie_me_and_logout_do_not_expose_gateway_credentials(tmp_path):
    async with http_app(tmp_path) as (client, auth, _):
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        response = await login(client)
        assert response.status_code == 200
        assert response.json()["data"]["role"] == "user"
        for secret in ("access-secret", "refresh-secret", "test-password"):
            assert secret not in response.text
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=lax" in cookie
        assert "Max-Age=604800" in cookie
        assert "Domain=" not in cookie
        assert response.headers["cache-control"] == "no-store"
        raw_cookie = client.cookies.get("st_session")
        me = await client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["data"]["id"] == response.json()["data"]["id"]
        assert "credit_balance" not in me.json()["data"]
        assert me.headers["cache-control"] == "no-store"
        logout = await client.post("/api/v1/auth/logout")
        assert logout.status_code == 200
        assert "Max-Age=0" in logout.headers["set-cookie"]
        assert (await client.get("/api/v1/auth/me")).status_code == 401
        with pytest.raises(AuthError):
            await auth.verify_session(raw_cookie)


async def test_register_maps_identity_in_project_without_redirect(tmp_path):
    async with http_app(tmp_path) as (client, auth, _):
        response = await client.post("/api/v1/auth/register", json={
            "email": "creator@example.test", "password": "test-password", "verify_code": "123456",
        })
        assert response.status_code == 200
        assert "location" not in response.headers
        user = response.json()["data"]
        assert await auth.store.get_user_id(user["username"]) == user["id"]
        assert (await client.get("/api/v1/auth/me")).json()["data"]["id"] == user["id"]


async def test_login_rotates_existing_local_cookie(tmp_path):
    async with http_app(tmp_path) as (client, auth, _):
        await login(client)
        old = client.cookies.get("st_session")
        await login(client)
        assert client.cookies.get("st_session") != old
        with pytest.raises(AuthError):
            await auth.verify_session(old)


@pytest.mark.parametrize("origin", [None, "null", "https://evil.example", ORIGIN + ".evil"])
async def test_cross_site_auth_requests_are_rejected_before_gateway(tmp_path, origin):
    def unexpected(_):
        pytest.fail("untrusted origin sent credentials to gateway")

    async with http_app(tmp_path, unexpected) as (client, _, _):
        client.headers.pop("origin")
        if origin is not None:
            client.headers["origin"] = origin
        for path in ("login", "register", "login/2fa", "logout"):
            response = await client.post(f"/api/v1/auth/{path}", json={})
            assert response.status_code == 403


async def test_host_header_cannot_make_attacker_origin_trusted(tmp_path):
    async with http_app(tmp_path) as (client, _, _):
        response = await client.post("/api/v1/auth/login", headers={
            "Origin": "https://evil.example", "Host": "evil.example",
        }, json={"username": "creator@example.test", "password": "test-password"})
        assert response.status_code == 403


@pytest.mark.parametrize("body", [
    {"username": "creator@example.test", "password": ""},
    {"username": "", "password": "secret-not-for-errors"},
    {"username": "creator@example.test", "password": "secret-not-for-errors", "role": "admin"},
    ["secret-not-for-errors"],
])
async def test_invalid_body_never_echoes_credentials(tmp_path, body):
    async with http_app(tmp_path) as (client, _, _):
        response = await client.post("/api/v1/auth/login", json=body)
        assert response.status_code == 400
        assert "secret-not-for-errors" not in response.text
        assert "st_session" not in response.headers.get("set-cookie", "")


async def test_auth_requires_json_and_bounds_body_size(tmp_path):
    async with http_app(tmp_path) as (client, _, _):
        assert (await client.post("/api/v1/auth/login", content="password=hidden")).status_code == 415
        response = await client.post(
            "/api/v1/auth/login", content='{"password":"' + "x" * 17000 + '"}',
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        invalid = await client.post(
            "/api/v1/auth/login", content='{"password":"secret-not-for-errors"',
            headers={"Content-Type": "application/json"},
        )
        assert invalid.status_code == 400
        assert "secret-not-for-errors" not in invalid.text


async def test_2fa_challenge_stays_in_encrypted_cookie_and_issues_no_session(tmp_path):
    def handle(request):
        if request.url.path.endswith("/login"):
            return success({"requires_2fa": True, "temp_token": "challenge-secret"})
        if request.url.path.endswith("/2fa"):
            assert json.loads(request.content) == {"temp_token": "challenge-secret", "totp_code": "123456"}
        return default_gateway(request)

    async with http_app(tmp_path, handle) as (client, _, _):
        challenge = await login(client)
        assert challenge.status_code == 202
        assert challenge.json()["data"] == {"requires_2fa": True}
        assert client.cookies.get("st_session") is None
        assert "challenge-secret" not in challenge.text
        assert "challenge-secret" not in challenge.headers["set-cookie"]
        assert "HttpOnly" in challenge.headers["set-cookie"]
        result = await client.post("/api/v1/auth/login/2fa", json={"code": "123456"})
        assert result.status_code == 200
        assert client.cookies.get("st_auth_challenge") is None
        assert client.cookies.get("st_session")


async def test_expired_or_forged_2fa_cookie_is_rejected(tmp_path, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)

    def handle(request):
        assert request.url.path.endswith("/login")
        return success({"requires_2fa": True, "temp_token": "challenge-secret"})

    async with http_app(tmp_path, handle) as (client, _, _):
        assert (await client.post("/api/v1/auth/login/2fa", json={"code": "123456"})).status_code == 401
        await login(client)
        challenge = client.cookies.get("st_auth_challenge")
        now += 301
        # Explicit Cookie ensures this tests server expiry, not the client's cookie jar.
        response = await client.post("/api/v1/auth/login/2fa",
            headers={"Cookie": f"st_auth_challenge={challenge}"}, json={"code": "123456"})
        assert response.status_code == 401
        response = await client.post("/api/v1/auth/login/2fa",
            headers={"Cookie": "st_auth_challenge=forged"}, json={"code": "123456"})
        assert response.status_code == 401


async def test_gateway_failures_are_safe_and_logout_502_still_clears_cookie(tmp_path):
    def handle(request):
        if request.url.path.endswith("/logout"):
            return httpx.Response(502, text="private gateway response")
        return default_gateway(request)

    async with http_app(tmp_path, handle) as (client, auth, _):
        await login(client)
        raw_cookie = client.cookies.get("st_session")
        response = await client.post("/api/v1/auth/logout")
        assert response.status_code == 503
        assert response.json()["local_session_revoked"] is True
        assert "private gateway response" not in response.text
        assert "Max-Age=0" in response.headers["set-cookie"]
        with pytest.raises(AuthError):
            await auth.verify_session(raw_cookie)


async def test_bad_password_sets_no_session_cookie(tmp_path):
    async with http_app(
        tmp_path, lambda _: httpx.Response(401, json={"message": "secret-not-for-errors"})
    ) as (client, _, _):
        response = await login(client)
        assert response.status_code == 401
        assert response.json()["ok"] is False
        assert "secret-not-for-errors" not in response.text
        assert client.cookies.get("st_session") is None


async def test_real_cookie_identities_cannot_read_each_others_project(tmp_path, monkeypatch):
    from novelvideo import config
    for key in ("OUTPUT_DIR", "STATE_DIR", "RUNTIME_DIR"):
        monkeypatch.setattr(config, key, str(tmp_path / key.lower()))
    async with http_app(tmp_path) as (alice, auth, app):
        registry = AigcdoProjectRegistry(auth.store)
        register_port("project_registry", registry)
        register_port("project_access", AigcdoProjectAccess(registry))

        @app.get("/test/projects/{project_id}")
        async def get_project(project_id: str, request: Request):
            user = await auth.verify_session(request.cookies.get("st_session"))
            context = await resolve_project_context(user=user, project_id=project_id)
            return {"owner_id": context.owner_id}

        identity = (await login(alice)).json()["data"]
        project = await registry.create_project(
            owner_user_id=identity["id"], owner_username=identity["username"], name="demo",
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN, headers={"Origin": ORIGIN}
        ) as bob:
            await login(bob, "bob@example.test")
            assert (await alice.get(f"/test/projects/{project.id}")).status_code == 200
            assert (await bob.get(f"/test/projects/{project.id}")).status_code == 403


@pytest.mark.parametrize("endpoint", ["login", "register"])
async def test_invalid_unicode_password_is_safe_400_before_gateway(tmp_path, endpoint):
    def unexpected(_):
        pytest.fail("invalid Unicode must not reach the gateway")

    async with http_app(tmp_path, unexpected) as (client, _, _):
        field = "username" if endpoint == "login" else "email"
        body = {field: "creator@example.test", "password": "hidden-\ud800"}
        response = await client.post(
            f"/api/v1/auth/{endpoint}",
            content=json.dumps(body).encode("ascii"),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400
        assert response.json()["ok"] is False
        assert "hidden-" not in response.text
        assert response.headers["cache-control"] == "no-store"


async def test_turnstile_site_key_is_offered_and_the_token_is_forwarded_once(tmp_path):
    """The gateway turned Turnstile on (2026-11-17) and refused every token-less login."""
    seen = []

    def gateway(request):
        if request.url.path.endswith("/settings/public"):
            return success(public_settings(turnstile_enabled=True, turnstile_site_key="0x4AAAtest"))
        body = json.loads(request.content)
        if request.url.path.endswith("/auth/logout"):
            return success({})
        seen.append((request.url.path, body.get("turnstile_token")))
        if body.get("turnstile_token") != "token-from-widget":
            return httpx.Response(400, json={"code": 400, "reason": "TURNSTILE_VERIFICATION_FAILED"})
        return success(session())

    async with http_app(tmp_path, gateway) as (client, _, _):
        data = (await client.get("/api/v1/auth/ui-config")).json()["data"]
        assert data["login_supported"] and data["registration_supported"]
        assert data["turnstile_site_key"] == "0x4AAAtest"
        denied = await client.post("/api/v1/auth/login", json={
            "username": "creator@example.test", "password": "test-password"})
        assert denied.status_code == 400
        for path, body in (
            ("login", {"username": "creator@example.test", "password": "test-password"}),
            ("register", {"email": "creator@example.test", "password": "test-password"}),
        ):
            response = await client.post(f"/api/v1/auth/{path}", json={**body, "turnstile_token": "token-from-widget"})
            assert response.status_code == 200, response.text
            assert "token-from-widget" not in response.text
        assert seen[1:] == [("/api/v1/auth/login", "token-from-widget"), ("/api/v1/auth/register", "token-from-widget")]
        bad = await client.post("/api/v1/auth/login", json={
            "username": "creator@example.test", "password": "test-password", "turnstile_token": "x" * 4097})
        assert bad.status_code == 400 and len(seen) == 3


async def test_turnstile_without_a_site_key_is_not_offered(tmp_path):
    async with http_app(tmp_path, lambda _: success(public_settings(turnstile_enabled=True))) as (client, _, _):
        data = (await client.get("/api/v1/auth/ui-config")).json()["data"]
        assert not data["login_supported"] and data["turnstile_site_key"] == ""


async def test_login_page_settings_are_reused_and_survive_a_gateway_outage(tmp_path, monkeypatch):
    from novelvideo import aigcdo_gateway

    calls = []

    def gateway(request):
        calls.append(request.url.path)
        if len(calls) > 1:
            raise httpx.ConnectTimeout("down")
        return success(public_settings())

    async with http_app(tmp_path, gateway) as (client, _, _):
        first = (await client.get("/api/v1/auth/ui-config")).json()
        assert (await client.get("/api/v1/auth/ui-config")).json() == first
        assert len(calls) == 1
        later = aigcdo_gateway.time.monotonic() + aigcdo_gateway.AUTH_SETTINGS_TTL + 1
        monkeypatch.setattr(aigcdo_gateway.time, "monotonic", lambda: later)
        assert (await client.get("/api/v1/auth/ui-config")).json() == first
        assert len(calls) == 2
