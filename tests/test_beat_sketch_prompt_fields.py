from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novelvideo.models import NovelVisualBeat
from novelvideo.sqlite_store import SQLiteStore


@pytest.mark.asyncio
async def test_store_persists_sketch_prompt_fields(tmp_path):
    store = SQLiteStore("demo", output_dir=str(tmp_path / "out"), state_dir=str(tmp_path / "state"))
    await store.initialize()
    await store.add_visual_beats([NovelVisualBeat(beat_number=1, episode_number=1, visual_description="黑场")])

    beats = await store.get_beats_as_dicts(1)
    assert beats[0]["sketch_prompt"] == ""
    assert beats[0]["sketch_prompt_mode"] == "append"

    ok = await store.update_beat_asset(1, beat_number=1, sketch_prompt="寻禾手中的木牌特写", sketch_prompt_mode="override")
    assert ok is True
    beats = await store.get_beats_as_dicts(1)
    assert beats[0]["sketch_prompt"] == "寻禾手中的木牌特写"
    assert beats[0]["sketch_prompt_mode"] == "override"
    await store.close()


class _ScriptStore:
    def __init__(self):
        self.updates: list[dict] = []

    async def get_script_as_dict(self, episode_num: int):
        return {"beats": [{"beat_number": 1, "visual_description": "黑场", "sketch_prompt": "", "sketch_prompt_mode": "append"}]}

    async def update_beat_asset(self, episode_number: int, beat_number: int, **fields):
        self.updates.append({"episode": episode_number, "beat": beat_number, **fields})
        return True


def _client(monkeypatch, tmp_path):
    from novelvideo.api.routes import scripts
    from novelvideo.api.deps import ProjectResolution

    store = _ScriptStore()

    async def fake_resolve_project_scope(project, user, *, required_role="viewer"):
        return ProjectResolution(
            ctx=SimpleNamespace(project_id="proj", state_dir=tmp_path / "state", runtime_dir=tmp_path / "runtime"),
            username="alice",
            project_name="demo",
            project_dir=tmp_path,
            output_dir=str(tmp_path),
            state_dir=str(tmp_path / "state"),
            runtime_dir=str(tmp_path / "runtime"),
        )

    async def fake_make_sqlite_store_for_context(ctx):
        return store

    monkeypatch.setattr(scripts, "resolve_project_scope", fake_resolve_project_scope)
    monkeypatch.setattr(scripts, "make_sqlite_store_for_context", fake_make_sqlite_store_for_context)

    app = FastAPI()
    app.include_router(scripts.router, prefix="/api/v1")
    app.dependency_overrides[scripts.get_api_user] = lambda: {"username": "alice"}
    return TestClient(app), store


def test_update_beat_accepts_sketch_prompt_fields(monkeypatch, tmp_path):
    client, store = _client(monkeypatch, tmp_path)

    res = client.patch(
        "/api/v1/projects/demo/episodes/1/beats/1",
        json={"sketch_prompt": "巴掌大小的木牌", "sketch_prompt_mode": "override"},
    )

    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert store.updates[-1]["sketch_prompt"] == "巴掌大小的木牌"
    assert store.updates[-1]["sketch_prompt_mode"] == "override"


def test_update_beat_rejects_invalid_mode(monkeypatch, tmp_path):
    client, _store = _client(monkeypatch, tmp_path)

    res = client.patch("/api/v1/projects/demo/episodes/1/beats/1", json={"sketch_prompt_mode": "replace"})

    assert res.status_code == 422
