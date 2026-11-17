from __future__ import annotations

import json
import traceback
from decimal import Decimal

import httpx
import pytest

from novelvideo.aigcdo_gateway import (
    AigcdoGatewayClient,
    AigcdoGatewayError,
    GatewayLoginChallenge,
    GatewaySession,
)


def user_payload() -> dict:
    return {
        "id": 73,
        "email": "creator@example.test",
        "username": "Creator",
        "role": "user",
        "status": "active",
        "balance": "12.12345678",
        "frozen_balance": "0.5",
    }


def tokens_payload() -> dict:
    return {
        "access_token": "test-access-secret",
        "refresh_token": "test-refresh-secret",
        "expires_in": 86400,
        "token_type": "Bearer",
    }


def session_payload() -> dict:
    return {**tokens_payload(), "user": user_payload()}


def success(data: dict) -> httpx.Response:
    return httpx.Response(200, json={"code": 0, "message": "success", "data": data})


async def test_login_then_me_uses_user_bearer_without_admin_key():
    requests = []

    def handle(request):
        requests.append(request)
        assert request.url.host == "api.aigcdo.top"
        assert request.url.scheme == "https"
        assert "x-api-key" not in request.headers
        if request.url.path == "/api/v1/auth/login":
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "email": "creator@example.test",
                "password": "test-password",
            }
            assert "authorization" not in request.headers
            return success(session_payload())
        assert request.url.path == "/api/v1/auth/me"
        assert request.headers["authorization"] == "Bearer test-access-secret"
        return success(user_payload())

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        session = await gateway.login("creator@example.test", "test-password")
        assert isinstance(session, GatewaySession)
        assert session.user.id == 73
        user = await gateway.me(session.access_token.get_secret_value())
        assert user.balance == Decimal("12.12345678")
        assert user.frozen_balance == Decimal("0.5")
        assert "test-access-secret" not in repr(session)
        assert "test-refresh-secret" not in str(session)
    assert len(requests) == 2


async def test_register_passes_verification_code_without_administrative_fields():
    def handle(request):
        assert request.url.path == "/api/v1/auth/register"
        assert json.loads(request.content) == {
            "email": "creator@example.test",
            "password": "test-password",
            "verify_code": "123456",
        }
        return success(session_payload())

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        session = await gateway.register(
            "creator@example.test", "test-password", verify_code="123456"
        )
        assert session.user.id == 73


async def test_2fa_challenge_is_not_a_session():
    def handle(request):
        if request.url.path == "/api/v1/auth/login":
            return success({
                "requires_2fa": True,
                "temp_token": "test-temporary-secret",
                "user_email_masked": "cr***@example.test",
            })
        assert request.url.path == "/api/v1/auth/login/2fa"
        assert json.loads(request.content) == {
            "temp_token": "test-temporary-secret", "totp_code": "123456"
        }
        return success(session_payload())

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        challenge = await gateway.login("creator@example.test", "test-password")
        assert isinstance(challenge, GatewayLoginChallenge)
        assert not isinstance(challenge, GatewaySession)
        assert "test-temporary-secret" not in repr(challenge)
        session = await gateway.login_2fa(challenge.temp_token.get_secret_value(), "123456")
        assert session.user.id == 73


async def test_refresh_accepts_response_without_user_and_logout_uses_rotated_token():
    def handle(request):
        if request.url.path == "/api/v1/auth/refresh":
            assert json.loads(request.content) == {"refresh_token": "old-refresh"}
            return success(tokens_payload())
        assert request.url.path == "/api/v1/auth/logout"
        assert json.loads(request.content) == {"refresh_token": "test-refresh-secret"}
        return success({"message": "logged out"})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        tokens = await gateway.refresh("old-refresh")
        assert tokens.expires_in == 86400
        assert await gateway.logout(tokens.refresh_token.get_secret_value()) is None


@pytest.mark.parametrize(
    ("status", "body", "expected_code", "expected_status"),
    [
        (401, {"code": "INVALID_TOKEN", "message": "test-leaked-secret"}, "authentication_failed", 401),
        (403, {"code": "FORBIDDEN"}, "access_denied", 403),
        (429, {"code": 429}, "rate_limited", 429),
        (502, {"message": "test-leaked-secret"}, "gateway_unavailable", 503),
        (400, {"code": "EMAIL_EXISTS"}, "request_rejected", 400),
        (200, {"code": 1, "message": "test-leaked-secret"}, "request_rejected", 400),
        (200, {"code": False, "data": {}}, "invalid_response", 502),
        (200, {"data": {}}, "invalid_response", 502),
        (200, {"code": 0, "data": []}, "invalid_response", 502),
    ],
)
async def test_errors_are_safe_and_never_retried(status, body, expected_code, expected_status):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json=body)

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.login("creator@example.test", "test-password")
        assert caught.value.code == expected_code
        assert caught.value.status_code == expected_status
        assert "test-leaked-secret" not in "".join(traceback.format_exception(caught.value))
    assert calls == 1


async def test_redirect_is_not_followed_with_credentials():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(307, headers={"Location": "https://other.example/auth/login"})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.login("creator@example.test", "test-password")
        assert caught.value.code == "invalid_response"
    assert len(calls) == 1


async def test_network_failure_hides_sensitive_exception_and_is_not_retried():
    calls = 0
    secret = "test-refresh-secret"

    def handle(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout(secret, request=request)

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.refresh(secret)
        assert caught.value.code == "gateway_unavailable"
        assert "test-refresh-secret" not in "".join(traceback.format_exception(caught.value))
    assert calls == 1


async def test_logout_failure_does_not_claim_session_revoked():
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(502, text="upstream failure"))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.logout("test-refresh-secret")
        assert caught.value.code == "gateway_unavailable"


async def test_invalid_json_is_reported_without_raw_response():
    secret = "test-access-secret"
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=secret))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.me(secret)
        assert caught.value.code == "invalid_response"
        assert "test-access-secret" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    ("field", "value"),
    [("access_token", ""), ("refresh_token", "  "), ("expires_in", 0),
     ("expires_in", True), ("token_type", "Basic"), ("user", {"id": 73})],
)
async def test_incomplete_session_is_rejected_without_leaking_token(field, value):
    payload = {**session_payload(), field: value}
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: success(payload))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.login("creator@example.test", "test-password")
        assert caught.value.code == "invalid_response"
        assert "test-access-secret" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    ("field", "value"),
    [("id", 0), ("id", True), ("id", "73"), ("balance", "NaN"), ("frozen_balance", "Infinity")],
)
async def test_invalid_identity_and_nonfinite_balances_are_rejected(field, value):
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: success({**user_payload(), field: value}))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.me("test-access-secret")
        assert caught.value.code == "invalid_response"


@pytest.mark.parametrize(
    "token",
    ["test-secret-☃", "test-secret\r\nInjected: value", "test secret", " test-secret", "test-secret\t"],
)
async def test_malformed_bearer_is_rejected_before_transport_without_secret_repr(token):
    calls = []

    def handle(request):
        calls.append(request)
        return success(user_payload())

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.me(token)
        assert caught.value.code == "authentication_failed"
        assert token not in repr(caught.value)
        assert token not in str(caught.value)
    assert calls == []


@pytest.mark.parametrize("field", ["access_token", "refresh_token"])
@pytest.mark.parametrize("token", ["test-secret-☃", "test-secret\r\n", "test secret"])
async def test_malformed_returned_session_tokens_are_rejected(field, token):
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: success({**session_payload(), field: token}))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.login("creator@example.test", "test-password")
        assert caught.value.code == "invalid_response"
        assert token not in repr(caught.value)


async def test_malformed_2fa_token_is_not_returned_as_challenge():
    token = "test-secret\r\n"
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(
            lambda _: success({"requires_2fa": True, "temp_token": token})
        )
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.login("creator@example.test", "test-password")
        assert caught.value.code == "invalid_response"
        assert token not in repr(caught.value)


def model_key_payload():
    return {
        "id": 91, "user_id": 73, "group_id": 41, "name": "aigcdo-binding-123",
        "key": "sk-test-model-secret-12345678", "status": "active", "expires_at": None,
    }


async def test_user_key_creation_uses_jwt_and_idempotency_without_admin_credentials():
    def handle(request):
        assert request.headers["Authorization"] == "Bearer test-access-secret"
        assert "x-api-key" not in request.headers
        if request.url.path == "/api/v1/groups/available":
            return httpx.Response(200, json={"code": 0, "data": [
                {"id": 41, "name": "All", "platform": "composite", "status": "active"},
            ]})
        assert request.url.path == "/api/v1/keys"
        assert request.headers["Idempotency-Key"] == "aigcdo-binding-123"
        assert json.loads(request.content) == {
            "name": "aigcdo-binding-123", "group_id": 41, "custom_key": "sk-test-model-secret-12345678",
        }
        return success(model_key_payload())

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        groups = await gateway.available_groups("test-access-secret")
        assert groups[0].id == 41
        key = await gateway.create_key(
            "test-access-secret", name="aigcdo-binding-123", group_id=41,
            custom_key="sk-test-model-secret-12345678", idempotency_key="aigcdo-binding-123",
        )
        assert key.user_id == 73
        assert key.key.get_secret_value() == "sk-test-model-secret-12345678"
        assert "sk-test-model-secret-12345678" not in repr(key)


async def test_user_key_search_reads_all_pages_and_keeps_name_filter():
    pages = []

    def handle(request):
        assert request.url.path == "/api/v1/keys"
        assert request.url.params["search"] == "aigcdo-binding-123"
        page = int(request.url.params["page"])
        pages.append(page)
        item = {**model_key_payload(), "id": 90 + page}
        return success({"items": [item], "total": 2, "page": page, "page_size": 1, "pages": 2})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        keys = await gateway.find_keys("test-access-secret", "aigcdo-binding-123")
        assert [key.id for key in keys] == [91, 92]
    assert pages == [1, 2]


async def test_missing_key_is_distinguished_from_other_gateway_failures():
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, json={"message": "secret"}))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.get_key("test-access-secret", 91)
        assert caught.value.code == "resource_not_found"
        assert caught.value.status_code == 404


@pytest.mark.parametrize("field,value", [
    ("id", True), ("user_id", 0), ("group_id", "41"), ("key", "bad\nsecret"),
    ("expires_at", "2026-01-01T00:00:00"),
])
async def test_user_key_response_validates_identity_secret_and_timezone(field, value):
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: success({**model_key_payload(), field: value}))
    ) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.get_key("test-access-secret", 91)
        assert caught.value.code == "invalid_response"


async def test_incomplete_key_search_cannot_look_like_no_match():
    async with AigcdoGatewayClient(transport=httpx.MockTransport(
        lambda _: success({"items": [], "total": 1001, "page": 1, "page_size": 100, "pages": 11})
    )) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.find_keys("test-access-secret", "aigcdo-binding-123")
        assert caught.value.code == "invalid_response"


def usage_record():
    return {
        "id": 101, "user_id": 73, "request_id": "request-101", "model": "image-model",
        "actual_cost": "0.12345678", "refunded_cost": "0.02345678", "net_actual_cost": "0.10000000",
        "billing_type": 0, "created_at": "2026-11-15T01:00:00Z",
        "input_tokens": 10, "output_tokens": 20,
        "api_key": {"key": "test-secret-do-not-return"},
        "ip_address": "192.0.2.1", "account_id": 999,
    }


async def test_billing_queries_use_user_jwt_and_preserve_decimal_precision():
    from datetime import date

    def handle(request):
        assert request.headers["authorization"] == "Bearer test-access-secret"
        assert "x-api-key" not in request.headers
        if request.url.path == "/api/v1/user/profile":
            return success(user_payload())
        assert request.url.path == "/api/v1/usage"
        assert dict(request.url.params) == {
            "page": "2", "page_size": "1", "model": "image-model",
            "start_date": "2026-11-01", "end_date": "2026-11-15", "timezone": "UTC",
        }
        return success({"items": [usage_record()], "page": 2, "page_size": 1, "pages": 2, "total": 2})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        assert (await gateway.profile("test-access-secret")).balance == Decimal("12.12345678")
        page = await gateway.usage(
            "test-access-secret", page=2, page_size=1, model="image-model",
            start_date=date(2026, 11, 1), end_date=date(2026, 11, 15),
        )
        assert page.items[0].actual_cost == Decimal("0.12345678")
        assert "test-secret-do-not-return" not in page.model_dump_json()
        assert "ip_address" not in page.items[0].model_dump()


@pytest.mark.parametrize("field,value", [
    ("user_id", True), ("actual_cost", "NaN"), ("net_actual_cost", "-1"),
    ("billing_type", 3), ("billing_type", True), ("created_at", "2026-11-15T01:00:00"),
    ("output_tokens", -1),
])
async def test_invalid_usage_record_is_rejected(field, value):
    record = {**usage_record(), field: value}
    async with AigcdoGatewayClient(transport=httpx.MockTransport(
        lambda _: success({"items": [record], "page": 1, "page_size": 20, "pages": 1, "total": 1})
    )) as gateway:
        with pytest.raises(AigcdoGatewayError) as caught:
            await gateway.usage("test-access-secret")
        assert caught.value.code == "invalid_response"


@pytest.mark.parametrize("patch", [
    {"page": 2}, {"total": 0}, {"pages": 0}, {"items": []}, {"page_size": 100},
])
async def test_inconsistent_usage_pagination_is_rejected(patch):
    data = {"items": [usage_record()], "page": 1, "page_size": 20, "pages": 1, "total": 1, **patch}
    async with AigcdoGatewayClient(transport=httpx.MockTransport(lambda _: success(data))) as gateway:
        with pytest.raises(AigcdoGatewayError):
            await gateway.usage("test-access-secret")


async def test_new_user_empty_usage_matches_gateway_minimum_one_page():
    async with AigcdoGatewayClient(transport=httpx.MockTransport(
        lambda _: success({"items": [], "page": 1, "page_size": 20, "pages": 1, "total": 0})
    )) as gateway:
        page = await gateway.usage("test-access-secret")
        assert page.total == 0 and page.items == [] and page.pages == 1
