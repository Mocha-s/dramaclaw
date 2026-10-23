"""Legacy NewAPI admin discovery is intentionally unavailable."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelvideo.api.routes import model_gateway


@pytest.mark.parametrize("method,path", [
    ("post", "/model-gateway/custom/newapi/provider-channel/models"),
    ("post", "/model-gateway/custom/newapi/provider-channel/sync"),
    ("get", "/model-gateway/custom/newapi/channel-types"),
])
def test_legacy_newapi_discovery_returns_static_410_without_secret_leak(method, path):
    app = FastAPI()
    app.include_router(model_gateway.router)
    with TestClient(app) as client:
        response = getattr(client, method)(path, json={"apiKey": "discovery-secret"}) if method == "post" else getattr(client, method)(path)
    assert response.status_code == 410
    assert "discovery-secret" not in response.text
    assert response.json() == {"detail": "NewAPI administration is not portable to third-party gateways; manage channels in the selected gateway."}
