# 虾集能力模型一次性配置设计

## 意图

让用户只需配置第三方网关组中的真实上游模型，不再为每个虾集功能填写
`DC-* -> upstreamModel` 映射。前端只展示业务能力和真实模型；后端根据固定的
功能能力定义自动路由。

## 当前虾集模型需求

当前 `FEATURE_MODEL_PRODUCT_GROUPS.xiahua` 包含 6 个功能：

| 功能 | 能力 | 是否必需 |
|---|---|---|
| 翻译 | text | 使用翻译时必需 |
| 文本写作 | text | 虾集脚本/文本任务必需 |
| 剧本创作 | text | 剧本创作必需 |
| Recipe 编译 | text | 使用 Recipe 时必需 |
| 视觉理解 | text | 使用图片理解/视觉任务时必需；文本网关默认支持视觉 |
| 道具规划 | text | 使用道具规划时必需 |

整个主线工作流的文本和视觉理解功能统一属于 `text` 能力；Embedding 是独立
能力，不计入文本模型。图片、视频、音频模型由各自媒体目录管理。

## 一次性前端配置

高级自定义中不再展示供应商渠道编辑器，也不再调用 `/custom/newapi/*`。
改为展示一个能力默认模型面板：

1. **文本模型**：从已配置 `text` 网关组的模型列表选择一个默认模型。
2. **Embedding 模型**：选择模型并配置维度、批量大小。
3. **图片/视频/音频**：继续使用第三方媒体组和媒体目录，不复制一套渠道配置。

用户不需要看到功能级 `DC-*` 名称，也不需要逐项保存 24 个映射。

第三方组的协议选择统一支持：

| 协议 | 请求方式 | 鉴权/接口 | 适用模型 |
|---|---|---|---|
| OpenAI | OpenAI-compatible | `Authorization: Bearer`，`/models` | GPT、Qwen、DeepSeek 等兼容网关 |
| Gemini | Gemini native | `x-goog-api-key`，Gemini models API | Gemini/Nano Banana |
| Anthropic | Claude native | `x-api-key`、`anthropic-version`，Models/Messages API | Claude |

Claude 组不能只把协议标签改成 OpenAI：模型列表、请求头、Messages 请求体和响应解析
必须走 Anthropic 专用适配器；配置中的 Base URL 仍由用户提供，默认官方地址为
`https://api.anthropic.com`。

协议下拉使用项目现有 Radix `Select` 组件（`SelectTrigger`、`SelectContent`、
`SelectItem`），不使用原生 `<select>`，保证暗色主题、尺寸、焦点态和菜单样式统一。

## 后端路由

`FEATURE_MODEL_GROUPS` 改为稳定的 `featureId -> capability` 定义；例如：

```text
FREEZONE_STORY_SCRIPT -> text
EPISODE_PROP_PLANNER -> text
FREEZONE_VISION      -> text
STYLE_ANALYZER       -> text
```

运行时按以下顺序选择：

1. 若功能有明确的显式覆盖，使用覆盖模型；
2. 使用该能力配置的默认上游模型；
3. 若能力没有独立默认但存在唯一兼容组，使用该组；
4. 没有可用能力组时，在任务开始前返回“请先配置文本/视觉/Embedding 模型”，
   不再把 `DC-*` 发给上游。

旧的 `DC-*` 值保留为读取兼容别名，自动转换为 `featureId` 或能力默认模型，
不再作为新的保存格式。

## 能力组要求

- text：虾集文本和视觉任务的最低配置；当前可复用 gpt 或 claude 组。
- embedding：只有启用小说导入、检索或向量功能时要求配置。
- image/video/audio：生成对应媒体前必须有对应媒体组和模型目录条目。

当前已配置的第三方组应按协议和能力分类展示，而不是按旧的 NewAPI provider
channel 展示。Claude 组使用 `anthropic` 协议后，仍可作为 `text` 组供虾集文本和
视觉任务复用。

## 非目标

- 不删除旧数据库中的 `DC-*` 字符串。
- 不恢复 NewAPI 管理接口或本地 NewAPI channel CRUD。
- 不把所有能力强行合并到一个网关组。
- 不在未配置官方网关时重新显示官方内置媒体模型。

## 方案取舍

- **采用：能力默认模型 + 旧别名兼容**。用户配置一次，覆盖所有功能，且保留
  旧项目可运行性。
- 彻底删除 `DC-*` 会破坏旧画布、项目配置和历史任务，不采用。
- 仅隐藏 `DC-*` 但保留功能级映射，会继续产生未映射 404，不采用。
