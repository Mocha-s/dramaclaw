# 草图面板简报（Sketch Panel Brief）设计

- 日期：2026-11-01
- 分支：`feat/sketch-panel-brief`（自 `main` 切出）
- 状态：设计已与需求方逐节确认，待实现

## 1. 背景与问题

在项目 `xunjiren_1` 第 1 集的 42 拍中，草图阶段出现五类系统性偏差，全部可追溯到
`src/novelvideo/generators/prompt_builder.py` 中 `SketchModeStrategy` 的提示词组装方式：

| 编号 | 现象 | 根因 |
|---|---|---|
| P1 | b10 把巴掌大的手持木牌“寻迹牌”画成齐膝高石碑，渲染阶段只能给石碑上色 | 草图阶段刻意不附道具参考图（`_filter_panel_prop_asset_refs` 在 Sketch 模式返回空），道具文字设定也未进入提示词，道具行只剩名字 |
| P2 | b02、b12、b13 没有具名角色却画出人物 | 没有“本格无人物”的约束；全局规则默认“无名人物画成灰色人偶” |
| P3 | b01“黑场，画面全黑”被改成“场，画面全”，b11“画面切黑”变成“画面切” | `utils/text_utils.strip_color_words` 剥离一切含颜色字的词，连“黄果树”“白水河”也被削成“果树”“水河” |
| P4 | b13、b17、b25、b30 字幕卡被画成翻开的书或人群 | 没有黑场、字幕卡的专门处理；`_SHOT_CUE_VARIANTS` 虽定义了“黑屏”“空镜”但从未被使用 |
| P5 | 用户无法对单拍草图提示词做人工纠正 | 没有 beat 级草图提示词字段，只能改画面描述、姿态编辑器或上传草图 |

次要问题 P6：本集道具菜单的 `marker_color` 从未被分配，且每次重新规划道具都会整体覆盖菜单，标记色被清空。

## 2. 目标与非目标

目标：

1. 草图阶段拿到道具的类别、尺度、持握方式；道具特写镜头附带参考图。
2. 无具名角色的拍默认不画人；黑场、字幕卡按特殊面板处理，草图与渲染两阶段一致。
3. 颜色词剥离不再误伤镜头状态词、场景名、道具名。
4. 每拍可设置自定义草图提示词，支持追加与覆盖两种模式，并能预览最终面板文本。
5. 全局道具缺标记色时自动补齐；重新规划道具时保留已有标记色。
6. 判定逻辑集中在一个纯函数模块，可单测，为后续扩展（如跳过生图）留出接口。

非目标（本轮不做）：

- 黑场、字幕卡跳过图像模型、由程序合成帧。
- 在剧本工作流的 LLM 输出中增加“镜头种类”字段。
- 修改失败模式注册表（`verification/failure_registry.py`）。
- 项目级全局附加提示词、提示词历史版本、画布节点内的编辑器。
- 为有具名角色的面板附道具参考图；新增道具级“草图提示”字段。

## 3. 总体架构

```
beats(含 sketch_prompt / sketch_prompt_mode)
  + ctx.prop_asset_refs（AssetResolver 在草图模式已解析，含 text_description / image_paths）
  + ctx.characters / ctx.prop_marker_colors / ctx.scene_refs
        │
        ▼
generators/sketch_panel_brief.py :: build_panel_briefs(ctx) -> list[PanelBrief]
        │
        ├──► SketchModeStrategy.build        面板行、PANEL KIND RULES、道具 FORM 锚点
        ├──► PromptComponents.build_panel_roster（Render）  黑场 / 字幕卡面板文本替换
        ├──► PromptComponents.build_reference_image_plan    道具特写面板放行道具参考图
        └──► GET …/beats/{n}/sketch-brief     前端预览（与提交走同一函数）
```

策略类只负责把简报渲染进提示词，不再内嵌判定逻辑。

## 4. 组件设计

### 4.1 `src/novelvideo/generators/sketch_panel_brief.py`

纯函数模块，不访问存储与网络。

```python
@dataclass(frozen=True)
class PanelBrief:
    beat_number: int
    kind: Literal["normal", "black", "title_card", "prop_insert"]
    has_characters: bool
    allow_unnamed_people: bool
    description: str            # 处理后的面板文本（已解析道具标签、受保护剥色、解析身份标签、合并自定义提示词）
    prop_anchor_lines: list[str]  # 形如 "FORM: 横向不规则山形寻迹牌，约 7 到 8 厘米宽，单手可握"
    attach_prop_refs: bool      # 仅 prop_insert 为 True

def build_panel_briefs(ctx: PromptContext) -> list[PanelBrief]: ...
def build_panel_brief(beat: dict, *, panel_idx: int, ctx: PromptContext) -> PanelBrief: ...
```

判定顺序（基于剥色前的原始 `visual_description`）：

1. 黑场词命中 → `black`。关键词：`黑场`、`黑屏`、`画面全黑`、`切黑`、`画面切黑`、`【黑屏】`、`淡出至黑`、`全黑`。面板文本替换为固定英文指令：`SOLID BLACK PANEL: fill the entire panel with flat black. No scenery, no characters, no objects, no text.`
2. 字幕卡词命中 → `title_card`。关键词：`屏幕出现文字`、`字幕`、`片名`、`片尾`、`事实卡`、`来源字幕`、`标题卡`、`屏幕文字`。面板文本替换为：`TITLE CARD PANEL: a plain blank card on a neutral background. No scenery, no characters, no readable text.`
3. 无具名角色（无 `{{身份}}` 标记且 `real_detected_identities` 为空）且存在 `[[道具]]` 标记 → `prop_insert`。
4. 其余 → `normal`。

`has_characters`：SKETCH 模式下只读 `{{身份}}` 标记（不读 `detected_identities`，避免上一张误画的人物在重生成时自我强化）；其他模式为存在 `{{身份}}` 标记或 `real_detected_identities` 非空。

`allow_unnamed_people`：`has_characters` 为假且原始描述含人群词之一：`人群`、`路人`、`行人`、`游客`、`众人`、`人影`、`村民`、`士兵`、`孩子`、`围观`、`人们`。

文本处理链（`normal` 与 `prop_insert`，顺序与现状一致）：

1. `_resolve_prop_marker_tags`：`[[寻迹牌]]` → `寻迹牌 [XJP_885e]`。
2. `strip_color_words(text, protected_terms=...)`：保护词 = 默认镜头状态词 ∪ 本格场景名（`beat.scene_ref.scene_id` 与 `ctx.scene_refs[panel_idx]` 的 `base_id`）∪ 本格道具名（标记中的 prop_id）。
3. `resolve_visual_description_markers`：`{{身份}}` → 色标。
4. 去掉结尾标点（沿用现有 `rstrip("。！？，、；：")`）。

自定义提示词合并：

- `sketch_prompt_mode == "append"` 且 `sketch_prompt` 非空：`description = f"{description} | ADDITIONAL DIRECTION: {processed}"`，其中 `processed` 为 `sketch_prompt` 经过同一条处理链（第 1 到 4 步）并把空白折叠为单行后的结果。黑场与字幕卡面板同样追加。
- `sketch_prompt_mode == "override"` 且 `sketch_prompt` 非空：`description = sketch_prompt`（同样经过第 1 到 3 步处理，覆盖文本里的 `[[ ]]`、`{{ }}` 会被解析）；若自动判定为 `black` 或 `title_card`，`kind` 回退为 `normal`；`prop_insert` 的判定仍依据原始描述的标记。
- `has_characters`、`allow_unnamed_people`、`attach_prop_refs` 始终基于原始 `visual_description` 计算。

道具锚点（所有含 `[[道具]]` 的面板）：

- 读 `ctx.prop_asset_refs[panel_idx]` 中每个 `ResolvedAssetRef.text_description`（解析器已按“本集菜单描述 → 全局 visual_prompt → description → 名字”兜底）。
- 取第一句（按 `。`、`；`、`;`、换行切分），超过 80 字截断并补 `…`；再经受保护剥色去掉颜色词与色号。
- 若结果为空，退回 `prop_type` 的可读标签（artifact → 器物、weapon → 武器、document → 文件、accessory → 配饰、furniture → 家具、object → 物件）。
- 输出格式：`FORM: <锚点>`，按 prop_id 去重。

### 4.2 `src/novelvideo/utils/text_utils.py`

- 签名改为 `strip_color_words(text: str, protected_terms: Iterable[str] = ()) -> str`。
- 新增模块常量 `SCREEN_STATE_TERMS = ("黑场", "黑屏", "切黑", "全黑", "白场", "闪白", "淡入", "淡出")`，无论调用方是否传保护词都生效。
- 保护实现沿用现有占位符机制：先保护 `{{…}}`，再保护 `【…】` 片段、每个保护词的每次出现，剥色后按序还原。保护词按长度降序处理，避免短词先占位。
- 其它颜色词行为不变。更新 docstring 示例，新增 `黑场，画面全黑` → 原样、`黄果树主瀑布`（传入场景名保护）→ 原样的示例。
- 仅有的调用方是 `prompt_builder.py`，改为经简报调用。

### 4.3 `SketchModeStrategy.build` 的变化

- 面板循环改为遍历 `build_panel_briefs(ctx)`，不再内联处理文本。
- 面板行前缀按种类标注：`[SOLID BLACK]`、`[TITLE CARD]`、`[PROP INSERT]`、无具名角色且不允许无名人物时加 `[NO CHARACTERS]`；允许无名人物时加 `[UNNAMED PEOPLE ONLY]`。普通面板不加前缀。
- 道具行（全局 `GLOBAL TABLE PROP` 与本集 `LOCAL / EPISODE PROP`）末尾追加 ` — <FORM 锚点>`，保留现有前缀文字以兼容既有测试断言。
- 全局规则区新增 `PANEL KIND RULES` 段，说明四种前缀的含义：黑场纯黑；卡片空白无文字；`NO CHARACTERS` 面板不得出现任何人形、人影、人偶；`UNNAMED PEOPLE ONLY` 面板只允许灰色无名人偶；`PROP INSERT` 面板以道具为唯一主体，按 FORM 锚点和参考图把握轮廓与比例，面板内不得出现人物。
- 现有三处“无名人物画成灰色人偶”的措辞（COLOR LAW、RENDERING RULES、FINAL CHECKLIST）改为“仅当该格描述明确写到人时”。
- 场景几何豁免语句从“BLANK PLACEHOLDER”扩展为“BLANK PLACEHOLDER、SOLID BLACK、TITLE CARD”。
- 角色与道具出现面板映射（`tag_panels`、`prop_panels`）继续基于原始 `visual_description`，不受覆盖模式影响。

### 4.4 渲染阶段 `PromptComponents.build_panel_roster`

- 调用 `build_panel_briefs(ctx)`，对 `kind` 为 `black` 或 `title_card` 的面板，用简报的固定指令替换面板描述，并跳过场景锚点行。
- 其余面板行为不变。`build_single_beat_render_visual_reference` 同样对这两种面板输出固定指令而非原描述。

### 4.5 道具参考图放行（`build_reference_image_plan` 与说明文字）

- 去掉“Sketch 模式一律不附道具参考图”的硬规则，改为：Sketch 模式下仅收集 `attach_prop_refs` 为真的面板对应的道具引用；Render 模式行为不变。
- `_filter_panel_prop_asset_refs` 在 Sketch 模式改为按简报放行，而非一律返回空。
- `build_reference_map` 的道具条目文案按模式区分。Sketch 模式：`Image N = Prop "寻迹牌" shape reference for sketching: use it only for silhouette, proportions, scale, and how it is held. Draw it as black/gray line art; ignore material, color, and surface detail.` Render 模式保留现有措辞。
- 上传数量仍受 `collect_prop_image_refs(limit=6)` 约束。

### 4.6 每拍自定义草图提示词

数据层：

- `SQLiteStore._ensure_beat_current_columns` 新增 `sketch_prompt TEXT DEFAULT ''`、`sketch_prompt_mode TEXT DEFAULT 'append'`。
- `models.VisualBeat` 新增同名字段；`update_beat_asset` 新增两个关键字参数；`get_beats_as_dicts` 导出两字段；重写剧本会删除并重建全部 beat，`sketch_prompt` 随之清空；编辑单拍不影响。

接口层：

- `api/schemas.BeatUpdate` 新增 `sketch_prompt: Optional[str]`（最长 500 字）与 `sketch_prompt_mode: Optional[Literal["append", "override"]]`。
- `api/routes/scripts.update_beat` 的允许字段元组加入两字段。
- 新增 `GET /api/v1/projects/{project}/episodes/{episode_num}/beats/{beat_num}/sketch-brief`：以该拍为 1x1 网格构造 `PromptContext`（`character_map` 走 `_build_character_map`，道具引用走 `AssetResolver(scene_reference_kind="sketch")`，标记色走 `_runtime_prop_menu_with_global_props` + `_prop_marker_colors_from_menu`），返回 `{"ok": true, "data": {kind, has_characters, allow_unnamed_people, description, prop_anchor_lines, attach_prop_refs}}`。Beat 不存在时返回 `ok:false`，文案走 `lmsg`。

前端：

- `types/script.ts`、`types/episode.ts` 的 Beat 与 `lib/queries/scripts.ts` 的 BeatUpdate 新增可选字段 `sketch_prompt`、`sketch_prompt_mode`。
- `lib/queries/sketches.ts` 新增 `useSketchBrief(project, episode, beatNum)`，查询键 `queryKeys.sketchBrief(project, episode, beatNum)`，在 `useUpdateBeat` 成功后失效。
- `components/episode/beat-workbench/sketch-section.tsx` 在重生成按钮下方新增可折叠块 `SketchPromptEditor`（独立文件 `sketch-prompt-editor.tsx`）：文本框绑定 `sketch_prompt`，切换控件绑定 `sketch_prompt_mode`，保存走 `useUpdateBeat`；下方只读预览显示种类徽标与最终面板文本。
- 文案键：`episode.workbench.sketch.promptEditorTitle`、`promptEditorPlaceholder`、`promptModeAppend`、`promptModeOverride`、`promptPreviewLabel`、`promptKindNormal`、`promptKindBlack`、`promptKindTitleCard`、`promptKindPropInsert`、`promptKindNoCharacters`、`promptKindUnnamedPeople`、`promptSaved`、`promptSaveFailed`，中英 `translation.json` 同步。

### 4.7 标记色补齐与规划保留

- `api/routes/generation.py` 新增 `async def ensure_global_prop_marker_colors(store, episode_num, beats, prop_menu, sketch_colors) -> list[dict]`：调用 `_global_prop_marker_colors(beats, prop_menu=..., sketch_colors=..., assign_missing=True)`，把结果写入运行时菜单项的 `marker_color`，有变化时 `store.patch_episode(episode_num, prop_menu=...)`，返回更新后的菜单。
- `generate_sketches`、`regenerate_sketches` 在组装 `config["prop_menu"]` 前调用它；`assign_sketch_colors` 改为复用它。
- `AssetCompiler.compile_episode_props` 在 `_compile_props` 之前读取 `episode.prop_menu` 的 `{prop_id: marker_color}`，对新菜单中同名项回填，再 `_write_menus`。

## 5. 错误处理

- `build_panel_briefs` 对缺字段、非字符串、空描述一律按 `normal` 处理，不抛异常。
- `strip_color_words` 对 `None` 或空串原样返回。
- `sketch-brief` 接口：项目或拍不存在返回 `ok:false` 与 `lmsg` 文案；内部异常由现有全局错误处理兜底。
- 标记色写回失败只记日志，草图生成继续，与现有 `assign_sketch_colors` 一致。
- 道具参考图文件缺失时 `image_paths` 为空，参考图计划自然跳过，仅保留 FORM 锚点。

## 6. 测试计划

- `tests/test_sketch_panel_brief.py`：四种种类判定及优先级；`has_characters` 与 `allow_unnamed_people`；追加与覆盖合并；覆盖后 `kind` 回退；道具锚点首句截断与类型兜底；保护词传递。
- `tests/test_text_utils_color.py`：镜头状态词默认受保护；传入场景名、道具名受保护；`红色的长裙`、`惨白脸色` 仍被剥离；`None` 与空串透传。
- 扩展 `tests/test_storyboard_prompt_visual_authority.py`：面板前缀；`PANEL KIND RULES` 存在；道具行含 `FORM:`；`prop_insert` 面板的参考图计划含 `kind == "prop"` 而有角色面板不含；渲染 `build_panel_roster` 对黑场面板输出 `SOLID BLACK PANEL`。
- 路由测试（新增 `tests/test_api_sketch_brief.py` 与 `tests/test_api_prop_marker_colors.py`）：`sketch-brief` 接口返回结构；`BeatUpdate` 接受新字段并拒绝非法模式；草图生成路由自动补齐标记色并落库；`compile_episode_props` 重新规划保留标记色。
- 前端 `sketch-prompt-editor.test.tsx`：保存调用、模式切换、预览渲染，MSW 模拟 `sketch-brief`。
- 覆盖率目标沿用仓库要求（80% 以上）。

## 7. 验收

在 `xunjiren_1` 第 1 集重生成 b01、b02、b10、b11、b12、b13 草图：

| 拍 | 预期 |
|---|---|
| b01、b11 | 纯黑面板 |
| b02、b12 | 瀑布 / 山路，无任何人形 |
| b13 | 空白卡片，无文字 |
| b10 | 巴掌大的手持木牌挂件，参考图已附带（任务日志出现 `添加道具参考图: 寻迹牌`） |

再渲染 b10，确认成片中的寻迹牌与 `assets/props/寻迹牌/reference_3view.png` 形态一致。

## 8. 文档与门禁

- `docs/en/reference/sketch-panel-brief.md` 与 `docs/zh/reference/sketch-panel-brief.md`：面板种类、关键词、自定义提示词两种模式、预览的含义。
- 提交前跑：`uv run ruff check .`、`uv run pytest -n auto`、`uv lock --check`、`python3 scripts/check_backend_i18n.py`、`python3 scripts/check_frontend_i18n.py`、`python3 scripts/lint_banned_words.py`、`cd frontend && pnpm build && pnpm test`。
- 所有提交使用 `git commit -s`，遵循 `<type>: <description>`。

## 9. 涉及文件

后端：
- 新增 `src/novelvideo/generators/sketch_panel_brief.py`
- `src/novelvideo/generators/prompt_builder.py`（`SketchModeStrategy.build`、`build_panel_roster`、`build_single_beat_render_visual_reference`、`_filter_panel_prop_asset_refs`、`build_reference_image_plan`、`build_reference_map`）
- `src/novelvideo/utils/text_utils.py`
- `src/novelvideo/models.py`（`VisualBeat`）
- `src/novelvideo/sqlite_store.py`（列迁移、`update_beat_asset`、`get_beats_as_dicts`）
- `src/novelvideo/api/schemas.py`（`BeatUpdate`）
- `src/novelvideo/api/routes/scripts.py`（`update_beat`）
- `src/novelvideo/api/routes/generation.py`（`ensure_global_prop_marker_colors`、`generate_sketches`、`regenerate_sketches`、`assign_sketch_colors`、新增 `sketch-brief` 路由）
- `src/novelvideo/agents/asset_compiler.py`（`compile_episode_props`）

前端：
- `frontend/src/types/script.ts`、`frontend/src/types/episode.ts`
- `frontend/src/lib/queries/scripts.ts`、`frontend/src/lib/queries/sketches.ts`、`frontend/src/lib/query-keys.ts`
- 新增 `frontend/src/components/episode/beat-workbench/sketch-prompt-editor.tsx`
- `frontend/src/components/episode/beat-workbench/sketch-section.tsx`
- `frontend/public/locales/zh/translation.json`、`frontend/public/locales/en/translation.json`

测试与文档：
- 新增 `tests/test_sketch_panel_brief.py`、`tests/test_text_utils_color.py`、`frontend/src/__tests__/components/episode/beat-workbench/sketch-prompt-editor.test.tsx`
- 扩展 `tests/test_storyboard_prompt_visual_authority.py`；新增 `tests/test_api_sketch_brief.py`、`tests/test_api_prop_marker_colors.py`
- 新增 `docs/en/reference/sketch-panel-brief.md`、`docs/zh/reference/sketch-panel-brief.md`
