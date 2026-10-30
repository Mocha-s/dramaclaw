from __future__ import annotations

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


@pytest.mark.asyncio
async def test_sketch_runner_passes_project_size_to_generator(tmp_path, monkeypatch):
    from novelvideo.generators import nanobanana_grid, pool_indexer
    from novelvideo.task_backend.runners import sketch as sketch_runner

    captured: dict = {}

    class FakeGridGenerator:
        provider = "test"
        model = "fake"

        def __init__(self, **_kwargs):
            pass

        async def generate_grid(self, **kwargs):
            captured.update(kwargs)
            output_path = tmp_path / "sketch.jpg"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (160, 90), "blue").save(output_path)
            return type("Result", (), {"success": True, "error": None, "generation_time": 0})()

    monkeypatch.setattr(nanobanana_grid, "NanoBananaGridGenerator", FakeGridGenerator)
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
