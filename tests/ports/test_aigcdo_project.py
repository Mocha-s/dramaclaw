from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException

from novelvideo.aigcdo_gateway import GatewaySession
from novelvideo.aigcdo_sessions import AigcdoSessionStore
from novelvideo.ports.aigcdo_project import AigcdoProjectAccess, AigcdoProjectRegistry
from novelvideo.ports.local.project import SQLiteProjectRegistry
from novelvideo.ports.project import Principal
from novelvideo.ports.registry import register_port
from novelvideo.project_context import resolve_project_context


@pytest.fixture
async def users_and_registry(tmp_path, monkeypatch):
    from novelvideo import config

    for key in ("OUTPUT_DIR", "STATE_DIR", "RUNTIME_DIR"):
        monkeypatch.setattr(config, key, str(tmp_path / key.lower()))
    store = AigcdoSessionStore(tmp_path / "auth" / "sessions.db", Fernet.generate_key())
    users = []
    for user_id in (73, 74):
        login = await store.create(GatewaySession.model_validate({
            "access_token": f"test-access-{user_id}",
            "refresh_token": f"test-refresh-{user_id}",
            "expires_in": 86400, "token_type": "Bearer",
            "user": {
                "id": user_id, "email": f"user{user_id}@example.test", "role": "user",
                "status": "active", "balance": 0, "frozen_balance": 0,
            },
        }))
        users.append(login.user)
    registry = AigcdoProjectRegistry(store)
    return users, registry


async def test_distinct_owners_can_create_same_name_and_only_list_their_projects(users_and_registry):
    (alice, bob), registry = users_and_registry
    first = await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")
    second = await registry.create_project(owner_user_id=bob.id, owner_username=bob.username, name="demo")
    assert first.owner_id == alice.id
    assert second.owner_id == bob.id
    assert first.id != second.id
    assert first.output_dir != second.output_dir
    assert Path(first.output_dir).parent.name == alice.username
    assert await registry.get_project_by_owner_name(alice.id, "demo") == first
    assert await registry.get_project_by_owner_name(bob.id, "demo") == second
    assert await registry.list_accessible_projects([("user", alice.id)]) == [first]
    assert await registry.list_accessible_projects([("user", bob.id)]) == [second]
    assert await registry.list_accessible_projects([("team", alice.id)]) == []
    assert await registry.get_project_by_owner_name("local", "demo") is None
    assert await registry.resolve_username_by_user_id(alice.id) == alice.username
    assert await registry.resolve_user_id_by_username(bob.username) == bob.id
    assert await registry.resolve_user_id_by_username("unregistered") is None
    with pytest.raises(ValueError, match="already exists"):
        await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")


async def test_unknown_owner_and_spoofed_directory_identity_are_rejected(users_and_registry):
    (alice, bob), registry = users_and_registry
    for user_id, username in [("local", "local"), ("unknown", "unknown"), (alice.id, bob.username)]:
        with pytest.raises(ValueError):
            await registry.create_project(owner_user_id=user_id, owner_username=username, name="demo")
    assert await registry.list_accessible_projects([("user", alice.id)]) == []


@pytest.mark.parametrize("name", ["../other", "a/b", "a\\b", "_reserved", "", "a" * 65])
async def test_new_project_path_cannot_escape_owner_namespace(users_and_registry, name):
    (alice, _), registry = users_and_registry
    with pytest.raises(ValueError):
        await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name=name)


async def test_new_project_cannot_override_paths_into_another_owner(users_and_registry):
    (alice, bob), registry = users_and_registry
    target = await registry.create_project(owner_user_id=bob.id, owner_username=bob.username, name="demo")
    with pytest.raises(ValueError):
        await registry.create_project(
            owner_user_id=alice.id, owner_username=alice.username, name="demo",
            output_dir=target.output_dir,
        )


async def test_real_project_context_denies_foreign_id_and_local_legacy_projects(users_and_registry):
    (alice, bob), registry = users_and_registry
    owned = await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")
    legacy = await SQLiteProjectRegistry().create_project(
        owner_user_id="local", owner_username="local", name="legacy"
    )
    access = AigcdoProjectAccess(registry)
    register_port("project_registry", registry)
    register_port("project_access", access)
    ctx = await resolve_project_context(user=alice.to_legacy_dict(), project_id=owned.id, required_role="owner")
    assert ctx.owner_id == alice.id
    for principal, project_id in [(bob, owned.id), (alice, legacy.id)]:
        with pytest.raises(HTTPException) as caught:
            await resolve_project_context(user=principal.to_legacy_dict(), project_id=project_id)
        assert caught.value.status_code == 403
    assert await access.resolve_requester_principals("unknown") == []
    assert await access.resolve_requester_principals("local") == []
    assert await access.effective_project_role_by_id("missing", [Principal("user", alice.id)]) is None
    assert await access.effective_project_role_by_id(owned.id, [Principal("user", bob.id)]) is None
    assert await access.count_project_task_eligible_users(
        project_id=owned.id, owner_type="user", owner_id=alice.id,
    ) == 1
    assert await access.count_project_task_eligible_users(
        project_id=owned.id, owner_type="user", owner_id=bob.id,
    ) == 0


async def test_inactive_identity_loses_project_authority(users_and_registry):
    import sqlite3

    (alice, _), registry = users_and_registry
    owned = await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")
    access = AigcdoProjectAccess(registry)
    principals = await access.resolve_requester_principals(alice.id)
    with sqlite3.connect(registry.identities.path) as db:
        db.execute("UPDATE identities SET status='disabled' WHERE id=?", (alice.id,))
    assert await access.resolve_requester_principals(alice.id) == []
    assert await access.effective_project_role(owned, principals) is None


async def test_owner_can_restore_or_purge_soft_deleted_project_but_not_run_tasks(users_and_registry):
    (alice, bob), registry = users_and_registry
    project = await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")
    await registry.update_project_status(project.id, "deleted")
    access = AigcdoProjectAccess(registry)
    register_port("project_registry", registry)
    register_port("project_access", access)
    context = await resolve_project_context(
        user=alice.to_legacy_dict(), project_id=project.id, required_role="owner"
    )
    assert context.effective_role == "owner"
    assert await access.effective_project_role_by_id(project.id, [Principal("user", bob.id)]) is None
    assert await access.count_project_task_eligible_users(
        project_id=project.id, owner_type="user", owner_id=alice.id,
    ) == 0
    await registry.mark_project_purged(project.id)
    assert await access.effective_project_role_by_id(project.id, [Principal("user", alice.id)]) is None


@pytest.mark.parametrize("status", ["deleted", "archived"])
async def test_inactive_project_cannot_reserve_task_even_with_stale_owner_context(
    users_and_registry, monkeypatch, status,
):
    from novelvideo.ports.local import tasks

    (alice, _), registry = users_and_registry
    project = await registry.create_project(owner_user_id=alice.id, owner_username=alice.username, name="demo")
    register_port("project_registry", registry)
    register_port("project_access", AigcdoProjectAccess(registry))
    context = await resolve_project_context(
        user=alice.to_legacy_dict(), project_id=project.id, required_role="editor",
    )
    await registry.update_project_status(project.id, status)
    monkeypatch.setattr(tasks, "get_task_manager", lambda: pytest.fail("inactive project reserved work"))
    backend = tasks.InlineTaskBackend()
    with pytest.raises(HTTPException) as caught:
        await backend.enqueue_project_task(context, task_type="image_gen", product_surface="freezone")
    assert caught.value.status_code == 409
    # Lifecycle authority remains available after task admission is refused.
    assert (await resolve_project_context(
        user=alice.to_legacy_dict(), project_id=project.id, required_role="owner",
    )).effective_role == "owner"
