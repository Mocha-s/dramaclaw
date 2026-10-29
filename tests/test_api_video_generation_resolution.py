from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_beat_resolution_options_are_global_for_every_backend():
    from novelvideo.api.routes.generation import _seedance2_resolution_options_for_backend

    expected = ("720p", "768p", "1080p", "2k", "4k")
    assert _seedance2_resolution_options_for_backend("seedance-2.0-fast") == expected
    assert _seedance2_resolution_options_for_backend("happyhorse-1.0") == expected
    assert _seedance2_resolution_options_for_backend("grok-video-channel") == expected
    assert _seedance2_resolution_options_for_backend("catalog-without-options") == expected


@pytest.mark.parametrize("resolution", ["720p", "768p", "1080p", "2k", "4k"])
def test_explicit_beat_resolution_is_not_downgraded(resolution: str):
    from novelvideo.api.routes.generation import _seedance2_resolution_for_backend

    assert _seedance2_resolution_for_backend(
        "seedance-2.0-fast", resolution, explicit=True
    ) == resolution


def test_explicit_beat_resolution_rejects_legacy_unsupported_tier():
    from novelvideo.api.routes.generation import _seedance2_resolution_for_backend

    with pytest.raises(ValueError, match="resolution must be one of"):
        _seedance2_resolution_for_backend("seedance-2.0-fast", "480p", explicit=True)


def test_explicit_beat_resolution_rejects_malformed_tier():
    from novelvideo.api.routes.generation import _seedance2_resolution_for_backend

    with pytest.raises(ValueError, match="resolution must be one of"):
        _seedance2_resolution_for_backend(
            "seedance-2.0-fast", "720p-plus", explicit=True
        )


def test_omitted_beat_resolution_keeps_legacy_default():
    from novelvideo.api.routes.generation import _seedance2_resolution_for_backend

    assert _seedance2_resolution_for_backend("seedance-2.0-fast", None) == "720p"


@pytest.mark.asyncio
async def test_single_video_route_keeps_legacy_default_when_resolution_is_omitted(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import generation
    from novelvideo.api.schemas import SingleVideoRequest

    frame = tmp_path / "frame.png"
    frame.write_bytes(b"frame")
    ctx = SimpleNamespace(project_id="project-demo")
    beat = {
        "beat_number": 1,
        "video_mode": "first_frame",
        "video_prompt": "A woman walks through a rainy street",
        "duration_seconds": 5,
        "audio_type": "silence",
    }

    class Store:
        async def get_beats_as_dicts(self, _episode):
            return [beat]

    class Backend:
        def __init__(self):
            self.payload = None

        async def enqueue_project_task(self, _ctx, **kwargs):
            self.payload = kwargs["payload"]
            return SimpleNamespace(
                task_state=SimpleNamespace(task_id="task-video"),
                backend="test",
                queue="video",
            )

    backend = Backend()
    resolved = SimpleNamespace(
        ctx=ctx,
        username="admin",
        project_name="demo",
        output_dir=str(tmp_path),
    )

    class FakePathResolver:
        def __init__(self, _output, _episode):
            pass

        def first_frame_for_video(self, _beat, use_director_render=False):
            return frame

    monkeypatch.setattr(generation, "_resolve_generation_project", _async_value(resolved))
    monkeypatch.setattr(generation, "make_sqlite_store_for_context", _async_value(Store()))
    monkeypatch.setattr(generation, "get_task_backend", lambda: backend)
    monkeypatch.setattr(generation, "_api_audio_duration_seconds", _async_value(None))
    from novelvideo.utils import path_resolver

    monkeypatch.setattr(path_resolver, "PathResolver", FakePathResolver)
    monkeypatch.setattr(
        generation,
        "_single_video_billing_metadata",
        lambda _backend, *, resolution, duration: {
            "pricing_params": {"resolution": resolution}
        },
    )
    monkeypatch.setattr(generation, "project_task_state_key", lambda *_args, **_kwargs: "task-key")

    result = await generation.generate_single_video(
        project="demo",
        episode_num=1,
        beat_num=1,
        body=SingleVideoRequest(video_backend="generic-provider"),
        user={"username": "admin"},
    )

    assert result["ok"] is True
    assert "resolution" not in backend.payload["config"]
    assert backend.payload["billing"]["pricing_params"]["resolution"] == "720p"


def test_single_video_billing_uses_explicit_resolution():
    from novelvideo.api.routes.generation import _single_video_billing_metadata

    billing = _single_video_billing_metadata(
        "seedance-2.0-fast", resolution="4k", duration=5
    )

    assert billing["pricing_params"]["resolution"] == "4k"


def test_compose_export_resolution_contract_is_still_independent():
    from novelvideo.api.schemas import SingleVideoRequest, VideoComposeRequest

    single = SingleVideoRequest()
    compose = VideoComposeRequest()

    assert "resolution" not in single.model_fields_set
    assert compose.resolution == "720x1280"


@pytest.mark.asyncio
async def test_single_video_route_queues_exact_explicit_resolution(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import generation
    from novelvideo.api.schemas import SingleVideoRequest

    frame = tmp_path / "frame.png"
    frame.write_bytes(b"frame")
    ctx = SimpleNamespace(project_id="project-demo")
    beat = {
        "beat_number": 1,
        "video_mode": "first_frame",
        "video_prompt": "A woman walks through a rainy street",
        "duration_seconds": 5,
        "audio_type": "silence",
    }

    class Store:
        async def get_beats_as_dicts(self, _episode):
            return [beat]

    class Backend:
        def __init__(self):
            self.payload = None

        async def enqueue_project_task(self, _ctx, **kwargs):
            self.payload = kwargs["payload"]
            return SimpleNamespace(
                task_state=SimpleNamespace(task_id="task-video"),
                backend="test",
                queue="video",
            )

    backend = Backend()
    store = Store()
    resolved = SimpleNamespace(
        ctx=ctx,
        username="admin",
        project_name="demo",
        output_dir=str(tmp_path),
    )

    class FakePathResolver:
        def __init__(self, _output, _episode):
            pass

        def first_frame_for_video(self, _beat, use_director_render=False):
            return frame

    monkeypatch.setattr(generation, "_resolve_generation_project", _async_value(resolved))
    monkeypatch.setattr(generation, "make_sqlite_store_for_context", _async_value(store))
    monkeypatch.setattr(generation, "get_task_backend", lambda: backend)
    monkeypatch.setattr(generation, "_api_audio_duration_seconds", _async_value(None))
    from novelvideo.utils import path_resolver

    monkeypatch.setattr(path_resolver, "PathResolver", FakePathResolver)
    monkeypatch.setattr(
        generation,
        "_single_video_billing_metadata",
        lambda _backend, *, resolution, duration: {
            "pricing_params": {"resolution": resolution}
        },
    )
    monkeypatch.setattr(generation, "project_task_state_key", lambda *_args, **_kwargs: "task-key")

    result = await generation.generate_single_video(
        project="demo",
        episode_num=1,
        beat_num=1,
        body=SingleVideoRequest(video_backend="generic-provider", resolution="4k"),
        user={"username": "admin"},
    )

    assert result["ok"] is True
    assert backend.payload["config"]["resolution"] == "4k"
    assert backend.payload["billing"]["pricing_params"]["resolution"] == "4k"


def _async_value(value):
    async def resolve(*_args, **_kwargs):
        return value

    return resolve


@pytest.mark.asyncio
async def test_single_video_route_rejects_explicit_resolution_outside_product_set(
    monkeypatch, tmp_path
):
    from novelvideo.api.routes import generation
    from novelvideo.api.schemas import SingleVideoRequest

    frame = tmp_path / "frame.png"
    frame.write_bytes(b"frame")
    resolved = SimpleNamespace(
        ctx=None,
        username="admin",
        project_name="demo",
        output_dir=str(tmp_path),
    )

    class Store:
        async def get_beats_as_dicts(self, _episode):
            return [
                {
                    "beat_number": 1,
                    "video_mode": "first_frame",
                    "video_prompt": "A woman walks through a rainy street",
                    "duration_seconds": 5,
                    "audio_type": "silence",
                }
            ]

    class FakePathResolver:
        def __init__(self, _output, _episode):
            pass

        def first_frame_for_video(self, _beat, use_director_render=False):
            return frame

    monkeypatch.setattr(generation, "_resolve_generation_project", _async_value(resolved))
    monkeypatch.setattr(generation, "make_sqlite_store", _async_value(Store()))
    monkeypatch.setattr(generation, "_api_audio_duration_seconds", _async_value(None))
    from novelvideo.utils import path_resolver

    monkeypatch.setattr(path_resolver, "PathResolver", FakePathResolver)

    result = await generation.generate_single_video(
        project="demo",
        episode_num=1,
        beat_num=1,
        body=SingleVideoRequest(video_backend="generic-provider", resolution="480p"),
        user={"username": "admin"},
    )

    assert result["ok"] is False
    assert "resolution must be one of" in result["error"]
