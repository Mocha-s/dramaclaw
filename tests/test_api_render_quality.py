from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


class _RenderPlanStore:
    async def get_beats_as_dicts(self, episode_num: int):
        assert episode_num == 1
        return [{"beat_number": 1, "location": "Hall", "narration_segment": ""}]

    def get_sketch_colors(self, _episode_num: int):
        return {}


def _client(monkeypatch, tmp_path):
    from novelvideo.api.routes import generation

    config: dict = {}
    resolved = SimpleNamespace(
        ctx=None,
        username="alice",
        project_name="demo",
        output_dir=tmp_path,
    )

    async def resolve_project(*_args, **_kwargs):
        return resolved

    async def make_store(*_args, **_kwargs):
        return _RenderPlanStore()

    async def character_map(*_args, **_kwargs):
        return {}

    monkeypatch.setattr(generation, "_resolve_generation_project", resolve_project)
    monkeypatch.setattr(generation, "make_sqlite_store", make_store)
    monkeypatch.setattr(generation, "load_project_config", lambda *_args: config)
    monkeypatch.setattr(generation, "_build_character_map", character_map)
    monkeypatch.setattr(generation, "render_ai_detection_error", lambda _beats: None)
    monkeypatch.setattr(
        generation,
        "build_regen_plan",
        lambda **_kwargs: [
            {
                "mode_key": "1x1_9-16",
                "rows": 1,
                "cols": 1,
                "beat_numbers": [1],
                "location": "Hall",
            }
        ],
    )
    monkeypatch.setattr(generation, "compute_input_fingerprint", lambda **_kwargs: "fingerprint")
    monkeypatch.setattr(generation, "hash_plan", lambda _plan: "plan-hash")

    app = FastAPI()
    app.include_router(generation.router, prefix="/api/v1")
    app.dependency_overrides[generation.get_api_user] = lambda: {"username": "alice"}
    return TestClient(app)


@pytest.mark.parametrize("quality", ["auto", "xhigh", "max"])
def test_render_plan_response_preserves_global_image_quality(monkeypatch, tmp_path, quality):
    client = _client(monkeypatch, tmp_path)

    response = client.post(
        "/api/v1/projects/demo/episodes/1/render/plan",
        json={
            "beat_indices": [1],
            "strategy": "location",
            "aspect_mode": "9:16",
            "image_quality": quality,
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["image_quality"] == quality


def test_render_settings_rejects_quality_outside_global_contract(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    response = client.patch(
        "/api/v1/projects/demo/render-settings",
        json={"image_quality": "draft"},
    )

    assert response.status_code == 422


def test_render_plan_request_and_execute_reject_unknown_quality():
    from novelvideo.api.schemas import (
        PlanEntryOut,
        RenderPlanExecuteRequest,
        RenderPlanRequest,
    )

    with pytest.raises(ValidationError):
        RenderPlanRequest(
            beat_indices=[1],
            strategy="location",
            aspect_mode="9:16",
            image_quality="draft",
        )
    with pytest.raises(ValidationError):
        RenderPlanExecuteRequest(
            plan=[PlanEntryOut(mode_key="1x1_9-16", rows=1, cols=1, beat_numbers=[1])],
            plan_hash="hash",
            input_fingerprint="fingerprint",
            strategy="location",
            aspect_mode="9:16",
            beat_indices=[1],
            image_quality="draft",
        )
