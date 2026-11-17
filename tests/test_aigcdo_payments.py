from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from decimal import Decimal

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from novelvideo.aigcdo_billing import CreditDisplayPolicy
from novelvideo.aigcdo_gateway import AigcdoGatewayClient, AigcdoGatewayError, GatewaySession
from novelvideo.aigcdo_payments import AigcdoPayments, AigcdoPaymentStore
from novelvideo.api.routes.aigcdo_payments import create_aigcdo_payments_router
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo.ports.auth_contract import AuthError

ORIGIN = "https://studio.example.test"
ATTEMPT = "checkout-attempt-0001"


def profile(uid):
    return {"id": uid, "email": f"user{uid}@example.test", "role": "user",
            "status": "active", "balance": "12", "frozen_balance": "0"}


def ok(data):
    return httpx.Response(200, json={"code": 0, "data": data})


class Gateway:
    def __init__(self):
        self.orders = {}
        self.posts = []
        self.timeout = False
        self.foreign = False
        self.disabled = False
        self.pay_url = "https://cashier.example.test/pay?ticket=opaque"
        self.started = None
        self.release = None
        self.read_started = None
        self.read_release = None
        self.created_payment_type = None
        self.qr_code = ""
        self.result_type = "order_created"
        self.bonus_amount = "0"
        self.checkout_started = None
        self.checkout_release = None

    async def __call__(self, request):
        assert request.url.host == "api.aigcdo.top"
        assert "x-api-key" not in request.headers
        uid = int(request.headers["authorization"].rsplit("-", 1)[1])
        path = request.url.path
        if path.endswith("/auth/me"):
            return ok(profile(uid))
        if path.endswith("/checkout-info"):
            disabled = self.disabled
            if self.checkout_started:
                self.checkout_started.set()
                await self.checkout_release.wait()
            return ok({
                "methods": {"alipay": {
                    "payment_type": "alipay", "currency": "CNY", "fee_rate": "0",
                    "single_min": "1", "single_max": "1000", "daily_limit": "5000",
                }},
                "balance_disabled": disabled, "balance_recharge_multiplier": "2",
                "recharge_fee_rate": "0", "recharge_bonus_mode": "bonus",
                "recharge_bonus_tiers": [], "global_min": "1", "global_max": "1000",
                "stripe_publishable_key": "not-needed", "help_text": "<script>not-needed</script>",
            })
        if path.endswith("/orders") and request.method == "POST":
            body = json.loads(request.content)
            assert body == {
                "amount": 10.25, "payment_type": "alipay", "order_type": "balance",
                "return_url": ORIGIN + "/payment/result", "is_mobile": False,
            }
            assert request.headers["referer"] == ORIGIN + "/"
            self.posts.append((uid, body))
            if self.started:
                self.started.set()
                await self.release.wait()
            oid = len(self.orders) + 1
            order = {
                "id": oid, "user_id": uid, "amount": str(Decimal("20.5") + Decimal(self.bonus_amount)),
                "pay_amount": "10.25",
                "fee_rate": "0", "bonus_amount": self.bonus_amount, "currency": "CNY",
                "payment_type": self.created_payment_type or "alipay",
                "out_trade_no": f"trade-{oid}", "order_type": "balance",
                "status": "PENDING", "created_at": "2026-11-15T00:00:00Z",
                "expires_at": "2099-11-15T00:30:00Z",
                "paid_at": None, "completed_at": None, "refund_amount": "0",
                "user_email": "private@example.test", "recharge_code": "test-private-code",
            }
            self.orders[oid] = order
            if self.timeout:
                raise httpx.ReadTimeout("test-uncertain-order", request=request)
            return ok({
                "order_id": oid, **{k: order[k] for k in (
                    "amount", "pay_amount", "fee_rate", "bonus_amount", "currency",
                    "status", "payment_type", "out_trade_no", "expires_at",
                )}, "result_type": self.result_type, "pay_url": self.pay_url,
                "qr_code": self.qr_code, "resume_token": "test-secret-resume",
            })
        if path.endswith("/orders/my"):
            assert request.url.params["order_type"] == "balance"
            items = list(self.orders.values()) if self.foreign else [
                order for order in self.orders.values() if order["user_id"] == uid
            ]
            return ok({"items": items, "page": 1, "page_size": 20, "pages": 1, "total": len(items)})
        if path.endswith("/orders/verify"):
            assert request.method == "POST"
            trade = json.loads(request.content)["out_trade_no"]
            order = next(o for o in self.orders.values() if o["out_trade_no"] == trade)
            assert order["user_id"] == uid
            order["status"] = "COMPLETED"
            order["paid_at"] = "2026-11-15T00:01:00Z"
            order["completed_at"] = "2026-11-15T00:02:00Z"
            return ok(order)
        if "/orders/" in path:
            assert request.method == "GET"
            if self.read_started:
                self.read_started.set()
                await self.read_release.wait()
            order = self.orders.get(int(path.rsplit("/", 1)[1]))
            if order is None or (order["user_id"] != uid and not self.foreign):
                return httpx.Response(404)
            return ok(order)
        pytest.fail(f"unexpected {path}")


@asynccontextmanager
async def setup(tmp_path):
    secret = Fernet.generate_key()
    sessions = AigcdoSessionStore(tmp_path / "sessions.db", secret)
    users = []
    for uid in (73, 74):
        users.append(await sessions.create(GatewaySession.model_validate({
            "access_token": f"access-{uid}", "refresh_token": f"refresh-{uid}",
            "expires_in": 86400, "token_type": "Bearer", "user": profile(uid),
        })))
    remote = Gateway()
    async with AigcdoGatewayClient(transport=httpx.MockTransport(remote)) as gateway:
        auth = AigcdoAuthPort(sessions, gateway)
        policy = CreditDisplayPolicy(Decimal("100"), 4, "test-v1")
        store = AigcdoPaymentStore(tmp_path / "payments.db", secret)
        service = AigcdoPayments(auth, store, policy, ORIGIN)
        yield service, remote, users, secret


async def create(service, user, attempt=ATTEMPT):
    return await service.create(
        user.raw_cookie, amount=Decimal("10.25"), payment_type="alipay", idempotency_key=attempt,
    )


async def test_checkout_and_create_show_authoritative_payment_vs_credit_amount(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        checkout = await service.checkout(alice.raw_cookie)
        assert checkout["methods"]["alipay"]["currency"] == "CNY"
        assert "stripe_publishable_key" not in checkout
        result = await create(service, alice)
        assert result["order"]["amount"] == "20.5"
        assert result["order"]["pay_amount"] == "10.25"
        assert result["order"]["currency"] == "CNY"
        assert result["expected_credits"] == "2050.0000"
        assert result["order"]["fulfilled"] is False
        assert result["checkout"]["pay_url"] == remote.pay_url
        assert "test-secret-resume" not in str(result)
        assert "recharge_code" not in str(result) and "user_email" not in str(result)


async def test_restart_replay_reuses_order_and_original_display_policy(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), secret):
        first = await create(service, alice)
        other = AigcdoPayments(
            service.auth, AigcdoPaymentStore(service.store.path, secret),
            CreditDisplayPolicy(Decimal("200"), 4, "test-v2"), ORIGIN,
        )
        replay = await create(other, alice)
        assert replay["order"]["id"] == first["order"]["id"]
        assert replay["expected_credits"] == "2050.0000"
        assert replay["policy"]["version"] == "test-v1"
        assert len(remote.posts) == 1
        content = service.store.path.read_bytes()
        assert remote.pay_url.encode() not in content
        assert b"test-secret-resume" not in content


async def test_concurrent_same_attempt_and_changed_amount_never_duplicate_post(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), secret):
        remote.started, remote.release = asyncio.Event(), asyncio.Event()
        other = AigcdoPayments(service.auth, AigcdoPaymentStore(service.store.path, secret), service.policy, ORIGIN)
        task = asyncio.create_task(create(service, alice))
        await asyncio.wait_for(remote.started.wait(), 3)
        try:
            with pytest.raises(AigcdoGatewayError) as caught:
                await create(other, alice)
            assert caught.value.code == "payment_pending"
            with pytest.raises(AigcdoGatewayError) as conflict:
                await other.create(alice.raw_cookie, amount=Decimal("11"), payment_type="alipay", idempotency_key=ATTEMPT)
            assert conflict.value.code == "idempotency_conflict"
        finally:
            remote.release.set()
        await task
        assert len(remote.posts) == 1


async def test_timeout_never_reposts_but_orders_remain_queryable(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.timeout = True
        with pytest.raises(AigcdoGatewayError) as initial:
            await create(service, alice)
        assert initial.value.code == "payment_pending"
        with pytest.raises(AigcdoGatewayError) as caught:
            await create(service, alice)
        assert caught.value.code == "payment_pending"
        listed = await service.orders(alice.raw_cookie)
        assert len(listed["items"]) == 1 and len(remote.posts) == 1


async def test_order_ownership_and_verify_do_not_use_browser_payment_status(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, bob), _):
        made = await create(service, alice)
        oid = int(made["order"]["id"])
        with pytest.raises(AigcdoGatewayError):
            await service.order(bob.raw_cookie, oid)
        assert (await service.orders(bob.raw_cookie))["total"] == 0
        remote.foreign = True
        with pytest.raises(AigcdoGatewayError):
            await service.order(bob.raw_cookie, oid)
        with pytest.raises(AigcdoGatewayError):
            await service.orders(bob.raw_cookie)
        checked = await service.verify(alice.raw_cookie, oid)
        assert checked["status"] == "COMPLETED" and checked["fulfilled"] is True
        replay = await create(service, alice)
        assert replay["checkout"] is None
        assert len(remote.posts) == 1


async def test_credited_amount_already_includes_nonzero_bonus(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.bonus_amount = "2.05"
        result = await create(service, alice)
        assert result["order"]["amount"] == "22.55"
        assert result["order"]["bonus_amount"] == "2.05"
        assert result["order"]["pay_amount"] == "10.25"
        assert result["expected_credits"] == "2255.0000"


@pytest.mark.parametrize("status", ["PAID", "RECHARGING", "FAILED", "CANCELLED", "REFUNDED"])
async def test_only_completed_is_fulfilled_and_nonpending_cannot_reuse_checkout(tmp_path, status):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        await create(service, alice)
        remote.orders[1]["status"] = status
        result = await create(service, alice)
        assert result["order"]["fulfilled"] is False
        assert result["checkout"] is None


@pytest.mark.parametrize("amount", ["0", "-1", "NaN", "Infinity", "10.251", "1e1000000"])
async def test_invalid_amounts_rejected_before_create(tmp_path, amount):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        with pytest.raises(AigcdoGatewayError):
            await service.create(alice.raw_cookie, amount=Decimal(amount), payment_type="alipay", idempotency_key=ATTEMPT)
        assert remote.posts == []


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://insecure.example/pay", "https://user:secret@pay.example/"])
async def test_unsafe_payment_urls_are_not_returned_or_retried(tmp_path, url):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.pay_url = url
        with pytest.raises(AigcdoGatewayError):
            await create(service, alice)
        with pytest.raises(AigcdoGatewayError):
            await create(service, alice)
        assert len(remote.posts) == 1


async def test_storage_failure_prevents_order_post(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        service.store.path.mkdir()
        with pytest.raises(AigcdoGatewayError) as caught:
            await create(service, alice)
        assert caught.value.code == "payment_storage_unavailable"
        assert remote.posts == []


async def test_logout_during_creation_keeps_receipt_but_returns_no_checkout(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.started, remote.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(create(service, alice))
        await asyncio.wait_for(remote.started.wait(), 3)
        try:
            await service.auth.store.take_for_logout(alice.raw_cookie)
        finally:
            remote.release.set()
        with pytest.raises(AuthError):
            await task
        assert len(remote.posts) == 1


async def test_payment_http_cookie_origin_and_input_boundaries(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        app = FastAPI()
        app.include_router(create_aigcdo_payments_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            cookies={"st_session": alice.raw_cookie},
        ) as browser:
            body = {"amount": "10.25", "payment_type": "alipay"}
            assert (await browser.post("/api/v1/account/payments/orders", json=body)).status_code == 403
            browser.headers["Origin"] = ORIGIN
            assert (await browser.post("/api/v1/account/payments/orders", json=body)).status_code == 400
            browser.headers["Idempotency-Key"] = ATTEMPT
            for extra in ({"user_id": 74}, {"return_url": "https://evil.example"}, {"status": "COMPLETED"}, {"amount": 10.25}):
                assert (await browser.post("/api/v1/account/payments/orders", json={**body, **extra})).status_code == 400
            made = await browser.post("/api/v1/account/payments/orders", json=body)
            assert made.status_code == 200
            assert made.headers["cache-control"] == "no-store"
            assert made.json()["data"]["order"]["fulfilled"] is False
            assert (await browser.get("/api/v1/account/payments/orders?user_id=74")).status_code == 400
            assert (await browser.get("/api/v1/account/payments/orders?page=1&page=2")).status_code == 400
            assert (await browser.post("/api/v1/account/payments/orders/1/verify", json={"status": "PAID"})).status_code == 400
            result = await browser.post("/api/v1/account/payments/orders/1/verify", json={})
            assert result.json()["data"]["fulfilled"] is True
            assert len(remote.posts) == 1


async def test_existing_checkout_remains_queryable_when_new_recharge_disabled(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        result = await create(service, alice)
        remote.disabled = True
        repeated = await create(service, alice)
        assert repeated["order"]["id"] == result["order"]["id"]
        assert len(remote.posts) == 1
        with pytest.raises(AigcdoGatewayError):
            await create(service, alice, "checkout-new-attempt")
        assert len(remote.posts) == 1


async def test_create_response_cannot_change_requested_payment_method(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.created_payment_type = "wxpay"
        with pytest.raises(AigcdoGatewayError) as caught:
            await create(service, alice)
        assert caught.value.code == "invalid_response"


async def test_same_idempotency_key_for_different_users_is_not_shared(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, bob), _):
        a = await create(service, alice)
        b = await create(service, bob)
        assert a["order"]["id"] != b["order"]["id"]
        assert [uid for uid, _ in remote.posts] == [73, 74]


async def test_expired_checkout_is_not_reoffered(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        await create(service, alice)
        remote.orders[1]["expires_at"] = "2020-01-01T00:00:00Z"
        assert (await create(service, alice))["checkout"] is None


@pytest.mark.parametrize("mode", ["order", "orders", "verify"])
async def test_pending_order_read_after_logout_does_not_return_data(tmp_path, mode):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        await create(service, alice)
        if mode == "orders":
            # List is also checked by the service after the user-scoped gateway read.
            original = service.auth.gateway.payment_orders
        else:
            original = service.auth.gateway.payment_order
        entered, release = asyncio.Event(), asyncio.Event()

        async def paused(*args, **kwargs):
            data = await original(*args, **kwargs)
            entered.set()
            await release.wait()
            return data

        method = "payment_orders" if mode == "orders" else "payment_order"
        setattr(service.auth.gateway, method, paused)
        task = asyncio.create_task(
            service.orders(alice.raw_cookie) if mode == "orders"
            else getattr(service, mode)(alice.raw_cookie, 1)
        )
        await asyncio.wait_for(entered.wait(), 3)
        try:
            await service.auth.store.take_for_logout(alice.raw_cookie)
        finally:
            release.set()
        with pytest.raises(AuthError):
            await task


async def test_native_wechat_qr_is_returned_as_data_not_executable_html(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.pay_url = ""
        remote.qr_code = "weixin://wxpay/bizpayurl?pr=test"
        result = await create(service, alice)
        assert result["checkout"]["qr_code"] == remote.qr_code


@pytest.mark.parametrize("result_type", ["oauth_required", "jsapi_ready"])
async def test_unsupported_checkout_flow_is_not_silently_accepted(tmp_path, result_type):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.result_type = result_type
        with pytest.raises(AigcdoGatewayError):
            await create(service, alice)
        with pytest.raises(AigcdoGatewayError) as caught:
            await create(service, alice)
        assert caught.value.code == "payment_pending"
        assert len(remote.posts) == 1


async def test_checkout_preflight_rejection_explicitly_proves_no_order_was_claimed(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        with pytest.raises(AigcdoGatewayError) as caught:
            await service.create(alice.raw_cookie, amount=Decimal("0.50"), payment_type="alipay", idempotency_key=ATTEMPT)
        assert caught.value.code == "payment_not_submitted"
        assert remote.posts == []
        # A definitively rejected operation is retired; the unlocked form starts a new one.
        assert (await create(service, alice, "checkout-corrected-0001"))["order"]["id"] == "1"


async def test_rejected_attempt_cannot_be_submitted_by_an_inflight_retry(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, _), _):
        remote.checkout_started = asyncio.Event()
        release = remote.checkout_release = asyncio.Event()
        earlier = asyncio.create_task(create(service, alice))
        await remote.checkout_started.wait()
        remote.checkout_started = None
        remote.disabled = True
        try:
            with pytest.raises(AigcdoGatewayError) as rejected:
                await create(service, alice)
            assert rejected.value.code == "payment_not_submitted"
        finally:
            release.set()
        with pytest.raises(AigcdoGatewayError) as late:
            await earlier
        assert late.value.code == "payment_not_submitted"
        assert remote.posts == []


async def test_old_page_identity_cannot_submit_with_new_users_cookie(tmp_path):
    async with setup(tmp_path) as (service, remote, (alice, bob), _):
        app = FastAPI()
        app.include_router(create_aigcdo_payments_router(service), prefix="/api/v1")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
            cookies={"st_session": bob.raw_cookie},
            headers={"Origin": ORIGIN, "X-AIGCDO-User-ID": alice.user.id, "Idempotency-Key": ATTEMPT},
        ) as browser:
            for path in ("/checkout", "/orders", "/orders/1"):
                response = await browser.get("/api/v1/account/payments" + path)
                assert response.status_code == 409 and response.json()["code"] == "session_changed"
            response = await browser.post("/api/v1/account/payments/orders", json={
                "amount": "10.25", "payment_type": "alipay",
            })
            assert response.status_code == 409
            assert response.headers["cache-control"] == "no-store"
        assert remote.posts == []
