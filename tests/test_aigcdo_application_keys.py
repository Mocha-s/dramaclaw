from __future__ import annotations

import asyncio
import json
import sqlite3

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from novelvideo.aigcdo_application_keys import (
    AigcdoApplicationKeys,
    AigcdoApplicationKeyStore,
    ApplicationKeyError,
)
from novelvideo.aigcdo_gateway import AigcdoGatewayClient, AigcdoGatewayError, GatewaySession
from novelvideo.aigcdo_sessions import AigcdoAuthPort, AigcdoSessionStore
from novelvideo.api.routes.aigcdo_auth import create_aigcdo_auth_router
from novelvideo.ports.auth_contract import AuthError


def profile(uid):
    return {
        "id": uid, "email": f"user{uid}@example.test", "role": "user", "status": "active",
        "balance": "10", "frozen_balance": "0",
    }


def ok(data):
    return httpx.Response(200, json={"code": 0, "data": data})


class Gateway:
    """HTTP-only test gateway; real clients/stores/services are exercised."""
    def __init__(self):
        self.keys = {}
        self.creates = []
        self.allowed = True
        self.timeout_after_create = False
        self.missing_after_attempt = False
        self.started = None
        self.release = None
        self.foreign_owner = False

    async def __call__(self, request):
        assert "x-api-key" not in request.headers
        path = request.url.path
        if path.endswith(("/auth/login", "/auth/register")):
            return ok({
                "access_token": "access-73", "refresh_token": "refresh-73",
                "expires_in": 86400, "token_type": "Bearer", "user": profile(73),
            })
        uid = int(request.headers["authorization"].rsplit("-", 1)[1])
        if path.endswith("/me"):
            return ok(profile(uid))
        if path.endswith("/groups/available"):
            return ok([{"id": 41, "name": "All", "platform": "composite", "status": "active"}] if self.allowed else [])
        if path.endswith("/keys") and request.method == "POST":
            data = json.loads(request.content)
            self.creates.append(data)
            assert request.headers["idempotency-key"] == data["name"]
            if self.started is not None:
                self.started.set()
                await self.release.wait()
            if self.missing_after_attempt:
                raise httpx.ReadTimeout("test timeout", request=request)
            key = {
                "id": len(self.keys) + 1, "user_id": 99 if self.foreign_owner else uid,
                "group_id": data["group_id"],
                "key": data["custom_key"], "name": data["name"], "status": "active", "expires_at": None,
            }
            self.keys[key["id"]] = key
            if self.timeout_after_create:
                raise httpx.ReadTimeout("test timeout", request=request)
            return ok(key)
        if path.endswith("/keys"):
            items = [key for key in self.keys.values()
                     if key["user_id"] == uid and request.url.params["search"] in key["name"]]
            return ok({"items": items, "total": len(items), "page": 1, "page_size": 100, "pages": 1})
        if "/keys/" in path:
            key = self.keys.get(int(path.rsplit("/", 1)[1]))
            return ok(key) if key and key["user_id"] == uid else httpx.Response(404)
        pytest.fail(f"unexpected gateway endpoint {path}")


@pytest.fixture
async def setup(tmp_path):
    encryption_key = Fernet.generate_key()
    sessions = AigcdoSessionStore(tmp_path / "sessions.db", encryption_key)
    cookies = []
    for uid in (73, 74):
        cookies.append(await sessions.create(GatewaySession.model_validate({
            "access_token": f"access-{uid}", "refresh_token": f"refresh-{uid}",
            "expires_in": 86400, "token_type": "Bearer", "user": profile(uid),
        })))
    transport = Gateway()
    async with AigcdoGatewayClient(transport=httpx.MockTransport(transport)) as client:
        auth = AigcdoAuthPort(sessions, client)
        path = tmp_path / "keys.db"
        store = AigcdoApplicationKeyStore(path, encryption_key)
        service = AigcdoApplicationKeys(auth, store, group_id=41)
        yield service, transport, cookies, path, encryption_key


async def test_repeated_login_and_reopened_store_reuse_one_encrypted_key(setup):
    service, gateway, (login, _), path, encryption_key = setup
    key = await service.ensure(login.raw_cookie)
    assert key.user_id == 73 and key.group_id == 41
    assert (await service.ensure(login.raw_cookie)).id == key.id
    reopened = AigcdoApplicationKeys(
        service.auth, AigcdoApplicationKeyStore(path, encryption_key), group_id=41,
    )
    assert (await reopened.ensure(login.raw_cookie)).id == key.id
    assert len(gateway.creates) == 1
    assert key.key.get_secret_value() not in repr(key)
    for file in path.parent.glob("keys.db*"):
        assert key.key.get_secret_value().encode() not in file.read_bytes()
    assert path.stat().st_mode & 0o077 == 0


async def test_logout_during_creation_does_not_return_key_to_old_cookie(setup):
    service, gateway, (login, _), _, _ = setup
    gateway.started, gateway.release = asyncio.Event(), asyncio.Event()
    task = asyncio.create_task(service.ensure(login.raw_cookie))
    await asyncio.wait_for(gateway.started.wait(), 3)
    try:
        await service.auth.store.take_for_logout(login.raw_cookie)
    finally:
        gateway.release.set()
    with pytest.raises(AuthError):
        await task
    assert len(gateway.creates) == 1


async def test_ambiguous_recovery_results_block_binding(setup):
    service, gateway, (login, _), _, _ = setup
    gateway.timeout_after_create = True
    with pytest.raises(AigcdoGatewayError):
        await service.ensure(login.raw_cookie)
    key = dict(gateway.keys[1])
    gateway.keys[2] = {**key, "id": 2}
    with pytest.raises(ApplicationKeyError) as caught:
        await service.ensure(login.raw_cookie)
    assert caught.value.code == "application_key_blocked"
    assert len(gateway.creates) == 1


async def test_foreign_owner_in_creation_response_is_rejected(setup):
    service, gateway, (login, _), _, _ = setup
    gateway.foreign_owner = True
    with pytest.raises(ApplicationKeyError) as caught:
        await service.ensure(login.raw_cookie)
    assert caught.value.code == "application_key_blocked"
    assert len(gateway.creates) == 1


async def test_login_automatically_provisions_key_but_browser_sees_only_status(setup):
    service, gateway, _, _, _ = setup
    app = FastAPI()
    app.include_router(create_aigcdo_auth_router(
        service.auth, "https://studio.example.test", application_keys=service,
    ), prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
        headers={"Origin": "https://studio.example.test"},
    ) as browser:
        response = await browser.post("/api/v1/auth/login", json={
            "username": "creator@example.test", "password": "test-password",
        })
        assert response.status_code == 200
        assert response.json()["data"]["application"] == {"status": "ready", "group_id": 41}
        assert gateway.keys[1]["key"] not in response.text
        assert "access-73" not in response.text
        assert browser.cookies.get("st_session")
        retry = await browser.post("/api/v1/auth/application", json={})
        assert retry.status_code == 200
        assert retry.json()["data"] == {"status": "ready", "group_id": 41}
        assert len(gateway.creates) == 1
        denied = await browser.post("/api/v1/auth/application", json={"group_id": 42})
        assert denied.status_code == 400


async def test_pending_key_does_not_turn_successful_login_into_failed_registration(setup):
    service, gateway, _, _, _ = setup
    gateway.timeout_after_create = True
    app = FastAPI()
    app.include_router(create_aigcdo_auth_router(
        service.auth, "https://studio.example.test", application_keys=service,
    ), prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
        headers={"Origin": "https://studio.example.test"},
    ) as browser:
        response = await browser.post("/api/v1/auth/login", json={
            "username": "creator@example.test", "password": "test-password",
        })
        assert response.status_code == 200
        assert response.json()["data"]["application"]["status"] == "pending"
        assert browser.cookies.get("st_session")
        recovered = await browser.post("/api/v1/auth/application", json={})
        assert recovered.json()["data"]["status"] == "ready"
        assert len(gateway.creates) == 1


async def test_users_receive_distinct_keys_owned_by_their_gateway_id(setup):
    service, gateway, (alice, bob), _, _ = setup
    a = await service.ensure(alice.raw_cookie)
    b = await service.ensure(bob.raw_cookie)
    assert a.user_id == 73 and b.user_id == 74
    assert a.key != b.key and a.id != b.id
    assert len(gateway.creates) == 2


async def test_unaccepted_group_and_bad_cookie_cannot_create_key(setup):
    service, gateway, (login, _), _, _ = setup
    with pytest.raises(AuthError):
        await service.ensure("forged")
    gateway.allowed = False
    with pytest.raises(ApplicationKeyError) as caught:
        await service.ensure(login.raw_cookie)
    assert caught.value.code == "group_unavailable"
    assert gateway.creates == []


async def test_timeout_after_accepted_creation_recovers_without_second_post(setup):
    service, gateway, (login, _), _, _ = setup
    gateway.timeout_after_create = True
    with pytest.raises(AigcdoGatewayError):
        await service.ensure(login.raw_cookie)
    key = await service.ensure(login.raw_cookie)
    assert key.user_id == 73
    assert len(gateway.creates) == 1


async def test_uncertain_missing_result_never_blindly_reposts(setup):
    service, gateway, (login, _), _, _ = setup
    gateway.missing_after_attempt = True
    with pytest.raises(AigcdoGatewayError):
        await service.ensure(login.raw_cookie)
    for _ in range(2):
        with pytest.raises(ApplicationKeyError) as caught:
            await service.ensure(login.raw_cookie)
        assert caught.value.code == "provisioning_pending"
    assert len(gateway.creates) == 1


async def test_concurrent_opening_across_store_instances_sends_one_post(setup):
    service, gateway, (login, _), path, encryption_key = setup
    gateway.started, gateway.release = asyncio.Event(), asyncio.Event()
    second = AigcdoApplicationKeys(
        service.auth, AigcdoApplicationKeyStore(path, encryption_key), group_id=41,
    )
    first = asyncio.create_task(service.ensure(login.raw_cookie))
    await asyncio.wait_for(gateway.started.wait(), 3)
    try:
        with pytest.raises(ApplicationKeyError) as caught:
            await second.ensure(login.raw_cookie)
        assert caught.value.code == "provisioning_pending"
    finally:
        gateway.release.set()
    assert (await first).id == (await second.ensure(login.raw_cookie)).id
    assert len(gateway.creates) == 1


@pytest.mark.parametrize("mutation", [
    {"status": "inactive"}, {"group_id": 42}, {"name": "changed"},
    {"key": "sk-aaaaaaaaaaaaaaaa"}, {"expires_at": "2020-01-01T00:00:00Z"},
])
async def test_changed_or_disabled_key_blocks_without_automatic_reissue(setup, mutation):
    service, gateway, (login, _), _, _ = setup
    key = await service.ensure(login.raw_cookie)
    gateway.keys[key.id].update(mutation)
    for _ in range(2):
        with pytest.raises(ApplicationKeyError) as caught:
            await service.ensure(login.raw_cookie)
        assert caught.value.code == "application_key_blocked"
    assert len(gateway.creates) == 1


async def test_deleted_key_is_not_recreated_on_login(setup):
    service, gateway, (login, _), _, _ = setup
    key = await service.ensure(login.raw_cookie)
    del gateway.keys[key.id]
    for _ in range(2):
        with pytest.raises(ApplicationKeyError):
            await service.ensure(login.raw_cookie)
    assert len(gateway.creates) == 1


async def test_swapped_ciphertext_cannot_return_other_users_key(setup):
    service, gateway, (alice, bob), path, _ = setup
    await service.ensure(alice.raw_cookie)
    await service.ensure(bob.raw_cookie)
    with sqlite3.connect(path) as db:
        cipher = db.execute("SELECT cipher FROM application_keys WHERE user_id=?", (bob.user.id,)).fetchone()[0]
        db.execute("UPDATE application_keys SET cipher=? WHERE user_id=?", (cipher, alice.user.id))
    with pytest.raises(ApplicationKeyError):
        await service.ensure(alice.raw_cookie)
    assert len(gateway.creates) == 2


async def test_group_change_requires_explicit_migration(setup):
    service, gateway, (login, _), path, encryption_key = setup
    await service.ensure(login.raw_cookie)
    new = AigcdoApplicationKeys(
        service.auth, AigcdoApplicationKeyStore(path, encryption_key), group_id=42,
    )
    # Group availability does not grant permission to silently rotate an existing binding.
    original = service.auth.gateway.available_groups

    async def groups(token):
        found = await original(token)
        return [*found, found[0].model_copy(update={"id": 42})]

    service.auth.gateway.available_groups = groups
    with pytest.raises(ApplicationKeyError) as caught:
        await new.ensure(login.raw_cookie)
    assert caught.value.code == "binding_migration_required"
    assert len(gateway.creates) == 1


@pytest.mark.parametrize("endpoint", ["login", "register"])
@pytest.mark.parametrize("storage_failure", ["directory", "corrupt_sqlite"])
async def test_application_storage_failure_preserves_successful_authentication(
    setup, endpoint, storage_failure,
):
    service, gateway, _, path, _ = setup
    if storage_failure == "directory":
        path.mkdir()
    else:
        path.write_bytes(b"not a SQLite database")
    app = FastAPI()
    app.include_router(create_aigcdo_auth_router(
        service.auth, "https://studio.example.test", application_keys=service,
    ), prefix="/api/v1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://studio.example.test",
        headers={"Origin": "https://studio.example.test"},
    ) as browser:
        field = "username" if endpoint == "login" else "email"
        response = await browser.post(f"/api/v1/auth/{endpoint}", json={
            field: "creator@example.test", "password": "test-password",
        })
        assert response.status_code == 200
        assert response.json()["data"]["application"] == {
            "status": "pending", "code": "storage_unavailable",
        }
        assert browser.cookies.get("st_session")
        assert response.headers["cache-control"] == "no-store"
        assert str(path) not in response.text
        assert (await browser.get("/api/v1/auth/me")).status_code == 200
        assert gateway.creates == []
        # Storage recovery must not require another registration or login.
        if storage_failure == "directory":
            path.rmdir()
        else:
            path.unlink()
        recovered = await browser.post("/api/v1/auth/application", json={})
        assert recovered.json()["data"]["status"] == "ready"
        assert len(gateway.creates) == 1


async def test_logout_after_claim_before_post_does_not_strand_binding(setup, monkeypatch):
    service, gateway, (login, _), path, _ = setup
    original_claim = service.store.claim_creation

    async def logout_after_claim(binding):
        claimed = await original_claim(binding)
        await service.auth.store.take_for_logout(login.raw_cookie)
        return claimed

    monkeypatch.setattr(service.store, "claim_creation", logout_after_claim)
    with pytest.raises(AuthError):
        await service.ensure(login.raw_cookie)
    assert gateway.creates == []
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT state FROM application_keys WHERE user_id=?", (login.user.id,)
        ).fetchone()[0] == "prepared"

    monkeypatch.setattr(service.store, "claim_creation", original_claim)
    fresh = await service.auth.login("creator@example.test", "test-password")
    result = await service.ensure(fresh.raw_cookie)
    assert result.user_id == 73
    assert len(gateway.creates) == 1


