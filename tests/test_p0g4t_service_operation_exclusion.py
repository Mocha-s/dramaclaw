"""Legacy NewAPI admin operations fail closed before any side effect."""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelvideo.api.routes import model_gateway


@pytest.mark.parametrize("method,path", [
    ("post", "/model-gateway/custom/newapi/init"),
    ("post", "/model-gateway/custom/newapi/provider-channels"),
    ("post", "/model-gateway/custom/newapi/provider-channel/sync"),
    ("post", "/model-gateway/custom/newapi/channels"),
    ("post", "/model-gateway/custom/newapi/channels/batch"),
    ("post", "/model-gateway/custom/newapi/embedding-model"),
    ("post", "/model-gateway/custom/newapi/media-models"),
    ("delete", "/model-gateway/custom/newapi/comfyui"),
])
def test_legacy_newapi_mutations_return_410_before_service_operations(method, path):
    app = FastAPI()
    app.include_router(model_gateway.router)
    with TestClient(app) as client:
        request = getattr(client, method)
        response = request(path, json={"secret": "must-not-leak"}) if method == "post" else request(path)
    assert response.status_code == 410
    assert "must-not-leak" not in response.text
    assert response.json() == {"detail": "NewAPI administration is not portable to third-party gateways; manage channels in the selected gateway."}
