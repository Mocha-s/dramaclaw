"""文本处理工具函数。"""

import re
from typing import Iterable

# 颜色词列表（单字和多字）
_COLOR_WORDS = [
    # 双字及以上颜色词（先匹配长的）
    "橘红", "橘黄", "橙红", "橙黄", "暗红", "深红", "鲜红", "猩红", "殷红", "嫣红",
    "粉红", "桃红", "玫红", "枣红", "酒红", "暗绿", "深绿", "浅绿", "翠绿", "墨绿",
    "碧绿", "草绿", "嫩绿", "橄榄绿", "暗蓝", "深蓝", "浅蓝", "湛蓝", "蔚蓝", "靛蓝",
    "宝蓝", "天蓝", "冷蓝", "暗黄", "深黄", "浅黄", "金黄", "鹅黄", "暖黄", "土黄",
    "明黄", "暗紫", "深紫", "浅紫", "淡紫", "紫红", "暗灰", "深灰", "浅灰", "银灰",
    "雪白", "惨白", "苍白", "煞白", "发白", "纯白", "乳白", "月白", "漆黑", "乌黑",
    "黝黑", "焦黑", "赤红", "朱红", "橘色", "橙色", "红色", "绿色", "蓝色", "黄色",
    "紫色", "灰色", "白色", "黑色", "粉色", "棕色", "褐色", "青色", "金色", "银色",
    "铜色", "玫瑰色", "琥珀色",
    # 单字颜色词
    "红", "绿", "蓝", "黄", "紫", "灰", "白", "黑", "粉", "棕", "褐", "青",
    "金", "银", "铜", "翠", "碧", "赤", "朱", "丹", "绯", "绛", "橘", "橙",
]

# 按长度降序排列，确保先匹配长词
_COLOR_WORDS.sort(key=len, reverse=True)

_MULTI_CHAR_COLOR_WORDS = [w for w in _COLOR_WORDS if len(w) >= 2]
_SINGLE_CHAR_COLOR_WORDS = [w for w in _COLOR_WORDS if len(w) == 1]

# 多字颜色词总是剥离（可带 色/色的/的 后缀）；单字颜色词只在带后缀时剥离，
# 否则“黄果树”“白水河”“黑场”这类专名会被削掉。
_COLOR_PATTERN = re.compile(
    r"(?:(?:" + "|".join(re.escape(w) for w in _MULTI_CHAR_COLOR_WORDS) + r")(?:色的|色|的)?)"
    r"|(?:(?:" + "|".join(re.escape(w) for w in _SINGLE_CHAR_COLOR_WORDS) + r")(?:色的|色|的))"
)

# 镜头状态词：含颜色字但描述的是画面状态，不是物体颜色。
SCREEN_STATE_TERMS: tuple[str, ...] = (
    "黑场", "黑屏", "切黑", "全黑", "白场", "闪白", "淡入", "淡出",
)

# {{身份}} 标记与【镜头提示】整段保护。
_PROTECTED_SPAN_PATTERN = re.compile(r"\{\{.*?\}\}|【[^】]*】")

# 占位符前缀（用不可能出现在正常文本中的字符序列）
_PLACEHOLDER_PREFIX = "\x00MARK"


def strip_color_words(text: str, protected_terms: Iterable[str] = ()) -> str:
    """从文本中剥离颜色修饰词。

    保护范围：``{{}}`` 身份标记、``【】`` 镜头提示、镜头状态词
    （:data:`SCREEN_STATE_TERMS`）以及调用方传入的 ``protected_terms``
    （通常是场景名、道具名）。

    Examples:
        >>> strip_color_words("惨白脸色")
        '脸色'
        >>> strip_color_words("红色的长裙")
        '长裙'
        >>> strip_color_words("红盖头")
        '红盖头'
        >>> strip_color_words("黑场，画面全黑")
        '黑场，画面全黑'
        >>> strip_color_words("朱红木匣", protected_terms=["朱红木匣"])
        '朱红木匣'
        >>> strip_color_words("{{沈知薇_大婚}}鲜红的嫁衣")
        '{{沈知薇_大婚}}嫁衣'
    """
    if not text:
        return text

    placeholders: list[str] = []

    def _hold(value: str) -> str:
        placeholders.append(value)
        return f"{_PLACEHOLDER_PREFIX}{len(placeholders) - 1}\x00"

    protected = _PROTECTED_SPAN_PATTERN.sub(lambda m: _hold(m.group(0)), text)

    terms = sorted(
        {
            str(term).strip()
            for term in (*SCREEN_STATE_TERMS, *protected_terms)
            if str(term or "").strip()
        },
        key=len,
        reverse=True,
    )
    for term in terms:
        if term in protected:
            protected = protected.replace(term, _hold(term))

    result = _COLOR_PATTERN.sub("", protected)

    for idx, value in enumerate(placeholders):
        result = result.replace(f"{_PLACEHOLDER_PREFIX}{idx}\x00", value)
    return result
