"""Legacy NewAPI administration is unavailable without touching any boundary."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelvideo import newapi_provisioner
from novelvideo.api.routes import model_gateway
from novelvideo.ports import registry
from novelvideo.service_operation_gate import (
    SERVICE_OPERATION_DENIED,
    ServiceOperationExcluded,
    require_legacy_local_service_operation,
)


STATIC_410 = {
    "detail": (
        "NewAPI administration is not portable to third-party gateways; "
        "manage channels in the selected gateway."
    )
}

# This is the complete legacy decorator inventory.  In particular, there is
# no /custom/newapi/channels/priority route.
LEGACY_ADMIN_ROUTES = (
    ("post", "/model-gateway/custom/newapi/init"),
    ("post", "/model-gateway/custom/newapi/provider-channels"),
    ("delete", "/model-gateway/custom/newapi/comfyui"),
    ("get", "/model-gateway/custom/newapi/channel-types"),
    ("post", "/model-gateway/custom/newapi/provider-channel/models"),
    ("post", "/model-gateway/custom/newapi/provider-channel/sync"),
    ("post", "/model-gateway/custom/newapi/channels"),
    ("post", "/model-gateway/custom/newapi/channels/batch"),
    ("post", "/model-gateway/custom/newapi/embedding-model"),
    ("post", "/model-gateway/custom/newapi/media-models"),
)

LEGACY_MUTATION_ROUTES = tuple(
    route for route in LEGACY_ADMIN_ROUTES if route[0] != "get"
)

PAYLOADS = {
    "/model-gateway/custom/newapi/init": {
        "newApiBaseUrl": "https://newapi-url-canary.invalid",
        "database": {"sqlDsn": "postgresql://request-dsn-canary"},
        "setupUsername": "admin-user-canary",
        "setupPassword": "admin-password-canary",
        "setupConfirmPassword": "admin-password-canary",
    },
    "/model-gateway/custom/newapi/provider-channels": {
        "channels": [{"provider": "ali", "upstreamKey": "provider-key-canary"}]
    },
    "/model-gateway/custom/newapi/provider-channel/models": {
        "provider": "ali"
    },
    "/model-gateway/custom/newapi/provider-channel/sync": {
        "provider": "ali",
        "upstreamKey": "sync-key-canary",
    },
    "/model-gateway/custom/newapi/channels": {
        "provider": "ali",
        "upstreamKey": "channel-key-canary",
        "modelMapping": {"internal-model": "upstream-model-canary"},
    },
    "/model-gateway/custom/newapi/channels/batch": {
        "channels": [
            {
                "provider": "ali",
                "upstreamKey": "batch-channel-key-canary",
                "modelMapping": {"internal-model": "batch-model-canary"},
            }
        ]
    },
    "/model-gateway/custom/newapi/embedding-model": {
        "provider": "ali",
        "upstreamModel": "embedding-model-canary",
        "dimension": 1024,
    },
    "/model-gateway/custom/newapi/media-models": {
        "models": {
            "LingShan-G2": {
                "provider": "ali",
                "upstreamModel": "media-model-canary",
            }
        }
    },
}


def _install_boundary_spies(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    calls: dict[str, int] = {}

    def deny(name: str) -> Callable[..., None]:
        def _deny(*_args: object, **_kwargs: object) -> None:
            calls[name] = calls.get(name, 0) + 1
            raise AssertionError(f"legacy admin boundary reached: {name}")

        return _deny

    for name in (
        "ensure_admin_access_token",
        "run_newapi_admin_operation",
        "require_newapi_admin_service",
        "list_channels",
        "list_channel_types",
        "fetch_provider_channel_models",
        "upsert_channel",
        "update_provider_channel_credentials",
    ):
        monkeypatch.setattr(newapi_provisioner, name, deny(name))
    monkeypatch.setattr(newapi_provisioner, "open_newapi_db", deny("open_newapi_db"))
    monkeypatch.setattr(newapi_provisioner.httpx, "Client", deny("httpx.Client"))
    monkeypatch.setattr(registry, "get_port", deny("registry.get_port"))
    return calls


@pytest.mark.parametrize(
    ("edition", "dsn", "allowed"),
    [
        ("ce", "", True),
        ("ee", "postgresql://organization-dsn-canary", False),
        ("ce", "postgresql://contradictory-dsn-canary", False),
        ("invalid-edition-canary", "", False),
    ],
)
def test_service_operation_gate_preserves_effective_ce_matrix(
    monkeypatch: pytest.MonkeyPatch, edition: str, dsn: str, allowed: bool
) -> None:
    monkeypatch.setenv("ST_EDITION", edition)
    if dsn:
        monkeypatch.setenv("ST_CONTROL_PLANE_DSN", dsn)
    else:
        monkeypatch.delenv("ST_CONTROL_PLANE_DSN", raising=False)

    if allowed:
        assert require_legacy_local_service_operation() is None
    else:
        with pytest.raises(ServiceOperationExcluded) as caught:
            require_legacy_local_service_operation()
        assert str(caught.value) == SERVICE_OPERATION_DENIED
        assert not dsn or dsn not in str(caught.value)


def test_legacy_admin_route_inventory_is_complete() -> None:
    registered = {
        (method.lower(), route.path)
        for route in model_gateway.router.routes
        for method in route.methods or ()
        if route.path.startswith("/model-gateway/custom/newapi/")
    }
    assert registered == set(LEGACY_ADMIN_ROUTES)


@pytest.mark.parametrize("edition,dsn", [("ee", "postgresql://ee-dsn-canary"), ("ce", "postgresql://ce-dsn-canary"), ("invalid-edition-canary", "")])
@pytest.mark.parametrize("method,path", LEGACY_MUTATION_ROUTES)
def test_legacy_mutations_are_static_410_before_any_boundary(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    edition: str,
    dsn: str,
    method: str,
    path: str,
) -> None:
    monkeypatch.setenv("ST_EDITION", edition)
    if dsn:
        monkeypatch.setenv("ST_CONTROL_PLANE_DSN", dsn)
    else:
        monkeypatch.delenv("ST_CONTROL_PLANE_DSN", raising=False)
    monkeypatch.setenv("NEWAPI_PROVISIONER_ENABLED", "true")
    monkeypatch.setenv("NEWAPI_API_KEY", "newapi-api-key-canary")
    calls = _install_boundary_spies(monkeypatch)
    app = FastAPI()
    app.include_router(model_gateway.router)

    request = getattr(TestClient(app), method)
    response = request(path, json=PAYLOADS[path]) if method == "post" else request(path)

    assert response.status_code == 410
    assert response.json() == STATIC_410
    assert calls == {}
    rendered = response.text + caplog.text
    for canary in (
        "ee-dsn-canary",
        "ce-dsn-canary",
        "newapi-api-key-canary",
        json.dumps(PAYLOADS.get(path, {})),
    ):
        assert canary not in rendered


class CanaryOperationPort:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, *_args: object, **_kwargs: object) -> "CanaryOperationPort":
        self.calls.append("get")
        return self

    async def claim(self, *_args: object, **_kwargs: object) -> object:
        self.calls.append("claim")
        raise AssertionError("durable operation was replayed")


@pytest.mark.parametrize("state", ["conflict", "accepted", "completed", "unknown"])
def test_excluded_mutations_never_consult_or_replay_durable_state(
    monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    del state  # The operation state must be irrelevant because no lookup is allowed.
    monkeypatch.setenv("ST_EDITION", "ee")
    monkeypatch.setenv("ST_CONTROL_PLANE_DSN", "postgresql://no-replay-canary")
    calls = _install_boundary_spies(monkeypatch)
    port = CanaryOperationPort()
    monkeypatch.setattr(registry, "get_port", port.get)
    app = FastAPI()
    app.include_router(model_gateway.router)

    response = TestClient(app).post(
        "/model-gateway/custom/newapi/init",
        json={"setupPassword": "no-replay-password-canary"},
    )

    assert response.status_code == 410
    assert response.json() == STATIC_410
    assert calls == {}
    assert port.calls == []
    assert "no-replay-canary" not in response.text
    assert "no-replay-password-canary" not in response.text
