from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from novelvideo.aigcdo_billing import AigcdoBilling, CreditDisplayPolicy
from novelvideo.aigcdo_gateway import AigcdoGatewayClient, AigcdoGatewayError, GatewaySession
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo.api.routes.aigcdo_billing import create_aigcdo_billing_router
from novelvideo.ports.auth_contract import AuthError


def profile(uid):
    return {
        "id": uid, "email": f"user{uid}@example.test", "role": "user", "status": "active",
        "balance": "12.34567891" if uid == 73 else "-0.25", "frozen_balance": "2",
    }


def record(uid, **changes):
    return {
        "id": 101, "user_id": uid, "request_id": "request-101", "model": "image-model",
        "actual_cost": "0.12345678", "refunded_cost": "0.02345678", "net_actual_cost": "0.1",
        "billing_type": 0, "created_at": "2026-11-15T01:00:00Z",
        "input_tokens": 10, "output_tokens": 20,
        "api_key": {"key": "test-secret-not-for-browser"}, "ip_address": "192.0.2.1",
        **changes,
    }


def ok(data):
    return httpx.Response(200, json={"code": 0, "data": data})


@asynccontextmanager
async def billing_fixture(tmp_path, handler=None):
    reads = []

    async def transport(request):
        assert request.method == "GET"
        assert "x-api-key" not in request.headers
        uid = int(request.headers["authorization"].rsplit("-", 1)[1])
        reads.append((request.url.path, uid))
        if request.url.path.endswith("/auth/me"):
            return ok(profile(uid))
        if handler:
            result = handler(request, uid)
            return await result if hasattr(result, "__await__") else result
        if request.url.path.endswith("/user/profile"):
            return ok(profile(uid))
        return ok({"items": [record(uid)], "page": 1, "page_size": 20, "pages": 1, "total": 1})

    store = AigcdoSessionStore(tmp_path / "sessions.db", Fernet.generate_key())
    users = []
    for uid in (73, 74):
        users.append(await store.create(GatewaySession.model_validate({
            "access_token": f"access-{uid}", "refresh_token": f"refresh-{uid}",
            "expires_in": 86400, "token_type": "Bearer", "user": profile(uid),
        })))
    async with AigcdoGatewayClient(transport=httpx.MockTransport(transport)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        service = AigcdoBilling(auth, CreditDisplayPolicy(
            credits_per_unit=Decimal("100"), decimal_places=4, version="test-v1",
        ))
        yield service, users, reads


async def test_balance_is_already_available_and_conversion_is_exact(tmp_path):
    async with billing_fixture(tmp_path) as (service, (alice, bob), _):
        a, b = await asyncio.gather(service.balance(alice.raw_cookie), service.balance(bob.raw_cookie))
        assert a["available_amount"] == "12.34567891"
        assert a["frozen_amount"] == "2"
        assert a["available_credits"] == "1234.5679"
        assert a["frozen_credits"] == "200.0000"
        assert b["available_credits"] == "-25.0000"
        assert a["ledger_unit"] == "USD"
        assert a["policy"] == {
            "credits_per_unit": "100", "decimal_places": 4, "rounding": "ROUND_HALF_UP", "version": "test-v1",
        }
        assert "email" not in a and "user_id" not in a


async def test_usage_preserves_refunds_and_separates_subscription_from_wallet(tmp_path):
    def handler(request, uid):
        items = [record(uid), record(uid, id=102, billing_type=1)]
        return ok({"items": items, "page": 1, "page_size": 20, "pages": 1, "total": 2})

    async with billing_fixture(tmp_path, handler) as (service, (alice, _), _):
        result = await service.usage(alice.raw_cookie)
        a, b = result["items"]
        assert a["charged_amount"] == "0.12345678"
        assert a["refunded_amount"] == "0.02345678"
        assert a["net_amount"] == "0.1"
        assert a["net_credits"] == "10.0000"
        assert a["wallet_debit_credits"] == "10.0000"
        assert b["billing_type"] == "subscription"
        assert b["net_credits"] == "10.0000"
        assert b["wallet_debit_credits"] == "0.0000"
        assert result["total"] == 2
        assert "api_key" not in str(result) and "test-secret" not in str(result)
        assert "ip_address" not in str(result)


@pytest.mark.parametrize("endpoint", ["balance", "usage"])
async def test_foreign_identity_in_gateway_billing_response_is_rejected(tmp_path, endpoint):
    def handler(request, uid):
        if endpoint == "balance":
            return ok(profile(999))
        return ok({"items": [record(999)], "page": 1, "page_size": 20, "pages": 1, "total": 1})

    async with billing_fixture(tmp_path, handler) as (service, (alice, _), _):
        with pytest.raises((AuthError, AigcdoGatewayError)):
            await getattr(service, endpoint)(alice.raw_cookie)


@pytest.mark.parametrize("endpoint", ["balance", "usage"])
async def test_logout_while_read_is_pending_does_not_return_account_data(tmp_path, endpoint):
    started, release = asyncio.Event(), asyncio.Event()

    async def handler(request, uid):
        started.set()
        await release.wait()
        if endpoint == "balance":
            return ok(profile(uid))
        return ok({"items": [record(uid)], "page": 1, "page_size": 20, "pages": 1, "total": 1})

    async with billing_fixture(tmp_path, handler) as (service, (alice, _), _):
        task = asyncio.create_task(getattr(service, endpoint)(alice.raw_cookie))
        await asyncio.wait_for(started.wait(), 3)
        try:
            await service.auth.store.take_for_logout(alice.raw_cookie)
        finally:
            release.set()
        with pytest.raises(AuthError):
            await task


@pytest.mark.parametrize("ratio,places,version", [
    ("0", 4, "v1"), ("-1", 4, "v1"), ("NaN", 4, "v1"),
    ("Infinity", 4, "v1"), ("100", -1, "v1"), ("100", 9, "v1"),
    ("100", True, "v1"), ("100", 4, ""),
])
def test_invalid_display_policy_is_rejected(ratio, places, version):
    with pytest.raises(ValueError):
        CreditDisplayPolicy(credits_per_unit=Decimal(ratio), decimal_places=places, version=version)


def test_credit_conversion_uses_decimal_not_float_and_bounded_output():
    policy = CreditDisplayPolicy(credits_per_unit=Decimal("100"), decimal_places=4, version="v1")
    assert policy.display(Decimal("0.0000005")) == "0.0001"
    assert policy.display(Decimal("0")) == "0.0000"
    with pytest.raises(AigcdoGatewayError):
        policy.display(Decimal("1e100000"))


async def test_http_account_reads_require_cookie_and_are_private(tmp_path):
    async with billing_fixture(tmp_path) as (service, (alice, bob), _):
        app = FastAPI()
        app.include_router(create_aigcdo_billing_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
        ) as browser:
            for name in ("balance", "usage"):
                assert (await browser.get(f"/api/v1/account/billing/{name}")).status_code == 401
            browser.cookies.set("st_session", alice.raw_cookie)
            response = await browser.get("/api/v1/account/billing/balance")
            assert response.status_code == 200
            assert response.json()["data"]["available_credits"] == "1234.5679"
            assert response.headers["cache-control"] == "no-store"
            assert "access-73" not in response.text
            browser.cookies.set("st_session", bob.raw_cookie)
            other = await browser.get("/api/v1/account/billing/balance")
            assert other.json()["data"]["available_credits"] == "-25.0000"


@pytest.mark.parametrize("query", [
    "user_id=74", "api_key_id=99", "group_id=41", "page=0", "page_size=101",
    "start_date=2026-11-16&end_date=2026-11-15", "start_date=bad",
    "page=1&page=2", "model=a&model=b", "project_id=another",
])
async def test_http_rejects_unsafe_or_unsupported_filters(tmp_path, query):
    async with billing_fixture(tmp_path) as (service, (alice, _), reads):
        app = FastAPI()
        app.include_router(create_aigcdo_billing_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
            cookies={"st_session": alice.raw_cookie},
        ) as browser:
            response = await browser.get(f"/api/v1/account/billing/usage?{query}")
            assert response.status_code == 400
            assert response.headers["cache-control"] == "no-store"
        assert reads == []


async def test_gateway_outage_does_not_return_fake_zero_balance(tmp_path):
    async with billing_fixture(tmp_path, lambda *_: httpx.Response(503)) as (service, (alice, _), _):
        app = FastAPI()
        app.include_router(create_aigcdo_billing_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
            cookies={"st_session": alice.raw_cookie},
        ) as browser:
            response = await browser.get("/api/v1/account/billing/balance")
        assert response.status_code == 503
        assert response.json()["ok"] is False
        assert "available_credits" not in response.text


@pytest.mark.parametrize("endpoint,field", [
    ("balance", "balance"), ("balance", "frozen_balance"),
    ("usage", "actual_cost"), ("usage", "refunded_cost"), ("usage", "net_actual_cost"),
])
async def test_extreme_finite_gateway_amount_returns_safe_uncached_error(tmp_path, endpoint, field):
    def handler(request, uid):
        if endpoint == "balance":
            return ok({**profile(uid), field: "1e1000000"})
        return ok({
            "items": [record(uid, **{field: "1e1000000"})],
            "page": 1, "page_size": 20, "pages": 1, "total": 1,
        })

    async with billing_fixture(tmp_path, handler) as (service, (alice, _), _):
        app = FastAPI()
        app.include_router(create_aigcdo_billing_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://studio.example.test", cookies={"st_session": alice.raw_cookie},
        ) as browser:
            response = await browser.get(f"/api/v1/account/billing/{endpoint}")
        assert response.status_code == 502
        assert response.json()["code"] == "invalid_response"
        assert response.headers["cache-control"] == "no-store"
        assert "1e1000000" not in response.text


async def test_stale_page_cannot_read_new_cookie_owners_balance(tmp_path):
    async with billing_fixture(tmp_path) as (service, (alice, bob), reads):
        app = FastAPI()
        app.include_router(create_aigcdo_billing_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
            cookies={"st_session": bob.raw_cookie}, headers={"X-AIGCDO-User-ID": alice.user.id},
        ) as browser:
            response = await browser.get("/api/v1/account/billing/balance")
        assert response.status_code == 409
        assert response.json()["code"] == "session_changed"
        assert all(path == "/api/v1/auth/me" for path, _ in reads)
