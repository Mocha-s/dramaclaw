from __future__ import annotations

from pathlib import Path

import pytest

from novelvideo.project_context import ProjectContext


def _ctx(tmp_path: Path) -> ProjectContext:
    return ProjectContext(
        project_id="proj_optimizer",
        project_name="demo",
        owner_type="user",
        owner_id="owner",
        owner_username="admin",
        requester_user_id="owner",
        requester_username="admin",
        requester_principals=(("user", "owner"),),
        effective_role="editor",
        home_node_id="node_a",
        output_dir=tmp_path,
        state_dir=tmp_path / "state",
        runtime_dir=tmp_path / "runtime",
        is_home_node=True,
    )


def _make_sketches(tmp_path: Path, beat_numbers: list[int]) -> None:
    from novelvideo.utils.path_resolver import PathResolver

    for beat_number in beat_numbers:
        path = PathResolver(str(tmp_path), 1).sketch(beat_number)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-png")


class _TaskManager:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def update_progress_for_project(self, *_args, **kwargs):
        self.logs.extend(kwargs.get("logs") or [])


class _Store:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def initialize(self):
        return None

    async def load_graph_state(self):
        return None

    async def update_beat_asset(self, **kwargs):
        self.saved.append(kwargs)
        return True

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_optimizer_retries_one_beat_until_third_attempt_and_saves_once(
    monkeypatch, tmp_path: Path
):
    from novelvideo.agents import global_video_optimizer
    from novelvideo import cognee
    from novelvideo.task_backend.runners import video

    _make_sketches(tmp_path, [1])
    manager = _TaskManager()
    store = _Store()
    attempts = 0

    class Optimizer:
        async def optimize_single_beat(self, **_kwargs):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise RuntimeError("temporary provider error")
            return {"prompt": "optimized prompt"}

    monkeypatch.setattr(video, "get_task_manager", lambda: manager)
    monkeypatch.setattr(cognee, "CogneeStore", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(global_video_optimizer, "get_global_video_optimizer", lambda: Optimizer())
    monkeypatch.setattr(
        global_video_optimizer,
        "prepare_global_optimizer_input",
        lambda **_kwargs: (["grid.png"], {}, 1),
    )
    monkeypatch.setattr(video.asyncio, "sleep", lambda *_args: _completed())

    result = await video._run_global_optimize_video_async(
        {"episode": 1, "payload": {"episode": 1, "beats": [{"beat_number": 1}], "characters": [], "output_dir": str(tmp_path)}},
        _ctx(tmp_path),
    )

    assert attempts == 3
    assert result["optimized"] == 1
    assert result["failed"] == 0
    assert result["failed_beats"] == []
    assert len(store.saved) == 1
    assert store.saved[0]["video_prompt"] == "optimized prompt"


@pytest.mark.asyncio
async def test_optimizer_returns_partial_success_and_keeps_successful_beat(
    monkeypatch, tmp_path: Path
):
    from novelvideo.agents import global_video_optimizer
    from novelvideo import cognee
    from novelvideo.task_backend.runners import video

    _make_sketches(tmp_path, [1, 2])
    store = _Store()
    manager = _TaskManager()

    class Optimizer:
        async def optimize_single_beat(self, **kwargs):
            if kwargs["beat"]["beat_number"] == 1:
                return {"prompt": "success"}
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(video, "get_task_manager", lambda: manager)
    monkeypatch.setattr(cognee, "CogneeStore", lambda *_args, **_kwargs: store)
    monkeypatch.setattr(global_video_optimizer, "get_global_video_optimizer", lambda: Optimizer())
    monkeypatch.setattr(global_video_optimizer, "prepare_global_optimizer_input", lambda **_kwargs: (["grid.png"], {}, 2))

    result = await video._run_global_optimize_video_async(
        {"episode": 1, "payload": {"episode": 1, "beats": [{"beat_number": 1}, {"beat_number": 2}], "characters": [], "output_dir": str(tmp_path)}},
        _ctx(tmp_path),
    )

    assert result["optimized"] == 1
    assert result["failed"] == 1
    assert result["failed_beats"][0]["beat_number"] == 2
    assert result["failed_beats"][0]["attempts"] == 3
    assert len(store.saved) == 1
    assert any("1/2" in message for message in manager.logs)


@pytest.mark.asyncio
async def test_optimizer_all_beats_failed_raises_last_safe_error(monkeypatch, tmp_path: Path):
    from novelvideo.agents import global_video_optimizer
    from novelvideo import cognee
    from novelvideo.task_backend.runners import video

    _make_sketches(tmp_path, [1])

    class Optimizer:
        async def optimize_single_beat(self, **_kwargs):
            raise RuntimeError("provider secret detail")

    monkeypatch.setattr(video, "get_task_manager", lambda: _TaskManager())
    monkeypatch.setattr(cognee, "CogneeStore", lambda *_args, **_kwargs: _Store())
    monkeypatch.setattr(global_video_optimizer, "get_global_video_optimizer", lambda: Optimizer())
    monkeypatch.setattr(global_video_optimizer, "prepare_global_optimizer_input", lambda **_kwargs: (["grid.png"], {}, 1))

    with pytest.raises(RuntimeError, match="0/1") as failed:
        await video._run_global_optimize_video_async(
            {"episode": 1, "payload": {"episode": 1, "beats": [{"beat_number": 1}], "characters": [], "output_dir": str(tmp_path)}},
            _ctx(tmp_path),
        )

    assert "provider secret detail" not in str(failed.value)


async def _completed():
    return None
