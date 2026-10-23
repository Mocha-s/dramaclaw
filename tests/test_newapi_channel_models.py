"""Legacy NewAPI discovery routes are intentionally unavailable."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelvideo import newapi_provisioner
from novelvideo.api.routes import model_gateway
from novelvideo.ports import registry


STATIC_410 = {
    "detail": (
        "NewAPI administration is not portable to third-party gateways; "
        "manage channels in the selected gateway."
    )
}

DISCOVERY_ROUTES = (
    ("post", "/model-gateway/custom/newapi/provider-channel/models"),
    ("post", "/model-gateway/custom/newapi/provider-channel/sync"),
    ("get", "/model-gateway/custom/newapi/channel-types"),
)


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, dict[str, int]]:
    calls: dict[str, int] = {}

    def deny(name: str):
        def _deny(*_args: object, **_kwargs: object) -> None:
            calls[name] = calls.get(name, 0) + 1
            raise AssertionError(f"discovery boundary reached: {name}")

        return _deny

    for name in (
        "ensure_admin_access_token",
        "run_newapi_admin_operation",
        "require_newapi_admin_service",
        "fetch_provider_channel_models",
        "list_channel_types",
    ):
        monkeypatch.setattr(newapi_provisioner, name, deny(name))
    monkeypatch.setattr(newapi_provisioner, "open_newapi_db", deny("open_newapi_db"))
    monkeypatch.setattr(newapi_provisioner.httpx, "Client", deny("httpx.Client"))
    monkeypatch.setattr(registry, "get_port", deny("registry.get_port"))

    app = FastAPI()
    app.include_router(model_gateway.router)
    return TestClient(app), calls


@pytest.mark.parametrize("method,path", DISCOVERY_ROUTES)
def test_discovery_routes_are_static_410_without_upstream_or_secret_leak(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    method: str,
    path: str,
) -> None:
    client, calls = _client(monkeypatch)
    payload = {
        "provider": "openai",
        "apiKey": "discovery-secret-canary",
        "newApiBaseUrl": "https://newapi-discovery-canary.invalid",
        "database": {"sqlDsn": "postgresql://discovery-dsn-canary"},
    }

    response = getattr(client, method)(path, json=payload) if method == "post" else getattr(client, method)(path)

    assert response.status_code == 410
    assert response.json() == STATIC_410
    assert calls == {}
    rendered = response.text + caplog.text
    for canary in (
        "discovery-secret-canary",
        "newapi-discovery-canary.invalid",
        "postgresql://discovery-dsn-canary",
    ):
        assert canary not in rendered


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/model-gateway/custom/newapi/provider-channel/models"),
        ("get", "/model-gateway/custom/newapi/provider-channel/sync"),
        ("post", "/model-gateway/custom/newapi/channel-types"),
        ("post", "/model-gateway/custom/newapi/channels/priority"),
    ],
)
def test_invalid_discovery_method_or_path_is_not_a_legacy_route(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str
) -> None:
    client, calls = _client(monkeypatch)
    response = (
        client.post(path, json={"provider": "openai"})
        if method == "post"
        else client.get(path)
    )
    expected_status = 404 if path.endswith("/channels/priority") else 405
    assert response.status_code == expected_status
    assert calls == {}
