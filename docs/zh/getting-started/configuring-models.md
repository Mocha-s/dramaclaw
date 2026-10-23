<!-- lang-switch -->
[English](../../en/getting-started/configuring-models.md) · **简体中文**

# 配置模型

DramaClaw CE 通过官方网关或用户配置的第三方网关组调用文本、视觉理解、Embedding、图片、视频和音频模型。自定义组支持 OpenAI 兼容和 Gemini 兼容协议。模型设置保存在 CE 本地 `settings.db`；密钥仅以脱敏状态返回浏览器。

启动后打开 `http://localhost:8080`，进入 **设置 → 模型与渠道**。页面顶部的“当前生效”表示实际运行模式，不是当前正在查看的标签。

## 选择运行模式

| 模式 | 适用场景 | 需要配置的内容 |
|---|---|---|
| 官方 | 直接使用 RelayClaw（虾驿）提供的模型 | 只需 DC Key |
| 自定义 | 模型通过已配置的第三方网关组路由 | 协议、Base URL、组 API key、能力和逻辑模型映射 |
| 混合 | 保留官方模型，并将匹配模型路由到第三方网关组 | 官方 DC Key 和一个或多个第三方网关组 |

配置完成后点击对应模式的启用按钮。更换模式、Key 或模型后，新任务会读取新配置；正在运行的任务不会中途切换。

### 第三方网关的图片和视频请求格式

图片编辑请求格式由所选协议决定，不提供给操作员选择。OpenAI 兼容组使用已验证的
`images: [{"image_url": "..."}]` JSON 格式；Gemini 兼容组使用 Gemini 原生图片请求。
迁移期间仍会保留旧的图片格式值作为隐藏兼容数据。

视频模型默认走现代异步流程：`POST /videos`、`GET /videos/{id}`，必要时再从
`GET /videos/{id}/content` 下载结果。若网关只支持旧接口，可在对应模型映射中
选择 `/video/generations`。现代提交会带 `Idempotency-Key`；任务完成但没有直链时，
DramaClaw 会使用认证信息下载 content 接口。上游报错后不会自动换格式重发，避免
重复创建并重复计费。

模型目录能力会限制参考素材、时长和分辨率。例如 `sd17-seedance-2.5-2` 最多 30 张
参考图，时长 10–30 秒，分辨率为 720p。

如果第三方账号组的协议选择为 **Gemini**，图片模型会使用 Gemini 原生的
`POST /v1beta/models/{model}:generateContent`，不会走 OpenAI 兼容图片接口。
提示词和参考图放在 `contents[].parts[]` 中，本地参考图编码为 `inlineData`，
`generationConfig.imageConfig` 传递 `imageSize` 和 `aspectRatio`。Gemini 视频模型
不会因此切换到这套图片接口。

## Agent 模型

虾导 Agent 可以跟随当前模型渠道，也可以单独使用第三方服务。在 **Agent 模型** 中选择 **第三方**，填写兼容 OpenAI 的 Base URL、API Key 和模型名称。第三方服务必须支持 OpenAI Responses API 和工具调用。该配置只影响 Agent，图片、视频、音频、Embedding 和其他业务模型仍使用当前选择的模型渠道。

密钥只保存在 CE 本地设置数据库中，浏览器仅能看到脱敏预览。修改第三方地址时必须重新输入 API Key，避免已保存密钥被意外发送到另一个主机。选择 **跟随当前渠道** 即可恢复官方、自定义或混合模式原有的 Agent 路由。

## 官方模式

官方模式是最简单的接入方式：

1. 打开 **官方**。
2. 填写 RelayClaw DC Key。
3. 点击 **保存并启用**。

官方网关地址由 DramaClaw 固定管理。RelayClaw 已配置 `DC-*-LLM`、`DC-cognee-embedding` 和官方媒体模型，不需要在 CE 中填写上游模型映射。

官方媒体模型及其分辨率、比例、时长和参考素材能力来自 CE 内置的 `src/novelvideo/official_media_models.json`。

### 更新官方媒体模型列表

官方模式和本地 + 官方混合模式会显示当前官方模型列表的版本、模型数量和来源：

- 点击 **立即检查更新**，可以从 DramaClaw 官方发布地址获取最新模型列表并立即应用。
- **自动更新官方模型列表**默认关闭。开启后，后端默认每 5 分钟检查一次；打开对应设置面板时也会立即检查。
- 下载的模型列表保存在本地 `state/local/official_media_models.json`，重启后继续生效。
- DramaClaw 不会安装低于当前生效版本的远端列表。应用升级后，如果新版内置列表比本地缓存更新，会优先使用新版内置列表。
- 开启自动更新后，已打开的虾画浏览器每分钟观察一次目录状态；内容 SHA256 变化时会自动刷新图片和视频模型列表。
- 状态接口会返回当前内容的 SHA256、发布 Git revision、发布时间、远端地址和最近一次更新错误，便于确认每个实例实际使用的版本。

用户在自定义模式中维护的渠道、模型映射和能力配置不受官方模型列表更新影响。

官方目录默认使用成都地域的 `dramaclaw-dl` Bucket：`https://dramaclaw-dl.oss-cn-chengdu.aliyuncs.com/official-media-catalog/manifest.json`。manifest 指向按 SHA256 命名、永不覆盖的目录快照；后端会校验 manifest、目录版本和内容 SHA256，并使用 ETag 检查更新。可通过 `OFFICIAL_MEDIA_CATALOG_MANIFEST_URL` 覆盖默认地址；`OFFICIAL_MEDIA_CATALOG_URL` 是兼容旧部署的直接 JSON 地址。轮询间隔可通过 `OFFICIAL_MEDIA_CATALOG_POLL_SECONDS` 调整，最低为 60 秒。

仓库的 `publish-official-media-catalog` 工作流负责发布：先上传带长期不可变缓存头的 `catalogs/<sha256>.json`，最后上传缓存 60 秒的 `manifest.json`。以下密钥既可配置为仓库级 Secrets，也可配置在 GitHub `official-media-catalog` environment 中：

- Variables 可选：默认使用 `oss-cn-chengdu.aliyuncs.com`、`dramaclaw-dl` 和 `official-media-catalog`；可用 `OFFICIAL_CATALOG_OSS_ENDPOINT`、`OFFICIAL_CATALOG_OSS_BUCKET`、`OFFICIAL_CATALOG_OSS_PREFIX` 覆盖。
- Secrets：优先使用 `OFFICIAL_CATALOG_OSS_ACCESS_KEY_ID`、`OFFICIAL_CATALOG_OSS_ACCESS_KEY_SECRET`；未配置时复用组织级 `OSS_RELAY_AK`、`OSS_RELAY_SK`。

`dramaclaw-dl` Bucket 本身保持私有，只对 `official-media-catalog/*` 前缀授予匿名 `GetObject`，CI 身份仅需该前缀的写权限。模型目录仍以 Git PR 为唯一内容源；建议开启 Bucket 版本控制作为基础设施灾备。

还没有 DC Key 时，可前往 <https://api.aigcdo.top> 注册或购买。

## 自定义模式

自定义模式使用一个或多个用户配置的第三方网关组。执行 `docker compose up -d` 后，CE Compose 只启动 `api` 和 `web`。

### 配置第三方网关组

在**自定义**中添加网关组，填写从 `api` 容器可访问的 Base URL、该组自己的 API key，并明确选择 **OpenAI 兼容**或 **Gemini 兼容**协议。选择文本、视觉、Embedding、图片、视频或音频能力，再把 DramaClaw 的逻辑模型 ID 映射到上游模型 ID。密钥保存在 CE 设置数据库中，浏览器只显示脱敏状态。

已保存的网关组默认折叠，可分别展开编辑。旧版 `sub2api_*` 设置会自动迁移；规范的第三方组写入成功后，旧设置仍会保留以便回滚。如果发现本地或不完整的地址，迁移会将其保持为不可用状态并显示脱敏警告，不会向不确定的地址发送密钥。

OpenAI 兼容组在支持时可通过 `/v1/models` 发现模型；Gemini 兼容图片请求使用原生 `generateContent` 接口。网关不提供模型列表时仍可手动输入。逻辑模型映射由应用管理；外部网关负责自己的上游账户和供应商配置。

NewAPI 专用的管理员 CRUD、供应商渠道目录、渠道类型同步和 root 初始化不具备通用性，CE 不会执行这些操作。请直接在选定的外部网关中重建上游账户。旧设置和已有 `newapi-data` 卷会保留用于迁移或回滚，但不会作为内置服务使用。

### 业务与媒体模型

保留 `DC-character-builder-LLM`、`DC-scene-builder-LLM`、`DC-freezone-vision-LLM` 等稳定逻辑名称，并映射到合适的上游模型。文本功能需要文本模型，视觉功能需要多模态模型，Embedding 需要匹配的模型和维度，媒体模型需要对应的图片、视频或音频能力。编辑后保存映射；上游失败不会自动换用另一份凭据。

ComfyUI 仍可作为独立外部供应商使用：在所选第三方网关中配置可访问的服务地址和 Workflow，再在 DramaClaw 中添加对应视频网关组和模型映射。容器内的 `127.0.0.1` 不是宿主机地址，请使用 `api` 容器可访问的宿主机或局域网地址。

## 混合模式

混合模式保留官方 RelayClaw，同时为匹配的能力或模型 ID 选择已配置的第三方网关组。保存官方 DC key，添加至少一个有效的外部组，完成逻辑模型映射后启用混合模式。精确且最具体的无歧义映射优先；没有匹配时使用官方网关。运行时失败不会自动换用另一份凭据；映射有歧义时会拒绝，而不会随意选择凭据。

## 参考媒体存储

图生图、视频首帧、首尾帧、参考图片和身份图等功能需要让上游模型读取本地文件。进入 **设置 → 媒体存储**，配置公网可访问的临时媒体 relay。

### 阿里云 OSS

需要 Bucket 和拥有该 Bucket 读写权限的 AccessKey。推荐使用只授权该 Bucket 的 RAM 子账号。

| 网页字段 | 环境变量 | 示例或说明 |
|---|---|---|
| Endpoint | `OSS_RELAY_ENDPOINT` | `oss-cn-chengdu.aliyuncs.com`，不要带 `https://` |
| Bucket | `OSS_RELAY_BUCKET` | 临时媒体 Bucket 名称 |
| AccessKey ID | `OSS_RELAY_AK` | Bucket 有限权限的 AK |
| AccessKey Secret | `OSS_RELAY_SK` | 对应 SK |
| 有效期 | `MEDIA_RELAY_TTL_SECONDS` | 默认 1800 秒 |

### 自部署 MinIO

在「设置 → 媒体存储」选择 MinIO，填写 API 容器可访问的 S3 `Endpoint`、bucket 和凭据，以及上游模型可访问的公网 HTTPS `Public Endpoint`。两种 endpoint 可经由同一个反向代理，也可分别使用内网地址和公网地址。凭据仅保存在服务端，不返回给浏览器。

Bucket 无需公开读；DramaClaw 使用临时签名 URL 授权上游读取。

### Cloudinary

填写 Cloud name、API Key、API Secret 和可选文件夹。可在 Cloudinary 控制台的 **Product environment settings → API Keys** 查看这些值。保存后本地数据库配置优先于环境变量，完整密钥不会返回前端。

## 常见问题

| 现象 | 检查方法 |
|---|---|
| 保存 Key 后高级配置仍没有“已保存”标记 | Key 可能只存在于页面草稿。重新保存对应渠道或重新应用完整配置，并确认使用的是包含最新代码的镜像。 |
| 添加媒体模型时提示缺少供应商 Key | 检查外部网关组的 Base URL、协议、API key 和所需媒体能力；确认 `api` 容器可以访问该网关。 |
| 模型报 `No available model ...` | 检查应用中的逻辑模型映射、外部网关能力和上游模型 ID。 |
| 走 Codex 类中转站（Codex2API 等）时结构化环节报 `Exceeded maximum output retries` | 中转站可能在 `/v1/chat/completions` 上丢掉 `tool_calls`。检查所选外部网关的兼容选项；如支持，开启 Responses 兼容模式。详见[排错指南](../guides/troubleshooting.md#模型--网关类)。 |
| 虾画没有显示新增模型 | 确认模型已启用、媒体类型正确、已保存全部配置并刷新页面。 |
| 模型控件与实际能力不一致 | 检查媒体模型的 `config`，尤其是分辨率、比例、模式和参考素材上限。 |
| 知识图谱 embedding 失败 | 检查 embedding Key、上游模型、维度和批量大小；429 表示上游限流。 |
| 参考图或首帧无法读取 | 检查媒体存储配置和临时 URL 是否能被上游公网访问。 |
| 混合模式本地视频失败后没有走官方 | 这是预期行为；混合模式不做自动失败回退。 |
| ComfyUI 无法连接 `127.0.0.1:8188` | `127.0.0.1` 指 DramaClaw 后端所在环境。容器或远程部署时改为后端可访问的宿主机名或局域网地址。 |
| MiniMax H3 Workflow 执行时报节点或模型缺失 | 确认 ComfyUI 已安装推荐 Workflow 使用的自定义节点和模型文件，并按本机安装情况修改 Workflow。 |

## 相关文件

- `src/novelvideo/official_media_models.json`：CE 官方媒体模型与能力。
- `.env.example`：环境变量参考。
- `docker-compose.yml`（源码构建）/ `docker-compose.release.yml`（镜像）：CE 双服务部署（api + web）；在设置页配置外部网关组。
- [自托管手册](../guides/self-hosting.md)
- [环境变量参考](../reference/environment-variables.md)
