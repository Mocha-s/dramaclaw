from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from novelvideo.project_context import ProjectContext


def test_sketch_billing_metadata_uses_explicit_image_size():
    from novelvideo.api.routes.generation import _sketch_regen_billing_metadata

    billing = _sketch_regen_billing_metadata(
        "gpt-image-2",
        "1x1_2-3_sketch",
        image_size="4K",
    )

    assert billing["pricing_params"]["size"] == "4K"


def test_invalid_legacy_sketch_size_is_not_treated_as_explicit():
    from novelvideo.api.routes.generation import _sketch_image_size_is_explicit

    assert _sketch_image_size_is_explicit({"sketch_image_size": "8K"}) is False


def test_explicit_sketch_size_rejects_google_models_without_size_support():
    from novelvideo.generators.nanobanana_grid import explicit_image_size_support_error

    error = explicit_image_size_support_error(
        provider="google",
        model="gemini-2.5-flash-image",
        strict=True,
    )

    assert error is not None
    assert "does not support explicit image_size" in error
    assert explicit_image_size_support_error(
        provider="google",
        model="gemini-3-pro-image-preview",
        strict=True,
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("two_pass", [False, True])
async def test_sketch_runner_passes_project_size_to_generator(
    tmp_path, monkeypatch, two_pass
):
    from novelvideo.generators import nanobanana_grid, pool_indexer
    from novelvideo.task_backend.runners import sketch as sketch_runner

    captured: dict = {}

    class FakeGridGenerator:
        provider = "test"
        model = "fake"

        def __init__(self, **_kwargs):
            captured["generator_config"] = _kwargs["config"]

        async def generate_grid(self, **kwargs):
            captured.update(kwargs)
            output_path = Path(kwargs["output_path"])
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (160, 90), "blue").save(output_path)
            return type("Result", (), {"success": True, "error": None, "generation_time": 0})()

        async def reformat_sketch(self, **kwargs):
            captured["reformat_target_size"] = kwargs["target_size"]
            Image.new("RGB", (160, 90), "blue").save(kwargs["output_path"])
            return type("Result", (), {"success": True, "error": None, "generation_time": 0})()

    monkeypatch.setattr(nanobanana_grid, "NanoBananaGridGenerator", FakeGridGenerator)
    if two_pass:
        monkeypatch.setattr(nanobanana_grid, "sketch_pass1_mode_key", lambda _mode: "1x1_1-1")
    monkeypatch.setattr(
        pool_indexer,
        "save_grid_and_split",
        lambda **kwargs: {
            "grid_path": kwargs["grid_image_path"],
            "cell_paths": [tmp_path / "beat_01.png"],
            "added": 1,
            "skipped": 0,
        },
    )

    ctx = ProjectContext(
        project_id="project-demo",
        project_name="demo",
        owner_type="user",
        owner_id="owner-1",
        owner_username="admin",
        requester_user_id="owner-1",
        requester_username="admin",
        requester_principals=(("user", "owner-1"),),
        effective_role="editor",
        home_node_id="node-a",
        output_dir=tmp_path,
        state_dir=tmp_path / "state",
        runtime_dir=tmp_path / "runtime",
        is_home_node=True,
    )
    result = await sketch_runner._run_sketch_generation_async(
        {
            "task_type": "sketch_grid_generation",
            "episode": 1,
            "scope": "grid_0",
            "payload": {
                "output_dir": str(tmp_path),
                    "config": {
                        "image_size": "4K",
                        "strict_image_size": True,
                    "direct_sketch_beats": True,
                    "mode_key": "1x1_16-9",
                    "beat_numbers": [1],
                    "beats": [{"beat_number": 1, "visual_description": "test"}],
                    "character_map": {},
                    "promote_direct_sketch": False,
                },
            },
        },
        ctx,
    )

    assert result["beat_numbers"] == [1]
    assert captured["force_image_size"] == "4K"
    assert captured["generator_config"]["image_size"] == "4K"
    assert captured["generator_config"]["strict_image_size"] is True
    if two_pass:
        assert captured["reformat_target_size"] == "4K"


@pytest.mark.asyncio
async def test_openai_rejection_of_explicit_sketch_size_is_not_retried(monkeypatch):
    import openai

    from novelvideo.generators import nanobanana_grid

    requests: list[dict] = []

    class FakeImages:
        async def generate(self, **kwargs):
            requests.append(kwargs)
            raise RuntimeError("Unsupported parameter: 'size'")

    class FakeClient:
        def __init__(self, **_kwargs):
            self.images = FakeImages()

    class FakeUsageMeter:
        async def reserve_current_model_call_credit(self, **_kwargs):
            return "reservation"

        async def refund_model_call_credit_reservation(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(openai, "AsyncOpenAI", FakeClient)
    monkeypatch.setattr(nanobanana_grid, "get_usage_meter", lambda: FakeUsageMeter())
    monkeypatch.setattr(
        nanobanana_grid,
        "_mark_paid_image_attempt_accepted",
        _noop_async,
    )

    image_bytes, _text, error = await nanobanana_grid._call_openai_image_api(
        api_key="test-key",
        model="gpt-image-2",
        prompt="sketch",
        image_config={
            "aspect_ratio": "16:9",
            "image_size": "4K",
            "quality": "low",
            "strict_image_size": True,
        },
    )

    assert len(requests) == 1
    assert requests[0]["size"] == nanobanana_grid.resolve_openai_image_size("16:9", "4K")
    assert image_bytes is None
    assert "size" in error


async def _noop_async(*_args, **_kwargs):
    return None
