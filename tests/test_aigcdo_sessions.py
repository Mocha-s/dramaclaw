from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3

import httpx
import pytest
from cryptography.fernet import Fernet

import novelvideo.aigcdo_sessions as sessions
from novelvideo.aigcdo_gateway import (
    AigcdoGatewayClient,
    AigcdoGatewayError,
    GatewayLoginChallenge,
    GatewaySession,
)
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo.ports.auth_contract import AuthError, AuthFailureReason


def gateway_session(user_id=73, *, email="creator@example.test", expires_in=86400):
    return GatewaySession.model_validate({
        "access_token": f"access-secret-{user_id}",
        "refresh_token": f"refresh-secret-{user_id}",
        "expires_in": expires_in,
        "token_type": "Bearer",
        "user": {
            "id": user_id, "email": email, "role": "user", "status": "active",
            "balance": "12.12345678", "frozen_balance": "0",
        },
    })


def ok(data):
    return httpx.Response(200, json={"code": 0, "data": data})


def wire_session(session):
    return {
        **session.model_dump(mode="json"),
        "access_token": session.access_token.get_secret_value(),
        "refresh_token": session.refresh_token.get_secret_value(),
    }


@pytest.fixture
def store(tmp_path):
    return AigcdoSessionStore(tmp_path / "auth" / "sessions.db", Fernet.generate_key())


async def test_identity_and_session_survive_reopening_without_plaintext_credentials(tmp_path):
    key = Fernet.generate_key()
    path = tmp_path / "auth" / "sessions.db"
    first = AigcdoSessionStore(path, key)
    login = await first.create(gateway_session())
    reopened = AigcdoSessionStore(path, key)
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: ok(gateway_session().user.model_dump(mode="json")))
    ) as gateway:
        user = await AigcdoAuthPort(reopened, gateway).verify_session(login.raw_cookie)
    assert user["id"] == login.user.id
    assert user["username"] == login.user.username
    assert user["id"] != "local"
    assert login.raw_cookie not in repr(login)
    assert await reopened.get_user_id(login.user.username) == login.user.id
    for file in path.parent.glob("sessions.db*"):
        content = file.read_bytes()
        assert login.raw_cookie.encode() not in content
        assert b"access-secret-73" not in content
        assert b"refresh-secret-73" not in content
    assert path.stat().st_mode & 0o077 == 0


async def test_identity_is_by_gateway_id_not_email(store):
    original = await store.create(gateway_session())
    renamed = await store.create(gateway_session(email="renamed@example.test"))
    other = await store.create(gateway_session(74))
    assert renamed.user.id == original.user.id
    assert renamed.user.username == original.user.username
    assert other.user.id != original.user.id
    assert other.user.username != original.user.username
    assert renamed.raw_cookie != original.raw_cookie


@pytest.mark.parametrize("cookie", [None, "", "forged", "A" * 43])
async def test_invalid_cookies_never_reach_gateway(store, cookie):
    def unexpected(_):
        pytest.fail("invalid cookie must not reach gateway")

    async with AigcdoGatewayClient(transport=httpx.MockTransport(unexpected)) as gateway:
        with pytest.raises(AuthError):
            await AigcdoAuthPort(store, gateway).verify_session(cookie)


async def test_expired_session_cannot_refresh(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session())
    now += 7 * 86400 + 1
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("expired session sent upstream"))
    ) as gateway:
        with pytest.raises(AuthError) as caught:
            await AigcdoAuthPort(store, gateway).verify_session(login.raw_cookie)
    assert caught.value.reason == AuthFailureReason.EXPIRED


async def test_login_register_and_2fa_use_existing_client_and_create_cookie(store):
    calls = []
    session = gateway_session()

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/login"):
            return ok({"requires_2fa": True, "temp_token": "test-challenge"})
        return ok(wire_session(session))

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        challenge = await auth.login("creator@example.test", "test-password")
        assert isinstance(challenge, GatewayLoginChallenge)
        assert not store.path.exists()
        login = await auth.login_2fa("test-challenge", "123456")
        registered = await auth.register("creator@example.test", "test-password", verify_code="123456")
        assert registered.user.id == login.user.id
        assert len(login.raw_cookie) == 43
    assert calls == ["/api/v1/auth/login", "/api/v1/auth/login/2fa", "/api/v1/auth/register"]


async def test_active_user_password_login_creates_session(store):
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: ok(wire_session(gateway_session())))
    ) as gateway:
        result = await AigcdoAuthPort(store, gateway).login("creator@example.test", "test-password")
    assert result.user.role == "user"
    assert await store.get_identity(result.user.id) == result.user


async def test_inactive_user_cannot_create_session(store):
    disabled = gateway_session().model_copy(
        update={"user": gateway_session().user.model_copy(update={"status": "disabled"})}
    )
    with pytest.raises(AuthError) as caught:
        await store.create(disabled)
    assert caught.value.reason == AuthFailureReason.USER_SUSPENDED


async def test_gateway_outage_fails_closed_without_destroying_valid_session(store):
    login = await store.create(gateway_session())
    fail = True

    def handle(request):
        if fail:
            return httpx.Response(503)
        return ok(gateway_session().user.model_dump(mode="json"))

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        with pytest.raises(AigcdoGatewayError):
            await auth.verify_session(login.raw_cookie)
        fail = False
        assert (await auth.verify_session(login.raw_cookie))["id"] == login.user.id


async def test_identity_mismatch_is_rejected_and_cookie_revoked(store):
    login = await store.create(gateway_session())
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: ok(gateway_session(74).user.model_dump(mode="json")))
    ) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)


async def test_live_gateway_role_and_suspension_are_authoritative(store, monkeypatch):
    monkeypatch.setattr(sessions, "VERIFY_TTL", 0)  # whenever the gateway is asked, it wins
    first = await store.create(gateway_session())
    second = await store.create(gateway_session())
    profile = gateway_session().user.model_dump(mode="json")
    profile["role"] = "admin"
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: ok(profile))
    ) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        assert (await auth.verify_session(first.raw_cookie))["role"] == "admin"
        profile["status"] = "disabled"
        with pytest.raises(AuthError) as caught:
            await auth.verify_session(first.raw_cookie)
        assert caught.value.reason == AuthFailureReason.USER_SUSPENDED
        assert await store.get_identity(first.user.id) is None
        with pytest.raises(AuthError):
            await auth.verify_session(second.raw_cookie)


async def test_unauthorized_gateway_session_is_revoked(store):
    login = await store.create(gateway_session())
    count = 0

    def handle(_):
        nonlocal count
        count += 1
        return httpx.Response(401)

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        for _ in range(2):
            with pytest.raises(AuthError):
                await auth.verify_session(login.raw_cookie)
    assert count == 1


async def test_wrong_key_or_swapped_ciphertext_cannot_authenticate(tmp_path):
    path = tmp_path / "auth.db"
    key = Fernet.generate_key()
    store = AigcdoSessionStore(path, key)
    alice = await store.create(gateway_session())
    bob = await store.create(gateway_session(74))
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("corrupt session sent upstream"))
    ) as gateway:
        wrong = AigcdoSessionStore(path, Fernet.generate_key())
        with pytest.raises(AuthError):
            await AigcdoAuthPort(wrong, gateway).verify_session(alice.raw_cookie)
        with sqlite3.connect(path) as db:
            bob_cipher = db.execute(
                "SELECT cipher FROM sessions WHERE cookie_hash = ?",
                (hashlib.sha256(bob.raw_cookie.encode()).hexdigest(),),
            ).fetchone()[0]
            db.execute(
                "UPDATE sessions SET cipher = ? WHERE cookie_hash = ?",
                (bob_cipher, hashlib.sha256(alice.raw_cookie.encode()).hexdigest()),
            )
        with pytest.raises(AuthError):
            await AigcdoAuthPort(store, gateway).verify_session(alice.raw_cookie)


async def test_logout_revokes_local_cookie_even_when_gateway_returns_502(store):
    login = await store.create(gateway_session())
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(502))
    ) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        with pytest.raises(AigcdoGatewayError):
            await auth.revoke_session(login.raw_cookie)
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)
        await auth.revoke_session(login.raw_cookie)


async def test_only_one_refresh_across_store_instances_and_new_tokens_persist(tmp_path, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    key = Fernet.generate_key()
    path = tmp_path / "auth.db"
    store = AigcdoSessionStore(path, key)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    started, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/refresh"):
            started.set()
            await release.wait()
            return ok({
                "access_token": "new-access-secret", "refresh_token": "new-refresh-secret",
                "expires_in": 86400, "token_type": "Bearer",
            })
        assert request.headers["authorization"] == "Bearer new-access-secret"
        return ok(gateway_session().user.model_dump(mode="json"))

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        other = AigcdoAuthPort(AigcdoSessionStore(path, key), gateway)
        task = asyncio.create_task(auth.verify_session(login.raw_cookie))
        await asyncio.wait_for(started.wait(), 3)
        try:
            with pytest.raises(AigcdoGatewayError):
                await other.verify_session(login.raw_cookie)
        finally:
            release.set()
        assert (await task)["id"] == login.user.id
        assert (await other.verify_session(login.raw_cookie))["id"] == login.user.id
    assert calls.count("/api/v1/auth/refresh") == 1


async def test_uncertain_refresh_result_forces_reauthentication(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("uncertain result", request=request)

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        with pytest.raises(AigcdoGatewayError):
            await auth.verify_session(login.raw_cookie)
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)
    assert calls == 1


async def test_logout_during_identity_lookup_cannot_restore_session(store):
    login = await store.create(gateway_session())
    started, release = asyncio.Event(), asyncio.Event()

    async def handle(request):
        if request.url.path.endswith("/me"):
            started.set()
            await release.wait()
            return ok(gateway_session().user.model_dump(mode="json"))
        return ok({"message": "logged out"})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        task = asyncio.create_task(auth.verify_session(login.raw_cookie))
        await asyncio.wait_for(started.wait(), 3)
        try:
            await auth.revoke_session(login.raw_cookie)
        finally:
            release.set()
        with pytest.raises(AuthError):
            await task
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)


async def test_logout_during_refresh_revokes_rotated_gateway_token(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    started, release = asyncio.Event(), asyncio.Event()
    revoked = []

    async def handle(request):
        if request.url.path.endswith("/refresh"):
            started.set()
            await release.wait()
            return ok({
                "access_token": "rotated-access", "refresh_token": "rotated-refresh",
                "expires_in": 86400, "token_type": "Bearer",
            })
        if request.url.path.endswith("/logout"):
            revoked.append(json.loads(request.content)["refresh_token"])
            return ok({"message": "logged out"})
        pytest.fail("logged-out session must not reach identity lookup")

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        task = asyncio.create_task(auth.verify_session(login.raw_cookie))
        await asyncio.wait_for(started.wait(), 3)
        try:
            await auth.revoke_session(login.raw_cookie)
        finally:
            release.set()
        with pytest.raises(AuthError):
            await task
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)
    assert revoked == ["refresh-secret-73", "rotated-refresh"]


async def test_expired_gateway_refresh_maps_to_revoked_auth_session(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(401))
    ) as gateway:
        with pytest.raises(AuthError) as caught:
            await AigcdoAuthPort(store, gateway).verify_session(login.raw_cookie)
    assert caught.value.reason == AuthFailureReason.REVOKED


async def test_abandoned_refresh_claim_requires_login_without_gateway_retry(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    record = await store.load(login.raw_cookie)
    await store.claim_refresh(record)
    now += 61
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: pytest.fail("abandoned refresh replayed"))
    ) as gateway:
        with pytest.raises(AuthError):
            await AigcdoAuthPort(store, gateway).verify_session(login.raw_cookie)


async def test_cancelled_refresh_does_not_leave_replayable_cookie(store, monkeypatch):
    now = 1800000000
    monkeypatch.setattr(sessions.time, "time", lambda: now)
    login = await store.create(gateway_session(expires_in=60))
    now += 61
    started = asyncio.Event()

    async def handle(request):
        started.set()
        await asyncio.Event().wait()

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        task = asyncio.create_task(auth.verify_session(login.raw_cookie))
        await asyncio.wait_for(started.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)


async def test_logout_with_wrong_encryption_key_still_revokes_local_cookie(tmp_path):
    path = tmp_path / "auth.db"
    key = Fernet.generate_key()
    original = AigcdoSessionStore(path, key)
    login = await original.create(gateway_session())
    wrong = AigcdoSessionStore(path, Fernet.generate_key())
    async with AigcdoGatewayClient(
        transport=httpx.MockTransport(lambda _: ok(gateway_session().user.model_dump(mode="json")))
    ) as gateway:
        await AigcdoAuthPort(wrong, gateway).revoke_session(login.raw_cookie)
        with pytest.raises(AuthError):
            await AigcdoAuthPort(original, gateway).verify_session(login.raw_cookie)


async def test_logout_does_not_load_old_tokens_before_deleting_current_row(store, monkeypatch):
    login = await store.create(gateway_session())
    record = await store.load(login.raw_cookie)
    await store.claim_refresh(record)
    from novelvideo.aigcdo_gateway import GatewaySessionTokens

    rotated = GatewaySessionTokens.model_validate({
        "access_token": "rotated-access", "refresh_token": "rotated-refresh",
        "expires_in": 86400, "token_type": "Bearer",
    })
    await store.save_refresh(record, rotated)
    revoked = []

    async def stale_load(_):
        return record

    # A separate read before DELETE can return the old credential after a rotation.
    monkeypatch.setattr(store, "load", stale_load)

    def handle(request):
        revoked.append(json.loads(request.content)["refresh_token"])
        return ok({"message": "logged out"})

    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        await AigcdoAuthPort(store, gateway).revoke_session(login.raw_cookie)
    assert revoked == ["rotated-refresh"]


async def test_recent_gateway_verification_is_reused_but_local_logout_is_immediate(store, monkeypatch):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path.endswith("/auth/me"):
            return ok(gateway_session().user.model_dump(mode="json"))
        return ok({})

    login = await store.create(gateway_session())
    async with AigcdoGatewayClient(transport=httpx.MockTransport(handle)) as gateway:
        auth = AigcdoAuthPort(store, gateway)
        first = await auth.verify_session(login.raw_cookie)
        assert await auth.verify_session(login.raw_cookie) == first
        assert calls == ["/api/v1/auth/me"]
        later = sessions.time.time() + sessions.VERIFY_TTL + 1
        monkeypatch.setattr(sessions.time, "time", lambda: later)
        await auth.verify_session(login.raw_cookie)
        assert calls == ["/api/v1/auth/me"] * 2
        # A fresh cache entry never outlives the local session it was computed for.
        await auth.revoke_session(login.raw_cookie)
        with pytest.raises(AuthError):
            await auth.verify_session(login.raw_cookie)
