"""草图面板简报：把每个 beat 判定为普通 / 黑场 / 字幕卡 / 道具特写并产出面板文本。

SKETCH 模式下 ``has_characters`` 只信任 ``{{身份}}`` 标记，不读 ``detected_identities``，
避免上一张误画的人物在重生成时自我强化；其他模式仍兼顾检测结果。

纯函数模块，不访问存储或网络。``prompt_builder`` 在函数内延迟导入，避免循环引用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Literal

from novelvideo.models import (
    beat_scene_id,
    collect_prop_marker_ids_from_beat,
    extract_char_identities_from_markers,
    real_detected_identities,
)
from novelvideo.utils.text_utils import strip_color_words

if TYPE_CHECKING:  # pragma: no cover
    from novelvideo.generators.prompt_builder import PromptContext

PanelKind = Literal["normal", "black", "title_card", "prop_insert"]

BLACK_SCREEN_TERMS: tuple[str, ...] = (
    "画面全黑", "画面切黑", "淡出至黑", "黑场", "黑屏", "切黑", "全黑",
)
TITLE_CARD_TERMS: tuple[str, ...] = (
    "屏幕出现文字", "来源字幕", "事实卡", "标题卡", "屏幕文字", "字幕", "片名", "片尾",
)
PEOPLE_TERMS: tuple[str, ...] = (
    "人群", "路人", "行人", "游客", "众人", "人影", "村民", "士兵", "孩子", "围观", "人们",
    "男人", "女人", "男子", "女子", "老人", "少年", "少女", "青年", "男孩", "女孩",
    "身影", "人物", "乘客", "顾客", "观众",
)
BLACK_PANEL_DIRECTIVE = (
    "SOLID BLACK PANEL: fill the entire panel with flat black. "
    "No scenery, no characters, no objects, no text."
)
TITLE_CARD_DIRECTIVE = (
    "TITLE CARD PANEL: a plain blank card on a neutral background. "
    "No scenery, no characters, no readable text."
)
PROP_ANCHOR_MAX_CHARS = 80
PROP_TYPE_LABELS: dict[str, str] = {
    "artifact": "器物",
    "weapon": "武器",
    "document": "文件",
    "accessory": "配饰",
    "furniture": "家具",
    "object": "物件",
}
_TRAILING_PUNCTUATION = "。！？，、；："
_SENTENCE_SPLIT = re.compile(r"[。；;\n]")


@dataclass(frozen=True)
class PanelBrief:
    beat_number: int
    kind: PanelKind
    has_characters: bool
    allow_unnamed_people: bool
    description: str
    prop_anchors: tuple[tuple[str, str], ...]
    attach_prop_refs: bool

    @property
    def no_characters(self) -> bool:
        return (
            not self.has_characters
            and not self.allow_unnamed_people
            and self.kind in ("normal", "prop_insert")
        )

    @property
    def panel_prefix(self) -> str:
        if self.kind == "black":
            return "[SOLID BLACK]"
        if self.kind == "title_card":
            return "[TITLE CARD]"
        if self.kind == "prop_insert":
            return "[PROP INSERT]"
        if self.allow_unnamed_people and not self.has_characters:
            return "[UNNAMED PEOPLE ONLY]"
        if self.no_characters:
            return "[NO CHARACTERS]"
        return ""

    @property
    def prop_anchor_lines(self) -> list[str]:
        return [f"{prop_id} — FORM: {anchor}" for prop_id, anchor in self.prop_anchors]


def detect_panel_kind(
    visual_description: str,
    *,
    has_characters: bool,
    has_prop_markers: bool,
    allow_unnamed_people: bool,
) -> PanelKind:
    text = str(visual_description or "")
    if any(term in text for term in BLACK_SCREEN_TERMS):
        return "black"
    if any(term in text for term in TITLE_CARD_TERMS):
        return "title_card"
    if has_prop_markers and not has_characters and not allow_unnamed_people:
        return "prop_insert"
    return "normal"


def condense_prop_anchor(
    text: str,
    *,
    prop_name: str,
    prop_type: str = "",
    protected_terms: Iterable[str] = (),
) -> str:
    first = _SENTENCE_SPLIT.split(str(text or "").strip(), maxsplit=1)[0].strip()
    first = strip_color_words(first, protected_terms=[prop_name, *protected_terms]).strip(" ，,")
    if len(first) > PROP_ANCHOR_MAX_CHARS:
        first = first[: PROP_ANCHOR_MAX_CHARS - 1].rstrip() + "…"
    if not first or first == prop_name:
        label = PROP_TYPE_LABELS.get(str(prop_type or "").strip().lower(), "物件")
        return f"{prop_name}（{label}）"
    return first


def _process_description(text: str, ctx: "PromptContext", protected_terms: list[str]) -> str:
    from novelvideo.generators.prompt_builder import _resolve_prop_marker_tags
    from novelvideo.utils.identity_resolver import (
        build_identity_to_char_map,
        resolve_visual_description_markers,
    )

    processed = _resolve_prop_marker_tags(str(text or ""))
    processed = strip_color_words(processed, protected_terms=protected_terms)
    id_to_char = build_identity_to_char_map(ctx.characters)
    processed = resolve_visual_description_markers(
        processed, ctx.characters, id_to_char, use_identity_id=True
    )
    return " ".join(processed.rstrip(_TRAILING_PUNCTUATION).split())


def _protected_terms(beat: dict, panel_idx: int, ctx: "PromptContext", prop_ids: list[str]) -> list[str]:
    terms = [str(beat_scene_id(beat) or "").strip()]
    for ref in ctx.scene_refs.get(panel_idx, []) or []:
        terms.append(str(getattr(ref, "base_id", "") or "").strip())
    terms.extend(prop_ids)
    return [term for term in terms if term]


def _prop_anchors(panel_idx: int, ctx: "PromptContext", protected_terms: list[str]) -> tuple[tuple[str, str], ...]:
    anchors: list[tuple[str, str]] = []
    seen: set[str] = set()
    for ref in ctx.prop_asset_refs.get(panel_idx, []) or []:
        if str(getattr(ref, "asset_type", "prop") or "prop") != "prop":
            continue
        base_id = str(getattr(ref, "base_id", "") or "").strip()
        if not base_id or base_id in seen:
            continue
        seen.add(base_id)
        anchor = condense_prop_anchor(
            str(getattr(ref, "text_description", "") or ""),
            prop_name=base_id,
            prop_type=str(getattr(ref, "prop_type", "") or ""),
            protected_terms=protected_terms,
        )
        anchors.append((base_id, anchor))
    return tuple(anchors)


def build_panel_brief(beat: dict, *, panel_idx: int, ctx: "PromptContext") -> PanelBrief:
    beat = beat if isinstance(beat, dict) else {}
    raw = str(beat.get("visual_description") or "")
    beat_number = int(beat.get("beat_number") or panel_idx)
    markers = extract_char_identities_from_markers(raw, strict=False)
    has_characters = bool(markers)
    if getattr(ctx.mode, "name", "") != "SKETCH":
        has_characters = has_characters or bool(
            real_detected_identities(beat.get("detected_identities") or [])
        )
    allow_unnamed = (not has_characters) and any(term in raw for term in PEOPLE_TERMS)
    prop_ids = collect_prop_marker_ids_from_beat(beat)
    kind = detect_panel_kind(
        raw,
        has_characters=has_characters,
        has_prop_markers=bool(prop_ids),
        allow_unnamed_people=allow_unnamed,
    )
    protected = _protected_terms(beat, panel_idx, ctx, prop_ids)

    custom = str(beat.get("sketch_prompt") or "").strip()
    mode = str(beat.get("sketch_prompt_mode") or "append").strip().lower()
    if mode == "override" and custom:
        description = _process_description(custom, ctx, protected)
        if kind in ("black", "title_card"):
            kind = "normal"
    elif kind == "black":
        description = BLACK_PANEL_DIRECTIVE
    elif kind == "title_card":
        description = TITLE_CARD_DIRECTIVE
    else:
        description = _process_description(raw, ctx, protected)
    if mode == "append" and custom:
        extra = _process_description(custom, ctx, protected)
        description = f"{description} | ADDITIONAL DIRECTION: {extra}"

    return PanelBrief(
        beat_number=beat_number,
        kind=kind,
        has_characters=has_characters,
        allow_unnamed_people=allow_unnamed,
        description=description,
        prop_anchors=_prop_anchors(panel_idx, ctx, protected),
        attach_prop_refs=kind == "prop_insert",
    )


def build_panel_briefs(ctx: "PromptContext") -> list[PanelBrief]:
    total = ctx.grid.total_panels
    return [
        build_panel_brief(beat, panel_idx=idx, ctx=ctx)
        for idx, beat in enumerate(ctx.beats[:total], start=1)
    ]
