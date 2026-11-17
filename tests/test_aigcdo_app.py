from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from novelvideo.api.app import create_app
from novelvideo.ports import registry

ORIGIN = "https://studio.example.test"


@pytest.fixture
def deployment_env(monkeypatch, tmp_path):
    from novelvideo import config
    from novelvideo.shared import runtime_env

    monkeypatch.setattr(runtime_env, "load_project_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("ST_EDITION", "ce")
    monkeypatch.delenv("ST_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.delenv("DRAMACLAW_LOCAL_AGENT_TRUST", raising=False)
    monkeypatch.setenv("SUPERTALE_AUTH_PROVIDER", "aigcdo")
    values = {
        "AIGCDO_APP_ORIGIN": ORIGIN,
        "AIGCDO_STATE_DIR": str(tmp_path / "auth"),
        "AIGCDO_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "AIGCDO_APPLICATION_GROUP_ID": "41",
        "AIGCDO_CREDITS_PER_USD": "100",
        "AIGCDO_CREDIT_DECIMALS": "4",
        "AIGCDO_CREDIT_POLICY_VERSION": "test-v1",
        "AIGCDO_MODEL_CATALOG": str(tmp_path / "catalog.json"),
    }
    (tmp_path / "catalog.json").write_text(json.dumps({
        "groups": [
            {"id": "text", "name": "text", "protocol": "openai", "capabilities": ["text"],
             "modelMappings": [{"requestPattern": "*", "upstreamModel": "test-writer"}]},
            {"id": "image", "name": "image", "protocol": "openai", "capabilities": ["image"],
             "modelMappings": [{"requestPattern": "test-image", "upstreamModel": "test-image"}]},
        ],
        "capabilityDefaults": {"textGroupId": "text", "textModel": "test-writer"},
    }))
    from novelvideo import aigcdo_model_runtime
    # The checkout's own .env may be a live deployment's.
    for name in (*aigcdo_model_runtime.SHARED_CREDENTIAL_ENV, *aigcdo_model_runtime.EMBEDDING_ENV,
                 "AIGCDO_EMBEDDING_DIMENSIONS"):
        monkeypatch.delenv(name, raising=False)
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("AIGCDO_ADMIN_USERNAME", "operator")
    monkeypatch.setenv("AIGCDO_ADMIN_PASSWORD", "operator-test-password")
    for name in ("OUTPUT_DIR", "STATE_DIR", "RUNTIME_DIR"):
        monkeypatch.setattr(config, name, str(tmp_path / name.lower()))
    registry._PORTS.clear()
    registry._BOOTSTRAPPED = False
    return values


class Gateway:
    def __init__(self):
        self.keys = {}
        self.disabled = set()
        self.requests = []
        self.unavailable = False

    def profile(self, uid):
        return {"id": uid, "email": f"user{uid}@example.test",
                "role": "admin" if uid == 75 else "user",
                "status": "disabled" if uid in self.disabled else "active",
                "balance": "12.50", "frozen_balance": "1"}

    async def __call__(self, request):
        self.requests.append((request.method, request.url.path))
        if self.unavailable:
            raise httpx.ConnectError("gateway unavailable", request=request)
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        uid = int(request.headers.get("authorization", "Bearer token-73").rsplit("-", 1)[1])
        if path.endswith(("/auth/login", "/auth/register")):
            uid = {"alice@example.test": 73, "bob@example.test": 74, "admin@example.test": 75}[body["email"]]
            data = {"access_token": f"token-{uid}", "refresh_token": f"refresh-{uid}",
                    "expires_in": 86400, "token_type": "Bearer", "user": self.profile(uid)}
        elif path.endswith(("/auth/me", "/user/profile")):
            data = self.profile(uid)
        elif path.endswith("/auth/logout"):
            data = {}
        elif path.endswith("/groups/available"):
            data = [{"id": 41, "name": "test-group", "platform": "composite", "status": "active"}]
        elif path.endswith("/keys") and request.method == "POST":
            data = {"id": uid, "user_id": uid, "group_id": body["group_id"],
                    "name": body["name"], "key": body["custom_key"], "status": "active", "expires_at": None}
            self.keys[uid] = data
        elif path.endswith("/keys") and request.method == "GET":
            key = self.keys.get(uid)
            data = {"items": [key] if key else [], "total": 1 if key else 0,
                    "page": 1, "page_size": 100, "pages": 1}
        elif "/keys/" in path:
            data = self.keys[int(path.rsplit("/", 1)[1])]
        elif path.endswith("/payment/orders/my"):
            data = {"items": [], "page": 1, "page_size": 20, "pages": 1, "total": 0}
        else:
            pytest.fail(f"unexpected gateway request {request.method} {path}")
        return httpx.Response(200, json={"code": 0, "data": data})


@pytest.fixture
async def composed_app(deployment_env, monkeypatch):
    import novelvideo.aigcdo_deployment as deployment

    remote = Gateway()
    gateway_class = deployment.AigcdoGatewayClient
    monkeypatch.setattr(deployment, "AigcdoGatewayClient",
                        lambda: gateway_class(transport=httpx.MockTransport(remote)))
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                     headers={"Origin": ORIGIN}) as client:
            yield app, client, remote
    assert registry.get_port("auth").gateway._http.is_closed


@pytest.mark.parametrize("name", [
    "AIGCDO_APP_ORIGIN", "AIGCDO_STATE_DIR", "AIGCDO_ENCRYPTION_KEY",
    "AIGCDO_APPLICATION_GROUP_ID", "AIGCDO_CREDITS_PER_USD",
    "AIGCDO_CREDIT_DECIMALS", "AIGCDO_CREDIT_POLICY_VERSION",
])
def test_missing_config_refuses_boot_without_local_fallback(deployment_env, monkeypatch, name):
    monkeypatch.delenv(name)
    with pytest.raises(RuntimeError, match="AIGCDO"):
        create_app()
    assert registry._BOOTSTRAPPED is False
    assert "auth" not in registry._PORTS


@pytest.mark.parametrize("name,value", [
    ("AIGCDO_APP_ORIGIN", "http://public.example.test"),
    ("AIGCDO_STATE_DIR", "relative"),
    ("AIGCDO_ENCRYPTION_KEY", "not-a-valid-secret-do-not-echo"),
    ("AIGCDO_APPLICATION_GROUP_ID", "0"),
    ("AIGCDO_CREDITS_PER_USD", "NaN"),
    ("AIGCDO_CREDIT_DECIMALS", "9"),
    ("SUPERTALE_AUTH_PROVIDER", "aigcdoo"),
    ("ST_EDITION", "ee"),
    ("ST_CONTROL_PLANE_DSN", "postgresql://do-not-echo"),
    ("DRAMACLAW_LOCAL_AGENT_TRUST", "1"),
])
def test_invalid_config_is_safe_and_refuses_boot(deployment_env, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError) as caught:
        create_app()
    assert "do-not-echo" not in str(caught.value)
    assert not registry._BOOTSTRAPPED


@pytest.mark.parametrize("catalog", [
    "not json", '{"groups": []}',
    '{"groups": [{"id": "g", "name": "g", "protocol": "openai", "capabilities": ["text"],'
    ' "modelMappings": [{"requestPattern": "*", "upstreamModel": "m"}], "apiKey": "sk-shared-do-not-echo"}]}',
    '{"groups": [{"id": "g", "name": "g", "protocol": "openai", "capabilities": ["text"],'
    ' "modelMappings": [{"requestPattern": "*", "upstreamModel": "m"}], "baseUrl": "https://evil.example"}]}',
])
def test_catalog_with_credentials_or_foreign_endpoint_refuses_boot(deployment_env, catalog):
    Path(deployment_env["AIGCDO_MODEL_CATALOG"]).write_text(catalog)
    with pytest.raises(RuntimeError) as caught:
        create_app()
    assert "do-not-echo" not in str(caught.value)


def test_shared_model_key_in_environment_refuses_boot(deployment_env, monkeypatch):
    monkeypatch.setenv("NEWAPI_API_KEY", "sk-shared-do-not-echo")
    with pytest.raises(RuntimeError, match="NEWAPI_API_KEY") as caught:
        create_app()
    assert "do-not-echo" not in str(caught.value)


def test_prebootstrapped_local_identity_cannot_be_reused(deployment_env, monkeypatch):
    from novelvideo.ports.local.auth import FileAuthPort
    registry.register_port("auth", FileAuthPort())
    registry._BOOTSTRAPPED = True
    with pytest.raises(RuntimeError):
        create_app()


async def test_provider_change_between_construction_and_startup_is_rejected(deployment_env, monkeypatch):
    monkeypatch.setenv("SUPERTALE_AUTH_PROVIDER", "legacy")
    app = create_app()
    monkeypatch.setenv("SUPERTALE_AUTH_PROVIDER", "aigcdo")
    with pytest.raises(RuntimeError, match="provider"):
        async with app.router.lifespan_context(app):
            pass
    assert "auth" not in registry._PORTS


async def test_replaced_deployment_before_startup_is_rejected(deployment_env):
    from novelvideo.aigcdo_deployment import AigcdoDeployment

    app = create_app()
    original = registry.get_port("lifecycle")
    replacement = AigcdoDeployment.from_env()
    registry.register_port("lifecycle", replacement)
    registry.register_port("auth", replacement.auth)
    try:
        with pytest.raises(RuntimeError, match="deployment"):
            async with app.router.lifespan_context(app):
                pass
    finally:
        await original.gateway._http.aclose()
        await replacement.gateway._http.aclose()


async def login(client, email="alice@example.test"):
    response = await client.post("/api/v1/auth/login", json={"username": email, "password": "test-password"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["application"]["status"] == "ready"
    return response.json()["data"]


async def test_actual_app_requires_auth_and_reports_aigcdo_even_on_ce(composed_app):
    app, client, remote = composed_app
    response = await client.get("/api/v1/config")
    assert response.status_code == 200
    assert response.json()["data"]["auth_required"] is True
    assert response.json()["data"]["auth_provider"] == "aigcdo"
    assert response.json()["data"]["edition"] == "ce"
    assert not getattr(app.state, "official_media_catalog_updater", None)
    assert not getattr(app.state, "third_party_model_refresh_updater", None)
    assert not getattr(app.state, "director_auto_available", False)
    for path in ("/api/v1/projects", "/api/v1/projects/", "/api/v1/account/billing/balance",
                 "/api/v1/model-gateway/status", "/api/v1/config/task-limits",
                 "/static/projects/foreign/image.png", "/api/v1/not-yet-wired",
                 "/api/v1/config/", "/api/v1/%70rojects"):
        response = await client.get(path)
        assert response.status_code == 401, (path, response.text)
        assert response.headers["cache-control"] == "no-store"
    assert remote.requests == []


async def test_real_login_account_reads_and_private_ports(composed_app):
    _, client, remote = composed_app
    user = await login(client)
    assert (await client.get("/api/v1/auth/me")).json()["data"]["email"] == "user73@example.test"
    assert user["id"] != "local"
    assert "key" not in user and "access_token" not in user
    response = await client.get("/api/v1/account/billing/balance")
    assert response.json()["data"]["available_credits"] == "1250.0000"
    assert (await client.get("/api/v1/account/payments/orders")).json()["data"]["items"] == []
    backend = registry.get_port("task_backend")
    assert backend._producer is registry.get_port("lifecycle").execution
    assert backend._run_scope is not None
    assert registry.get_port("auth_session") is registry.get_port("lifecycle").execution
    assert registry.get_port("model_credentials") is registry.get_port("lifecycle").execution
    assert sum(path.endswith("/keys") and method == "POST" for method, path in remote.requests) == 1
    await client.post("/api/v1/auth/logout")
    assert (await client.get("/api/v1/projects")).status_code == 401


async def test_registration_in_actual_app_provisions_only_one_application_key(composed_app):
    _, client, remote = composed_app
    response = await client.post("/api/v1/auth/register", json={
        "email": "alice@example.test", "password": "test-password",
    })
    assert response.status_code == 200, response.text
    user = response.json()["data"]
    assert user["application"]["status"] == "ready"
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Secure" in response.headers["set-cookie"]
    assert (await client.get("/api/v1/auth/me")).json()["data"]["id"] == user["id"]
    recovery = await client.post("/api/v1/auth/application", json={},
                                 headers={"X-AIGCDO-User-ID": user["id"]})
    assert recovery.json()["data"]["status"] == "ready"
    assert sum(path.endswith("/keys") and method == "POST" for method, path in remote.requests) == 1


async def test_project_routes_and_media_enforce_real_owners(composed_app):
    _, client, _ = composed_app
    alice = await login(client)
    alice_cookie = client.cookies.get("st_session")
    first = await client.post("/api/v1/projects", json={"name": "demo"})
    assert first.status_code == 200, first.text
    project_id = first.json()["data"]["id"]
    record = await registry.get_port("project_registry").get_project(project_id)
    image = Path(record.output_dir) / "proof.txt"
    image.write_text("alice-private-data")
    response = await client.get(f"/static/projects/{project_id}/proof.txt")
    assert response.status_code == 200 and response.text == "alice-private-data"
    assert response.headers["cache-control"] == "no-store"
    client.cookies.clear()
    await login(client, "bob@example.test")
    second = await client.post("/api/v1/projects", json={"name": "demo"})
    assert second.status_code == 200
    assert second.json()["data"]["id"] != project_id
    rows = (await client.get("/api/v1/projects")).json()["data"]
    assert len(rows) == 1 and rows[0]["id"] == second.json()["data"]["id"]
    for path in (f"/api/v1/projects/{project_id}", f"/api/v1/projects/{project_id}/static-auth",
                 f"/static/projects/{project_id}/proof.txt",
                 f"/api/v1/projects/{project_id}/files/proof.txt"):
        response = await client.get(path)
        assert response.status_code == 403, (path, response.text)
        assert "alice-private-data" not in response.text
    assert record.owner_id == alice["id"]
    assert (await registry.get_port("auth").verify_session(alice_cookie))["id"] == alice["id"]


async def test_old_global_management_and_unwired_execution_cannot_run(composed_app):
    _, client, remote = composed_app
    await login(client)
    for path in ("/api/v1/model-gateway/status", "/api/v1/config/task-limits", "/api/v1/diagnostics"):
        assert (await client.get(path)).status_code == 403
    for path in ("/api/v1/chat/cancel", "/api/v1/freezone/agent-config/skills",
                 "/api/v1/projects/anything/freezone/skill-imports"):
        response = await client.post(path, json={})
        assert response.status_code == 503
        assert response.json()["code"] == "aigcdo_integration_pending"
    # A gateway account with the admin role is not the operator administrator.
    await login(client, "admin@example.test")
    assert (await client.get("/api/v1/model-gateway/config")).status_code == 403
    assert all("/v1/chat/completions" not in path for _, path in remote.requests)


async def test_origin_identity_revocation_and_gateway_outage(composed_app, monkeypatch):
    import novelvideo.aigcdo_sessions as sessions

    monkeypatch.setattr(sessions, "VERIFY_TTL", 0)  # the reuse window has its own test
    _, client, remote = composed_app
    await login(client)
    assert (await client.post("/api/v1/projects", headers={"Origin": "https://evil.example"},
                              json={"name": "evil"})).status_code == 403
    assert (await client.get("/api/v1/projects", headers={"Authorization": "Bearer local-forged"})).status_code == 401
    assert (await client.get("/api/v1/projects?token=forged")).status_code == 401
    remote.unavailable = True
    assert (await client.get("/api/v1/projects")).status_code == 503
    remote.unavailable = False
    remote.disabled.add(73)
    assert (await client.get("/api/v1/projects")).status_code == 403


async def test_legacy_local_projects_are_not_claimed_even_by_gateway_admin(composed_app):
    from novelvideo.ports.local.project import SQLiteProjectRegistry

    _, client, _ = composed_app
    legacy = await SQLiteProjectRegistry().create_project(
        owner_user_id="local", owner_username="local", name="legacy",
    )
    await login(client, "admin@example.test")
    assert (await client.get("/api/v1/projects")).json()["data"] == []
    assert (await client.get(f"/api/v1/projects/{legacy.id}")).status_code == 403
    retained = await registry.get_port("project_registry").get_project(legacy.id)
    assert retained.owner_id == "local" and retained.output_dir == legacy.output_dir


async def test_websocket_cannot_bypass_the_pending_agent_boundary(composed_app):
    app, _, _ = composed_app
    messages = []

    async def receive():
        return {"type": "websocket.connect"}

    async def send(message):
        messages.append(message)

    await app({"type": "websocket", "path": "/api/v1/chat/ws", "headers": []}, receive, send)
    assert messages == [{"type": "websocket.close", "code": 1008}]


async def test_sessions_and_application_binding_survive_process_restart(deployment_env, monkeypatch):
    import novelvideo.aigcdo_deployment as deployment

    remote = Gateway()
    gateway_class = deployment.AigcdoGatewayClient
    monkeypatch.setattr(deployment, "AigcdoGatewayClient",
                        lambda: gateway_class(transport=httpx.MockTransport(remote)))
    cookie = None
    user = None
    for _ in range(2):
        registry._PORTS.clear()
        registry._BOOTSTRAPPED = False
        app = create_app()
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN,
                                         headers={"Origin": ORIGIN}) as client:
                if cookie is None:
                    user = await login(client)
                    cookie = client.cookies.get("st_session")
                else:
                    client.cookies.set("st_session", cookie)
                    assert (await client.get("/api/v1/auth/me")).json()["data"]["id"] == user["id"]
                    recovered = await client.post("/api/v1/auth/application", json={})
                    assert recovered.json()["data"]["status"] == "ready"
    assert sum(path.endswith("/keys") and method == "POST" for method, path in remote.requests) == 1


async def test_downstream_storage_errors_are_safe_and_uncached(composed_app, monkeypatch):
    app, client, _ = composed_app
    await login(client)

    async def broken(*args):
        raise OSError("sensitive-storage-path")

    monkeypatch.setattr(registry.get_port("project_registry"), "list_accessible_projects", broken)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url=ORIGIN,
        cookies={"st_session": client.cookies.get("st_session")},
    ) as browser:
        response = await browser.get("/api/v1/projects")
    assert response.status_code == 500
    assert response.headers.get("cache-control") == "no-store"
    assert "sensitive-storage-path" not in response.text
    assert response.json()["ok"] is False


async def test_text_generation_runs_on_each_users_own_key_through_the_task_engine(composed_app, monkeypatch):
    import asyncio

    app, client, remote = composed_app
    seen = []
    original = httpx.AsyncClient

    def model(request):
        assert str(request.url) == "https://api.aigcdo.top/v1/chat/completions"
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={
            "id": "r", "object": "chat.completion", "created": 1, "model": "test-writer",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "generated scene"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        })

    class ModelClient(original):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(model)
            super().__init__(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", ModelClient)
    for email, uid in (("alice@example.test", 73), ("bob@example.test", 74)):
        client.cookies.clear()
        await login(client, email)
        project = (await client.post("/api/v1/projects", json={"name": "text_demo"})).json()["data"]["id"]
        response = await client.post(f"/api/v1/projects/{project}/freezone/text/generate",
                                     json={"prompt": "write a short scene"})
        assert response.status_code == 200, response.text
        job = response.json()["data"]
        for _ in range(200):
            tasks = (await client.get(f"/api/v1/projects/{project}/tasks")).json()["data"]
            state = next(task for task in tasks if task["task_key"] == job["task_key"])
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.05)
        assert state["status"] == "completed", state
        result = await client.get(
            f"/api/v1/projects/{project}/freezone/jobs/freezone_text_generate/{job['job_id']}/result")
        assert result.json()["data"]["generated_text"] == "generated scene"
        assert seen[-1] == f"Bearer {remote.keys[uid]['key']}"
    assert len(set(seen)) == 2


async def test_task_of_logged_out_user_never_reaches_the_model(composed_app, monkeypatch):
    app, client, _ = composed_app
    await login(client)
    project = (await client.post("/api/v1/projects", json={"name": "text_demo"})).json()["data"]["id"]
    execution = app.state.aigcdo_deployment.execution
    cookie = client.cookies.get("st_session")
    signed = await execution.issue_task(cookie, root_task_id="root-1", project_id=project,
                                        task_type="freezone_text_generate",
                                        payload={"episode": 0, "beat_num": None, "scope": "s",
                                                 "queue_kind": "default", "payload": {}})
    await client.post("/api/v1/auth/logout")
    from novelvideo.task_backend.envelope import InvalidTaskEnvelope
    with pytest.raises(InvalidTaskEnvelope):
        await execution.consumer.consume({
            "project_id": project, "requester_user_id": signed.admission.requester_user_id,
            "task_type": "freezone_text_generate", **signed.to_dict()["payload"],
            "task_envelope_v2": signed.to_dict(),
        }, expected_root_task_id="root-1")
    assert (await client.get(f"/api/v1/projects/{project}/tasks")).status_code == 401


async def test_no_project_route_serves_another_users_project(composed_app):
    import re

    app, client, _ = composed_app
    await login(client)
    project = (await client.post("/api/v1/projects", json={"name": "private_demo"})).json()["data"]["id"]
    client.cookies.clear()
    await login(client, "bob@example.test")
    checked = 0
    from novelvideo.api import api_router

    def leaves(routes, prefix=""):
        for route in routes:
            inner = getattr(route, "original_router", None)
            if inner is not None:
                yield from leaves(inner.routes, prefix + inner.prefix)
            else:
                yield prefix + getattr(route, "path", ""), getattr(route, "methods", None) or set()

    for path, methods in [*leaves(api_router.routes), *leaves(app.routes)]:
        if True:
            if "{project" not in path:
                continue
            url = re.sub(r"\{project(_id)?\}", project, path)
            url = re.sub(r"\{[^}:]+(:path)?\}", "1", url)
            if not url.startswith("/"):
                continue
            url = url if url.startswith(("/api/", "/static/")) else "/api/v1" + url
            for method in methods & {"GET", "DELETE"}:
                response = await client.request(method, url)
                checked += 1
                assert response.status_code in {401, 403, 404, 405, 410, 422, 503}, (method, path, response.status_code)
    assert checked > 150
    client.cookies.clear()
    await login(client)
    assert (await client.get(f"/api/v1/projects/{project}")).status_code == 200


async def test_local_projects_migrate_to_one_gateway_user_only_on_apply(composed_app, tmp_path):
    import importlib.util
    from novelvideo import config
    from novelvideo.ports.local.project import SQLiteProjectRegistry

    spec = importlib.util.spec_from_file_location(
        "aigcdo_migrate", Path(__file__).parents[1] / "scripts" / "aigcdo_migrate_local_projects.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _, client, _ = composed_app
    legacy = await SQLiteProjectRegistry().create_project(
        owner_user_id="local", owner_username="local", name="legacy")
    await login(client)
    dbs = (Path(config.STATE_DIR) / "local" / "projects.db", tmp_path / "auth" / "sessions.db")
    assert module.migrate(*dbs, 73, apply=False) == ["legacy"]
    assert (await client.get("/api/v1/projects")).json()["data"] == []
    with pytest.raises(SystemExit):
        module.migrate(*dbs, 999, apply=True)
    assert module.migrate(*dbs, 73, apply=True) == ["legacy"]
    rows = (await client.get("/api/v1/projects")).json()["data"]
    assert [row["id"] for row in rows] == [legacy.id]
    moved = await registry.get_port("project_registry").get_project(legacy.id)
    assert moved.output_dir == legacy.output_dir
    client.cookies.clear()
    await login(client, "bob@example.test")
    assert (await client.get(f"/api/v1/projects/{legacy.id}")).status_code == 403
    # A user who has never logged in here: the identity is pre-created and their first login adopts it.
    later = await SQLiteProjectRegistry().create_project(
        owner_user_id="local", owner_username="local", name="later")
    assert module.migrate(*dbs, 75, apply=False, create_identity=True) == ["later"]
    assert module.migrate(*dbs, 75, apply=True, create_identity=True) == ["later"]
    client.cookies.clear()
    await login(client, "admin@example.test")
    assert [row["id"] for row in (await client.get("/api/v1/projects")).json()["data"]] == [later.id]


def test_media_credentials_follow_the_scoped_user_and_are_empty_outside(deployment_env):
    from novelvideo import aigcdo_model_runtime
    from novelvideo.config import get_effective_newapi_gateway_config
    from novelvideo.model_gateway_settings import save_platform_gateway_key

    create_app()
    assert get_effective_newapi_gateway_config(capability="image", model="test-image").api_key == ""
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        gateway = get_effective_newapi_gateway_config(capability="image", model="test-image")
        assert (gateway.api_key, gateway.base_url) == ("sk-user-a", "https://api.aigcdo.top/v1")
    with pytest.raises(RuntimeError):
        save_platform_gateway_key(api_key="sk-shared")


def test_cold_process_boots_after_cognee_config_import(deployment_env, tmp_path):
    """The CLI imports Cognee config first, and that module exports placeholder keys to env."""
    import os
    import subprocess
    import sys

    env = {
        **{name: os.environ[name] for name in ("PATH", "HOME") if name in os.environ},
        **deployment_env, "SUPERTALE_AUTH_PROVIDER": "aigcdo", "ST_EDITION": "ce",
        "NOVELVIDEO_DATA_ROOT": str(tmp_path),
    }
    code = (
        "import novelvideo.cognee.config\n"
        "from novelvideo.aigcdo_deployment import AigcdoDeployment\n"
        "AigcdoDeployment.from_env()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, result.stderr[-1500:]


def test_operator_embedding_endpoint_is_independent_of_the_user_key(deployment_env, monkeypatch):
    from novelvideo import aigcdo_model_runtime, model_gateway_settings
    from novelvideo.embedding_models import (
        embedding_gateway_credentials, embedding_gateway_model, embedding_model_binding_for_new_project,
    )

    create_app()
    spec = embedding_model_binding_for_new_project()
    # Unconfigured: no endpoint and no fallback to a user's gateway key.
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        assert embedding_gateway_credentials(spec) == ("", "")

    monkeypatch.setenv("AIGCDO_EMBEDDING_BASE_URL", "https://embed.example.test/v1")
    monkeypatch.setenv("AIGCDO_EMBEDDING_API_KEY", "sk-operator-embedding")
    monkeypatch.setenv("AIGCDO_EMBEDDING_MODEL", "BAAI/bge-m3")
    monkeypatch.setenv("AIGCDO_EMBEDDING_DIMENSIONS", "768")
    spec = embedding_model_binding_for_new_project()
    assert spec.dimensions == 768
    for user_key in ("", "sk-user-a"):
        with aigcdo_model_runtime.user_key_scope(user_key):
            assert embedding_gateway_credentials(spec) == (
                "sk-operator-embedding", "https://embed.example.test/v1",
            )
            assert embedding_gateway_model(spec) == "BAAI/bge-m3"
    # Fixed-size models (bge-m3 on SiliconFlow, real 400 on 2026-11-16) reject `dimensions`.
    from novelvideo.cognee.config import _project_embedding_request_kwargs
    from novelvideo.embedding_models import embedding_model_scope

    with embedding_model_scope(spec.internal_model, dimensions=spec.dimensions):
        routed = _project_embedding_request_kwargs({"input": ["x"], "dimensions": 5})
    assert "dimensions" not in routed
    assert (routed["model"], routed["api_base"]) == ("openai/BAAI/bge-m3", "https://embed.example.test/v1")
    # The operator key never rides in the per-user rows that feed every other capability.
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        assert "sk-operator-embedding" not in json.dumps(model_gateway_settings._read_all())


@pytest.mark.parametrize("env", [
    {"AIGCDO_EMBEDDING_BASE_URL": "https://embed.example.test/v1"},
    {"AIGCDO_EMBEDDING_BASE_URL": "http://embed.example.test/v1",
     "AIGCDO_EMBEDDING_API_KEY": "sk-e", "AIGCDO_EMBEDDING_MODEL": "m"},
    {"AIGCDO_EMBEDDING_BASE_URL": "https://embed.example.test/v1",
     "AIGCDO_EMBEDDING_API_KEY": "sk-e", "AIGCDO_EMBEDDING_MODEL": "m", "AIGCDO_EMBEDDING_DIMENSIONS": "0"},
])
def test_partial_or_invalid_embedding_config_refuses_boot(deployment_env, monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="Invalid AIGCDO deployment configuration"):
        create_app()


def test_gateway_insufficient_balance_is_the_insufficient_credits_task_error(deployment_env, monkeypatch):
    from novelvideo.shared.billing_errors import is_insufficient_credits_error

    # Verbatim from the real gateway (2026-11-16) through the text adapter.
    error = RuntimeError(
        "status_code: 403, model_name: gpt-6.1-sol, body: "
        "{'message': 'Insufficient account balance', 'type': 'insufficient_balance'}"
    )
    assert is_insufficient_credits_error(error)
    monkeypatch.setenv("SUPERTALE_AUTH_PROVIDER", "legacy")
    assert not is_insufficient_credits_error(error)


def test_model_plaza_background_refresh_keeps_the_callers_key(deployment_env, monkeypatch):
    import threading

    from novelvideo import aigcdo_model_runtime, model_plaza

    create_app()
    seen = []
    done = threading.Event()

    def fetch():
        seen.append(model_plaza._plaza_endpoint())
        done.set()
        return {"groups": []}

    monkeypatch.setattr(model_plaza, "_fetch_payload", fetch)
    monkeypatch.setattr(model_plaza, "_CACHE", {"expires_at": 0.0, "payload": {"groups": []}})
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        model_plaza._load_payload()
    assert done.wait(5)
    assert seen == [("https://api.aigcdo.top", "sk-user-a")]


async def test_chat_websocket_needs_a_ready_agent_the_app_origin_and_a_live_session(composed_app):
    from novelvideo import aigcdo_model_runtime
    from novelvideo.api.aigcdo_composition import AigcdoBoundary

    app, client, remote = composed_app
    await login(client)
    deployment = app.state.aigcdo_deployment
    cookie = client.cookies.get("st_session")
    served = []

    async def inner(scope, receive, send):
        served.append(aigcdo_model_runtime.scoped_user_key())

    async def connect(*, origin=ORIGIN, session=cookie, path="/api/v1/chat/ws", extra=()):
        messages = []

        async def send(message):
            messages.append(message)

        headers = [(b"origin", origin.encode()), (b"cookie", f"st_session={session}".encode()), *extra]
        await AigcdoBoundary(inner, deployment)(
            {"type": "websocket", "path": path, "headers": headers, "query_string": b""}, None, send,
        )
        return messages

    closed = [{"type": "websocket.close", "code": 1008}]
    assert await connect() == closed  # no isolated worker runtime on this host
    deployment.agent_ready = True
    assert await connect(origin="https://evil.example") == closed
    assert await connect(session="A" * 43) == closed
    assert await connect(path="/api/v1/other/ws") == closed
    assert await connect(extra=[(b"authorization", b"Bearer anything")]) == closed
    assert served == []
    assert await connect() == []
    assert served == [remote.keys[73]["key"]]
    await client.post("/api/v1/auth/logout")
    assert await connect() == closed


async def test_agent_worker_token_acts_only_from_this_host_for_its_own_session(composed_app, monkeypatch):
    import asyncio

    app, client, remote = composed_app
    seen = []
    original = httpx.AsyncClient

    def model(request):
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json={
            "id": "r", "object": "chat.completion", "created": 1, "model": "test-writer",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "by the agent"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        })

    class ModelClient(original):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(model)
            super().__init__(**kwargs)

    user = await login(client)
    mine = (await client.post("/api/v1/projects", json={"name": "agent_demo"})).json()["data"]["id"]
    other = (await client.post("/api/v1/projects", json={"name": "agent_other"})).json()["data"]["id"]
    deployment = app.state.aigcdo_deployment
    async with deployment.execution.browser_scope(client.cookies.get("st_session")):
        token = await deployment.execution.create_agent_session(
            username=user["username"], scopes=["projects:read", "projects:write", "tasks:submit"],
            current_scope_kind="project", current_project_id=mine,
        )
    bearer = {"Authorization": f"Bearer {token.value}"}
    # The worker has no cookie and sends no Origin; it reaches the API over loopback.
    async with original(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as worker:
        assert (await worker.get(f"/api/v1/projects/{mine}/tasks", headers=bearer)).status_code == 401
        deployment.agent_ready = True
        assert (await worker.get(f"/api/v1/projects/{mine}/tasks", headers=bearer)).status_code == 200
        assert (await worker.get(f"/api/v1/projects/{other}/tasks", headers=bearer)).status_code == 403
        assert (await worker.get("/api/v1/model-gateway/status", headers=bearer)).status_code == 403
        forwarded = {**bearer, "X-Forwarded-For": "203.0.113.9"}
        assert (await worker.get(f"/api/v1/projects/{mine}/tasks", headers=forwarded)).status_code == 401

        monkeypatch.setattr(httpx, "AsyncClient", ModelClient)
        response = await worker.post(
            f"/api/v1/projects/{mine}/freezone/text/generate", headers=bearer, json={"prompt": "write"},
        )
        assert response.status_code == 200, response.text
        job = response.json()["data"]
        for _ in range(200):
            tasks = (await worker.get(f"/api/v1/projects/{mine}/tasks", headers=bearer)).json()["data"]
            state = next(task for task in tasks if task["task_key"] == job["task_key"])
            if state["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(0.05)
        assert state["status"] == "completed", state
        # Work the agent submits is paid by the user it acts for.
        assert seen == [f"Bearer {remote.keys[73]['key']}"]

        # A re-login replaces the session: the old worker token is stale, then dead.
        async with deployment.execution.browser_scope(client.cookies.get("st_session")):
            assert not await deployment.execution.agent_session_stale(token.value)
        await client.post("/api/v1/auth/logout")
        assert (await worker.get(f"/api/v1/projects/{mine}/tasks", headers=bearer)).status_code == 401
        await login(client)
        async with deployment.execution.browser_scope(client.cookies.get("st_session")):
            assert await deployment.execution.agent_session_stale(token.value)


def test_agent_worker_holds_no_key_and_each_turn_carries_the_scoped_users(deployment_env, monkeypatch, tmp_path):
    import time

    from novelvideo import aigcdo_model_runtime
    from novelvideo.chat import hermes_pool, service
    from novelvideo.ports.auth_contract import AgentSessionToken

    catalog = json.loads((tmp_path / "catalog.json").read_text())
    (tmp_path / "catalog.json").write_text(json.dumps({**catalog, "agentModel": "test-writer"}))
    create_app()
    # Only Hermes workers run inside the per-user sandbox, whatever the image default says.
    monkeypatch.setenv("DRAMACLAW_CHAT_BACKEND", "codex")
    monkeypatch.setattr(service, "is_hermes_backend_available", lambda: True)
    assert service._chat_backend() == "hermes"

    assert hermes_pool._resolve_turn_gateway_api_key(None) is None  # no user in scope, no key
    token = AgentSessionToken("agent-token", "ref", "alice", (), int(time.time()) + 60, "w", "hermes")
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        assert hermes_pool._resolve_turn_gateway_api_key(None) == "sk-user-a"
        env = hermes_pool.HermesPool()._build_env(tmp_path, "alice", token, project_id=None)
    assert "sk-user-a" not in json.dumps(env)
    assert env["NEWAPI_BASE_URL"].startswith("https://api.aigcdo.top")
    assert env["DRAMACLAW_GATEWAY_CREDENTIAL_MODE"] == "per_turn_required"


async def test_request_paths_have_no_organization_egress_identity(composed_app):
    """Chat turns ask for one; the real container refused every turn on 2026-11-17."""
    from novelvideo.api.egress_binding import build_request_egress_context

    _, client, _ = composed_app
    user = await login(client)
    assert await build_request_egress_context(
        requester_user_id=user["id"], project_id="p", task_type="chat",
    ) is None


def test_administrator_settings_reach_users_with_their_own_key(deployment_env):
    from novelvideo import aigcdo_model_runtime, model_gateway_settings as settings
    from novelvideo.config import get_effective_newapi_gateway_config
    from novelvideo.embedding_models import embedding_gateway_credentials, embedding_model_binding_for_new_project

    create_app()
    mapping = [{"requestPattern": "*", "upstreamModel": "m"}]
    with aigcdo_model_runtime.admin_scope():
        settings.save_third_party_gateway_groups([
            {"id": "gw", "name": "gw", "protocol": "openai", "baseUrl": "https://api.aigcdo.top",
             "apiKey": "sk-admin-listing", "capabilities": ["image"],
             "modelMappings": [{"requestPattern": "admin-image", "upstreamModel": "admin-image"}]},
            {"id": "foreign", "name": "foreign", "protocol": "openai", "baseUrl": "https://other.example/v1",
             "apiKey": "sk-admin-foreign", "capabilities": ["video"],
             "modelMappings": [{"requestPattern": "foreign-video", "upstreamModel": "foreign-video"}]},
            {"id": "embed", "name": "embed", "protocol": "openai", "baseUrl": "https://embed.example/v1",
             "apiKey": "sk-admin-embed", "capabilities": ["embedding"],
             "modelMappings": [{"requestPattern": "bge", "upstreamModel": "bge"}]},
        ], activate=True)
        settings.save_capability_defaults(embedding_group_id="embed", embedding_model="bge")
        # The administrator works with the stored settings as they are.
        assert [g["apiKey"] for g in settings.get_third_party_gateway_groups()][0] == "sk-admin-listing"
    del mapping
    with aigcdo_model_runtime.user_key_scope("sk-user-a"):
        image = get_effective_newapi_gateway_config(capability="image", model="admin-image")
        assert (image.api_key, image.base_url) == ("sk-user-a", "https://api.aigcdo.top/v1")
        # Media on someone else's endpoint would run on the operator's key for every user.
        assert get_effective_newapi_gateway_config(capability="video", model="foreign-video").api_key == ""
        rows = json.dumps(settings._read_all())
        assert "sk-admin-listing" not in rows and "sk-admin-foreign" not in rows
        assert embedding_gateway_credentials(embedding_model_binding_for_new_project()) == (
            "sk-admin-embed", "https://embed.example/v1")
        with pytest.raises(RuntimeError):
            settings.save_capability_defaults(embedding_group_id="embed", embedding_model="bge")


async def test_operator_administrator_configures_but_never_generates(composed_app):
    _, client, _ = composed_app
    admin = {"username": "operator", "password": "operator-test-password"}
    assert (await client.get("/api/v1/admin/session")).status_code == 401
    assert (await client.post("/api/v1/auth/admin/login", json={**admin, "password": "wrong-password-1"})).status_code == 401
    assert (await client.post("/api/v1/auth/admin/login", json=admin, headers={"Origin": "https://evil.example"})).status_code == 403
    assert (await client.post("/api/v1/auth/admin/login", json=admin)).status_code == 200
    assert (await client.get("/api/v1/admin/session")).json()["data"] == {"username": "operator"}
    # The single-user settings routes, unchanged, are the administrator's.
    assert (await client.get("/api/v1/model-gateway/config")).status_code == 200
    assert (await client.get("/api/v1/config/task-limits")).status_code == 200
    # No gateway account behind it: nothing outside the admin area.
    assert (await client.get("/api/v1/projects")).status_code == 401
    assert (await client.get("/api/v1/account/billing/balance")).status_code == 401

    assert (await client.post("/api/v1/admin/credits", json={"credits_per_usd": "0", "decimals": 2})).status_code == 400
    assert (await client.post("/api/v1/admin/credits", json={"credits_per_usd": "1000", "decimals": 0})).status_code == 200
    item = {"id": "a1", "title": "维护通知", "body": "今晚维护", "pinned": True, "published_at": "2026-11-18T10:00:00+08:00"}
    assert (await client.post("/api/v1/admin/announcements", json={"items": [item, item]})).status_code == 400
    assert (await client.post("/api/v1/admin/announcements", json={"items": [item]})).status_code == 200
    assert (await client.post("/api/v1/auth/admin/logout")).status_code == 200
    client.cookies.clear()

    public = (await client.get("/api/v1/announcements")).json()["announcements"]
    assert public[0]["i18n"]["zh"]["title"] == "维护通知" and public[0]["pinned"] is True
    await login(client)
    assert (await client.get("/api/v1/account/billing/balance")).json()["data"]["available_credits"] == "12500"
    for method, path in (("GET", "/api/v1/admin/credits"), ("POST", "/api/v1/admin/announcements"),
                         ("GET", "/api/v1/model-gateway/config")):
        assert (await client.request(method, path, json={})).status_code == 403


@pytest.mark.parametrize("env", [
    {"AIGCDO_ADMIN_PASSWORD": ""}, {"AIGCDO_ADMIN_USERNAME": ""}, {"AIGCDO_ADMIN_PASSWORD": "short"},
])
def test_half_configured_or_weak_administrator_refuses_boot(deployment_env, monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeError, match="Invalid AIGCDO deployment configuration"):
        create_app()
