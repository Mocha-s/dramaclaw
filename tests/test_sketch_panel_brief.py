from novelvideo.generators.prompt_builder import (
    GridConfig,
    PromptComponents,
    PromptContext,
    PromptMode,
    StyleConfig,
)
from novelvideo.generators.sketch_panel_brief import (
    BLACK_PANEL_DIRECTIVE,
    TITLE_CARD_DIRECTIVE,
    PanelBrief,
    build_panel_brief,
    build_panel_briefs,
    condense_prop_anchor,
    detect_panel_kind,
)
from novelvideo.utils.asset_resolver import ResolvedAssetRef


def _ctx(beats, **kwargs) -> PromptContext:
    return PromptContext(
        grid=GridConfig(rows=1, cols=len(beats), aspect_ratio="2:3"),
        characters={},
        style=StyleConfig(style_keywords="test", avoid_keywords=""),
        beats=beats,
        mode=PromptMode.SKETCH,
        **kwargs,
    )


def test_detect_panel_kind_priority():
    assert detect_panel_kind("黑场，画面全黑。", has_characters=False, has_prop_markers=False, allow_unnamed_people=False) == "black"
    assert detect_panel_kind("屏幕出现文字“明崇祯十一年”。", has_characters=False, has_prop_markers=False, allow_unnamed_people=False) == "title_card"
    assert detect_panel_kind("[[寻迹牌]]泛起微光", has_characters=False, has_prop_markers=True, allow_unnamed_people=False) == "prop_insert"
    assert detect_panel_kind("男人抱起[[纸箱]]", has_characters=False, has_prop_markers=True, allow_unnamed_people=True) == "normal"
    assert detect_panel_kind("[[寻迹牌]]泛起微光", has_characters=True, has_prop_markers=True, allow_unnamed_people=False) == "normal"
    assert detect_panel_kind("近景：瀑布水流", has_characters=False, has_prop_markers=False, allow_unnamed_people=False) == "normal"


def test_black_panel_replaces_description():
    brief = build_panel_brief({"beat_number": 1, "visual_description": "黑场，画面全黑。"}, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "black"
    assert brief.description == BLACK_PANEL_DIRECTIVE
    assert brief.panel_prefix == "[SOLID BLACK]"
    assert brief.attach_prop_refs is False


def test_title_card_panel_replaces_description():
    brief = build_panel_brief({"beat_number": 1, "visual_description": "屏幕出现文字“资料记载”。"}, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "title_card"
    assert brief.description == TITLE_CARD_DIRECTIVE
    assert brief.panel_prefix == "[TITLE CARD]"


def test_no_character_panel_is_flagged():
    brief = build_panel_brief({"beat_number": 2, "visual_description": "近景：一股瀑布水流冲过岩石。"}, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "normal"
    assert brief.has_characters is False
    assert brief.allow_unnamed_people is False
    assert brief.no_characters is True
    assert brief.panel_prefix == "[NO CHARACTERS]"
    assert brief.description == "近景：一股瀑布水流冲过岩石"


def test_people_words_allow_unnamed_people():
    brief = build_panel_brief({"beat_number": 13, "visual_description": "人群涌上步道。"}, panel_idx=1, ctx=_ctx([{}]))
    assert brief.allow_unnamed_people is True
    assert brief.no_characters is False
    assert brief.panel_prefix == "[UNNAMED PEOPLE ONLY]"


def test_detected_identities_count_as_characters():
    beat = {"beat_number": 5, "visual_description": "抬头看向水声传来的方向。", "detected_identities": ["寻禾_青年时期"]}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}]))
    assert brief.has_characters is True
    assert brief.panel_prefix == ""


def test_prop_insert_panel_attaches_refs_and_resolves_tag():
    prop_tag = PromptComponents.compute_prop_tag("寻迹牌")
    beat = {"beat_number": 10, "visual_description": "[[寻迹牌]]上的山脊纹样短暂泛起冷蓝白微光。"}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "prop_insert"
    assert brief.attach_prop_refs is True
    assert brief.panel_prefix == "[PROP INSERT]"
    assert f"寻迹牌 {prop_tag}" in brief.description
    assert "冷蓝白" not in brief.description


def test_prop_anchor_from_asset_refs():
    ref = ResolvedAssetRef(
        asset_type="prop",
        base_id="寻迹牌",
        variant_id=None,
        image_paths=[],
        text_description="横向不规则山形寻迹牌，约7到8厘米宽，单手可握。牌面为灰黑木 #3E3835。",
        source_level="base_text",
    )
    beat = {"beat_number": 10, "visual_description": "[[寻迹牌]]泛起微光。"}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}], prop_asset_refs={1: [ref]}))
    assert brief.prop_anchors == (("寻迹牌", "横向不规则山形寻迹牌，约7到8厘米宽，单手可握"),)
    assert brief.prop_anchor_lines == ["寻迹牌 — FORM: 横向不规则山形寻迹牌，约7到8厘米宽，单手可握"]


def test_condense_prop_anchor_truncates_and_falls_back():
    long_text = "甲" * 120
    assert condense_prop_anchor(long_text, prop_name="道具").endswith("…")
    assert len(condense_prop_anchor(long_text, prop_name="道具")) == 80
    assert condense_prop_anchor("", prop_name="七星剑", prop_type="weapon") == "七星剑（武器）"
    assert condense_prop_anchor("七星剑", prop_name="七星剑") == "七星剑（物件）"


def test_append_mode_adds_direction():
    beat = {"beat_number": 10, "visual_description": "[[寻迹牌]]泛起微光。", "sketch_prompt": "巴掌大小的挂件", "sketch_prompt_mode": "append"}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}]))
    assert brief.description.endswith("| ADDITIONAL DIRECTION: 巴掌大小的挂件")
    assert brief.kind == "prop_insert"


def test_override_mode_replaces_and_resets_auto_kind():
    beat = {"beat_number": 1, "visual_description": "黑场，画面全黑。", "sketch_prompt": "寻禾手中的木牌特写。", "sketch_prompt_mode": "override"}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "normal"
    assert brief.description == "寻禾手中的木牌特写"


def test_append_on_black_panel_keeps_directive():
    beat = {"beat_number": 1, "visual_description": "黑场。", "sketch_prompt": "两秒后淡入", "sketch_prompt_mode": "append"}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}]))
    assert brief.kind == "black"
    assert brief.description == f"{BLACK_PANEL_DIRECTIVE} | ADDITIONAL DIRECTION: 两秒后淡入"


def test_scene_and_prop_names_are_protected_from_color_stripping():
    scene_ref = ResolvedAssetRef(asset_type="scene", base_id="深蓝海湾", variant_id=None, image_paths=[], text_description="", source_level="base_text")
    beat = {"beat_number": 3, "visual_description": "镜头推向深蓝海湾，[[朱红木匣]]放在礁石上。", "scene_ref": {"scene_id": "深蓝海湾"}}
    brief = build_panel_brief(beat, panel_idx=1, ctx=_ctx([{}], scene_refs={1: [scene_ref]}))
    assert "深蓝海湾" in brief.description
    assert "朱红木匣" in brief.description


def test_build_panel_briefs_handles_bad_input():
    ctx = _ctx([{"beat_number": 1}, {"beat_number": 2, "visual_description": None}])
    briefs = build_panel_briefs(ctx)
    assert [b.kind for b in briefs] == ["normal", "normal"]
    assert all(isinstance(b, PanelBrief) for b in briefs)
