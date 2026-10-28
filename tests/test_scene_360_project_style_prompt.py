from __future__ import annotations

from novelvideo.director_world import scene_360_builder


def _prompt(monkeypatch, *, style: str, contract: str = "") -> str:
    monkeypatch.setattr(
        scene_360_builder,
        "get_style_preset",
        lambda _style, project_dir=None: {
            "style_keywords": f"STYLE KEYWORDS FOR {style}",
            "negative_prompt": f"STYLE AVOIDANCE FOR {style}",
        },
    )
    return scene_360_builder.build_prompt(
        scene_name="Test scene",
        scene_description="A fixed environment",
        style=style,
        has_master=True,
        has_reverse=True,
        spatial_contract_prompt_insert=contract,
    )


def test_360_prompt_preserves_selected_project_style_without_global_realism(monkeypatch):
    prompt = _prompt(monkeypatch, style="realistic")
    normalized = " ".join(prompt.split()).lower()

    assert "STYLE KEYWORDS FOR realistic" in prompt
    assert "STYLE AVOIDANCE FOR realistic" in prompt
    assert "preserve the selected project visual style and medium" in normalized
    assert "photorealism" not in prompt
    assert "Do not drift into photorealism" not in prompt


def test_360_prompt_does_not_force_realistic_for_illustration_style(monkeypatch):
    prompt = _prompt(monkeypatch, style="ink_illustration")

    assert "STYLE KEYWORDS FOR ink_illustration" in prompt
    assert "photorealism" not in prompt
    assert "photographic" not in prompt


def test_spatial_contract_adds_geometry_without_replacing_project_style(monkeypatch):
    prompt = _prompt(
        monkeypatch,
        style="ink_illustration",
        contract="CONTRACT: preserve the left-side bridge at the 25% panorama position.",
    )

    assert "STYLE KEYWORDS FOR ink_illustration" in prompt
    assert "CONTRACT: preserve the left-side bridge" in prompt
