from novelvideo.utils.text_utils import SCREEN_STATE_TERMS, strip_color_words


def test_strips_multi_char_color_words_and_suffixed_single_chars():
    assert strip_color_words("红色的长裙") == "长裙"
    assert strip_color_words("惨白脸色") == "脸色"
    assert strip_color_words("一抹红的霞光") == "一抹霞光"


def test_bare_single_char_colors_are_kept():
    assert strip_color_words("红盖头") == "红盖头"
    assert strip_color_words("青石板") == "青石板"
    assert strip_color_words("镜头推向黄果树主瀑布") == "镜头推向黄果树主瀑布"
    assert strip_color_words("白水河边") == "白水河边"


def test_screen_state_terms_are_protected_by_default():
    assert "黑场" in SCREEN_STATE_TERMS
    assert strip_color_words("黑场，画面全黑。") == "黑场，画面全黑。"
    assert strip_color_words("画面切黑。") == "画面切黑。"
    assert strip_color_words("漆黑的夜里切黑") == "夜里切黑"


def test_bracket_cues_are_protected():
    assert strip_color_words("【黑屏】然后红色的灯亮起") == "【黑屏】然后灯亮起"


def test_protected_terms_keep_asset_names():
    text = "朱红木匣放在深蓝海湾边"
    assert strip_color_words(text, protected_terms=["朱红木匣", "深蓝海湾"]) == text


def test_protected_terms_do_not_block_other_color_words():
    out = strip_color_words("朱红木匣旁一件黄色的雨衣", protected_terms=["朱红木匣"])
    assert out == "朱红木匣旁一件雨衣"


def test_identity_markers_still_protected():
    assert strip_color_words("{{沈知薇_大婚}}鲜红的嫁衣") == "{{沈知薇_大婚}}嫁衣"


def test_empty_and_none_pass_through():
    assert strip_color_words("") == ""
    assert strip_color_words(None) is None
