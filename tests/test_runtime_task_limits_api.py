from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client(monkeypatch, tmp_path, *, authorized: bool = True):
    from novelvideo.api.auth import get_api_user
    from novelvideo.api.routes import task_limits
    from novelvideo import runtime_settings

    monkeypatch.setattr(runtime_settings, "runtime_settings_db_path", lambda: tmp_path / "settings.db")

    def authorize():
        if not authorized:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")

    monkeypatch.setattr(task_limits, "_require_ce_task_limits_admin", authorize)
    app = FastAPI()
    app.include_router(task_limits.router, prefix="/api/v1")
    app.dependency_overrides[get_api_user] = lambda: {"role": "owner"}
    return TestClient(app)


def _valid_payload():
    return {
        "lanes": {
            "default": {"globalConcurrency": 8, "globalQueueLimit": 512, "projectActiveLimit": 12, "projectUserActiveLimit": 12},
            "video": {"globalConcurrency": 2, "globalQueueLimit": 128, "projectActiveLimit": 4, "projectUserActiveLimit": 4},
            "world": {"globalConcurrency": 1, "globalQueueLimit": 64, "projectActiveLimit": 2, "projectUserActiveLimit": 2},
            "ffmpeg": {"globalConcurrency": 1, "globalQueueLimit": 64, "projectActiveLimit": 2, "projectUserActiveLimit": 2},
        }
    }


def test_task_limits_api_persists_each_lane_and_reports_defaults(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.get("/api/v1/config/task-limits")

    assert response.status_code == 200
    body = response.json()["data"]
    assert set(body["lanes"]) == {"default", "video", "world", "ffmpeg"}
    assert body["lanes"]["default"]["globalConcurrency"] == 8
    assert body["lanes"]["default"]["projectUserActiveLimit"] == 12

    update = body
    update["lanes"]["default"]["globalConcurrency"] = 6
    update["lanes"]["video"]["projectUserActiveLimit"] = 4
    saved = client.put("/api/v1/config/task-limits", json=update)

    assert saved.status_code == 200
    assert saved.json()["data"]["lanes"]["default"]["globalConcurrency"] == 6
    assert saved.json()["data"]["lanes"]["video"]["projectUserActiveLimit"] == 4
    assert client.get("/api/v1/config/task-limits").json()["data"] == saved.json()["data"]


def test_task_limits_api_rejects_out_of_range_without_overwriting(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    before = client.get("/api/v1/config/task-limits").json()["data"]
    invalid = {**before, "lanes": {**before["lanes"]}}
    invalid["lanes"]["video"] = {**before["lanes"]["video"], "globalConcurrency": 0}

    response = client.put("/api/v1/config/task-limits", json=invalid)

    assert response.status_code in {400, 422}
    assert client.get("/api/v1/config/task-limits").json()["data"] == before


def test_task_limits_api_rejects_unauthorized_reads_and_writes(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, authorized=False)

    assert client.get("/api/v1/config/task-limits").status_code == 403
    assert client.put("/api/v1/config/task-limits", json=_valid_payload()).status_code == 403
