from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient


class _BriefStore:
    async def get_beats_as_dicts(self, episode_num: int):
        assert episode_num == 1
        return [
            {"beat_number": 1, "visual_description": "黑场，画面全黑。"},
            {"beat_number": 10, "visual_description": "[[寻迹牌]]上的山脊纹样泛起微光。", "sketch_prompt": "巴掌大小", "sketch_prompt_mode": "append"},
        ]

    def get_episode(self, episode_num: int):
        return SimpleNamespace(prop_menu=[])

    def get_cached_prop(self, prop_id: str):
        return None

    def get_sketch_colors(self, episode_num: int):
        return {}


def _client(monkeypatch, tmp_path):
    from novelvideo.api.routes import generation
    from novelvideo.api.deps import ProjectResolution

    store = _BriefStore()

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

    async def fake_character_map(*args, **kwargs):
        return {}

    monkeypatch.setattr(generation, "resolve_project_scope", fake_resolve_project_scope)
    monkeypatch.setattr(generation, "get_state_dir", lambda username, project: str(tmp_path / "state"))
    monkeypatch.setattr(generation, "load_project_config", lambda username, project: {})
    monkeypatch.setattr(generation, "make_sqlite_store_for_context", fake_make_sqlite_store_for_context)
    monkeypatch.setattr(generation, "_build_character_map", fake_character_map)

    app = FastAPI()
    app.include_router(generation.router, prefix="/api/v1")
    app.dependency_overrides[generation.get_api_user] = lambda: {"username": "alice"}
    return TestClient(app)


def test_sketch_brief_reports_black_panel(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    res = client.get("/api/v1/projects/demo/episodes/1/beats/1/sketch-brief")

    body = res.json()
    assert res.status_code == 200
    assert body["ok"] is True
    assert body["data"]["kind"] == "black"
    assert body["data"]["description"].startswith("SOLID BLACK PANEL")
    assert body["data"]["has_characters"] is False


def test_sketch_brief_reports_prop_insert_with_direction(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/v1/projects/demo/episodes/1/beats/10/sketch-brief").json()

    assert body["data"]["kind"] == "prop_insert"
    assert body["data"]["attach_prop_refs"] is True
    assert body["data"]["description"].endswith("| ADDITIONAL DIRECTION: 巴掌大小")
    assert body["data"]["prop_anchor_lines"] == ["寻迹牌 — FORM: 寻迹牌（物件）"]


def test_sketch_brief_missing_beat(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)

    body = client.get("/api/v1/projects/demo/episodes/1/beats/99/sketch-brief").json()

    assert body == {"ok": False, "error": "Beat 99 not found"}
