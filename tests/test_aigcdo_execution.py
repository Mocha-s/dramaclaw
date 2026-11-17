from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from dataclasses import replace

import httpx
import pytest

from test_aigcdo_app import Gateway, deployment_env as deployment_env
from novelvideo.api.app import create_app
from novelvideo.ports import registry
from novelvideo.ports.auth_contract import AuthError
from novelvideo.ports.authz import AuthzError, AuthzServiceUnavailable
from novelvideo.task_backend.envelope import InvalidTaskEnvelope, TaskAuthorityUnavailable


@pytest.fixture
async def execution(deployment_env, monkeypatch):
    import novelvideo.aigcdo_deployment as module

    remote = Gateway()
    gateway_class = module.AigcdoGatewayClient
    monkeypatch.setattr(module, "AigcdoGatewayClient",
                        lambda: gateway_class(transport=httpx.MockTransport(remote)))
    app = create_app()
    async with app.router.lifespan_context(app):
        deployment = registry.get_port("lifecycle")
        users = [await deployment.auth.login(f"{name}@example.test", "test-password") for name in ("alice", "bob")]
        projects = [await deployment.projects.create_project(
            owner_user_id=user.user.id, owner_username=user.user.username, name="demo",
        ) for user in users]
        yield deployment, remote, users, projects


async def issue(deployment, user, project, root="task-alice"):
    return await deployment.execution.issue_task(
        user.raw_cookie, root_task_id=root, project_id=project.id, task_type="freezone_text_generate",
        payload={"episode": 0, "beat_num": None, "scope": None, "queue_kind": "default", "payload": {"prompt": "hello"}},
    )


def delivery(signed):
    return {
        "project_id": signed.project_id, "requester_user_id": signed.admission.requester_user_id,
        "task_type": signed.task_type, **signed.to_dict()["payload"], "task_envelope_v2": signed.to_dict(),
    }


async def test_task_delivery_persists_only_references_and_resolves_own_key(execution):
    deployment, remote, (alice, bob), (a, b) = execution
    first, second = await asyncio.gather(issue(deployment, alice, a), issue(deployment, bob, b, "task-bob"))
    checked = await deployment.execution.consumer.consume(delivery(first), expected_root_task_id="task-alice")
    credential = await deployment.execution.resolve(checked.admission)
    assert credential.api_key == remote.keys[73]["key"]
    assert credential.api_key != (await deployment.execution.resolve(second.admission)).api_key
    assert credential.base_url == "https://api.aigcdo.top/v1"
    raw = deployment.execution.path.read_bytes()
    for secret in (alice.raw_cookie, bob.raw_cookie, "token-73", remote.keys[73]["key"]):
        assert secret.encode() not in raw
        assert secret not in json.dumps(first.to_dict())
        assert secret not in repr(credential)
    with pytest.raises(AuthError):
        await deployment.auth.verify_session(alice.session_id)
    assert checked.admission.requester_user_id == alice.user.id


async def test_restart_reuses_same_task_binding_and_cannot_rebind_owner_or_payload(execution):
    from novelvideo.aigcdo_execution import AigcdoExecutionAuthority
    deployment, _, (alice, bob), (a, b) = execution
    first = await issue(deployment, alice, a)
    restarted = AigcdoExecutionAuthority(
        deployment.auth, deployment.application_keys, deployment.projects,
        deployment.execution.path, os.environ["AIGCDO_ENCRYPTION_KEY"].encode(),
    )
    checked = await restarted.consumer.consume(delivery(first), expected_root_task_id="task-alice")
    assert (await restarted.resolve(checked.admission)).api_key
    with pytest.raises(AuthzError):
        await issue(deployment, bob, b)
    with pytest.raises(AuthzError):
        await deployment.execution.issue_task(
            alice.raw_cookie, root_task_id="task-alice", project_id=a.id,
            task_type="freezone_text_generate", payload={"prompt": "different"},
        )
    assert (await issue(deployment, alice, a)).admission == first.admission


async def test_rejected_secret_payload_does_not_claim_task_root(execution):
    deployment, _, (alice, _), (a, _) = execution
    with pytest.raises(InvalidTaskEnvelope):
        await deployment.execution.issue_task(
            alice.raw_cookie, root_task_id="task-alice", project_id=a.id, task_type="freezone_text_generate",
            payload={"episode": 0, "beat_num": None, "scope": None, "queue_kind": "default",
                     "payload": {"api_key": "forbidden-secret"}},
        )
    assert (await issue(deployment, alice, a)).admission.requester_user_id == alice.user.id


async def test_task_rechecks_signature_project_status_and_parent_revocation(execution):
    deployment, _, (alice, _), (a, b) = execution
    signed = await issue(deployment, alice, a)
    forged = delivery(signed)
    forged["project_id"] = b.id
    with pytest.raises(InvalidTaskEnvelope):
        await deployment.execution.consumer.consume(forged, expected_root_task_id="task-alice")
    with pytest.raises(AuthzError):
        await issue(deployment, alice, b, "foreign")
    with sqlite3.connect(deployment.projects._db_path()) as db:
        db.execute("UPDATE projects SET status='deleted' WHERE id=?", (a.id,))
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)
    with sqlite3.connect(deployment.projects._db_path()) as db:
        db.execute("UPDATE projects SET status='active' WHERE id=?", (a.id,))
    await deployment.auth.revoke_session(alice.raw_cookie)
    await deployment.auth.login("alice@example.test", "test-password")
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)


async def test_disabled_user_or_key_cannot_run_and_admission_cannot_be_forged(execution):
    deployment, remote, (alice, bob), (a, b) = execution
    signed = await issue(deployment, alice, a)
    other = await issue(deployment, bob, b, "task-bob")
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(replace(signed.admission, credential=other.admission.credential))
    remote.keys[73]["status"] = "disabled"
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)
    remote.disabled.add(74)
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(other.admission)




async def test_agent_creation_requires_trusted_parent_and_enforces_owner_scope_ttl(execution):
    deployment, _, (alice, bob), (a, b) = execution
    agents = deployment.execution
    with pytest.raises(AuthError):
        await agents.create_agent_session(username=alice.user.username, scopes=["projects:read"])
    async with agents.browser_scope(alice.raw_cookie):
        with pytest.raises(AuthError):
            await agents.create_agent_session(username=bob.user.username, scopes=["projects:read"])
        with pytest.raises(AuthError):
            await agents.create_agent_session(username=alice.user.username, scopes=["admin"])
        with pytest.raises(AuthError):
            await agents.create_agent_session(username=alice.user.username, scopes=["projects:read"], ttl_seconds=0)
        with pytest.raises(AuthError):
            await agents.create_agent_session(username=alice.user.username, scopes=["projects:read"],
                                               current_scope_kind="project", current_project_id=b.id)
        token = await agents.create_agent_session(
            username=alice.user.username, scopes=["projects:read", "media:read"],
            current_scope_kind="project", current_project_id=a.id, ttl_seconds=60, worker_id="worker-a",
        )
    verified = await agents.verify_agent_session(token.value)
    assert verified["id"] == alice.user.id and verified["id"] != "local"
    assert verified["current_project_id"] == a.id
    assert verified["scopes"] == ["projects:read", "media:read"]
    assert token.value.encode() not in agents.path.read_bytes()
    with pytest.raises(AuthError):
        await agents.update_agent_session_scope(token.value, scope_kind="home", project_id=None)
    async with agents.browser_scope(bob.raw_cookie):
        with pytest.raises(AuthError):
            await agents.update_agent_session_scope(token.value, scope_kind="project", project_id=b.id)
    await agents.revoke_agent_session(token.value)
    with pytest.raises(AuthError):
        await agents.verify_agent_session(token.value)


async def test_agent_expires_and_logout_invalidates_descendants(execution, monkeypatch):
    import novelvideo.aigcdo_execution as module
    deployment, _, (alice, _), _ = execution
    async with deployment.execution.browser_scope(alice.raw_cookie):
        token = await deployment.execution.create_agent_session(username=alice.user.username, scopes=["projects:read"],
                                                                  ttl_seconds=60)
    clock = module.time.time
    monkeypatch.setattr(module.time, "time", lambda: token.exp + 1)
    with pytest.raises(AuthError):
        await deployment.execution.verify_agent_session(token.value)
    monkeypatch.setattr(module.time, "time", clock)
    await deployment.auth.revoke_session(alice.raw_cookie)
    with pytest.raises(AuthError):
        await deployment.execution.verify_agent_session(token.value)


async def test_agent_restart_scope_update_and_cipher_binding(execution):
    from novelvideo.aigcdo_execution import AigcdoExecutionAuthority
    deployment, _, (alice, _), (a, _) = execution
    authority = deployment.execution
    async with authority.browser_scope(alice.raw_cookie):
        first = await authority.create_agent_session(username=alice.user.username, scopes=["projects:read"])
        second = await authority.create_agent_session(username=alice.user.username, scopes=["media:read"])
        await authority.update_agent_session_scope(first.value, scope_kind="project", project_id=a.id)
    restarted = AigcdoExecutionAuthority(deployment.auth, deployment.application_keys, deployment.projects,
                                         authority.path, os.environ["AIGCDO_ENCRYPTION_KEY"].encode())
    verified = await restarted.verify_agent_session(first.value)
    assert verified["current_project_id"] == a.id
    assert verified["scopes"] == ["projects:read"]
    assert first.value not in repr(first)
    with sqlite3.connect(authority.path) as db:
        cipher = db.execute("SELECT cipher FROM execution_grants WHERE reference=?", (first.session_id,)).fetchone()[0]
        db.execute("UPDATE execution_grants SET cipher=? WHERE reference=?", (cipher, second.session_id))
    with pytest.raises(AuthError):
        await restarted.verify_agent_session(second.value)


async def test_agent_revoke_during_remote_validation_does_not_return_authority(execution, monkeypatch):
    deployment, _, (alice, _), _ = execution
    authority = deployment.execution
    async with authority.browser_scope(alice.raw_cookie):
        token = await authority.create_agent_session(username=alice.user.username, scopes=["projects:read"])
    original = deployment.auth.gateway.me
    async def revoke_before_return(access):
        user = await original(access)
        await authority.revoke_agent_session(token.value)
        return user
    monkeypatch.setattr(deployment.auth.gateway, "me", revoke_before_return)
    with pytest.raises(AuthError):
        await authority.verify_agent_session(token.value)


async def test_task_key_lookup_rechecks_parent_logout_before_return(execution, monkeypatch):
    deployment, _, (alice, _), (a, _) = execution
    signed = await issue(deployment, alice, a)
    original = deployment.auth.gateway.get_key
    async def logout_before_return(*args):
        key = await original(*args)
        await deployment.auth.revoke_session(alice.raw_cookie)
        return key
    monkeypatch.setattr(deployment.auth.gateway, "get_key", logout_before_return)
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)


@pytest.mark.parametrize("operation", ["admit", "resolve", "agent"])
async def test_logout_during_final_project_check_denies_returned_authority(execution, monkeypatch, operation):
    deployment, _, (alice, _), (a, _) = execution
    authority = deployment.execution
    signed = await issue(deployment, alice, a)
    async with authority.browser_scope(alice.raw_cookie):
        token = await authority.create_agent_session(
            username=alice.user.username, scopes=["projects:read"],
            current_scope_kind="project", current_project_id=a.id,
        )
    original = deployment.projects.get_project
    calls = 0
    # admit has two project reads; resolve adds one; agent has one.
    final = {"admit": 2, "resolve": 3, "agent": 1}[operation]
    async def logout_at_last_read(project_id):
        nonlocal calls
        project = await original(project_id)
        calls += 1
        if calls == final:
            await deployment.auth.revoke_session(alice.raw_cookie)
        return project
    monkeypatch.setattr(deployment.projects, "get_project", logout_at_last_read)
    with pytest.raises(AuthError if operation == "agent" else AuthzError):
        if operation == "agent":
            await authority.verify_agent_session(token.value)
        elif operation == "resolve":
            await authority.resolve(signed.admission)
        else:
            await authority.admit_model_task(user_id=alice.user.id, root_task_id="task-alice")


@pytest.mark.parametrize("code", ["storage_unavailable", "provisioning_pending", "invalid_binding"])
async def test_temporary_key_failures_preserve_retryable_authority_contract(execution, monkeypatch, code):
    from novelvideo.aigcdo_application_keys import ApplicationKeyError
    deployment, _, (alice, _), (a, _) = execution
    signed = await issue(deployment, alice, a)
    async def unavailable(*args):
        raise ApplicationKeyError(code)
    monkeypatch.setattr(deployment.application_keys, "ensure_for_session", unavailable)
    with pytest.raises(AuthzServiceUnavailable):
        await issue(deployment, alice, a, "new-task")
    with pytest.raises(TaskAuthorityUnavailable):
        await deployment.execution.consumer.consume(delivery(signed), expected_root_task_id="task-alice")
    with pytest.raises(AuthzServiceUnavailable):
        await deployment.execution.resolve(signed.admission)


async def test_task_uses_parent_refresh_without_reissuing_cookie(execution, monkeypatch):
    from novelvideo.aigcdo_gateway import GatewaySessionTokens
    deployment, _, (alice, _), (a, _) = execution
    signed = await issue(deployment, alice, a)
    parent = await deployment.auth.store.load(alice.raw_cookie)
    # Keep the encrypted session metadata consistent while expiring only the upstream access token.
    expiry = 1
    cipher = deployment.auth.store._encrypt(parent.cookie_hash, parent.user.id, parent.tokens, parent.expires_at, expiry)
    with sqlite3.connect(deployment.auth.store.path) as db:
        db.execute("UPDATE sessions SET access_expires_at=?, cipher=? WHERE cookie_hash=?",
                   (expiry, cipher, parent.cookie_hash))
    refreshes = []
    async def refresh(token):
        refreshes.append(token)
        return GatewaySessionTokens.model_validate({
            "access_token": "rotated-73", "refresh_token": "new-refresh-73",
            "expires_in": 86400, "token_type": "Bearer",
        })
    monkeypatch.setattr(deployment.auth.gateway, "refresh", refresh)
    await deployment.execution.resolve(signed.admission)
    assert refreshes == ["refresh-73"]
    assert (await deployment.auth.store.load(alice.raw_cookie)).tokens.access_token.get_secret_value() == "rotated-73"


async def test_task_expiry_and_storage_failure_do_not_fallback_to_global_key(execution, monkeypatch):
    import novelvideo.aigcdo_execution as module
    deployment, _, (alice, _), (a, _) = execution
    signed = await issue(deployment, alice, a)
    clock = module.time.time
    now = clock()
    monkeypatch.setattr(module.time, "time", lambda: now + 86401)
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)
    monkeypatch.setattr(module.time, "time", clock)
    deployment.execution.path = deployment.execution.path.parent
    with pytest.raises(AuthzError):
        await deployment.execution.resolve(signed.admission)


