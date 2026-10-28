# 媒体生成可靠性与运行时队列控制设计

**日期：** 2026-10-27
**状态：** 已实施，待 provider-dependent verification
**范围：** 方案 A 分阶段实施

## 目标

让 360 全景、虾画图片参考、虾集视频任务和 AI 视频优化具备可追踪的真实状态；同时让图片/视频模型参数和任务队列限制通过设置页实时配置，而不是依赖隐藏的硬编码或重启环境变量。

## 当前证据

- 360 生成可以收到 `master.png`、`reverse_master.png` 和 topology 参考，但最近一次产物的 overlap analysis 与 spatial contract 为空；提示词因此缺少空间合同。
- 最近图片任务 `c761539633264a08` 已完成，画布有两条上传图片边连入生成节点，两张文件均存在；最终历史没有保存参考数量、哈希或 provider 请求协议。
- 该图片任务的最终 prompt 中完整 Portrait prompt 出现两次，说明上游文本与节点 prompt 被重复拼接。
- NewAPI 视频主路径默认使用 1800 秒 HTTP timeout、360 次轮询；已观察到的失败分别是 provider 终态失败和网关连接失败，不是明确的轮询超时。
- 视频生成在 provider 完成后还要经过归档、下载和本地落盘；这些交付失败目前会把整体任务显示成失败。
- CE 当前全局 worker 默认值为 `default=8 / video=2 / world=1 / ffmpeg=1`，但项目/用户有效限制仍可能造成默认 3 或 video 1 的隐藏瓶颈；Inline backend 只在启动时读取环境变量。
- 现有媒体目录已经支持 `resolutionOptions`、`qualityOptions` 和 `request.parameters`；前端目前会隐藏 `thinking_level`，需要改变这一边界。

## 目标与非目标

### 目标

1. 360 双参考生成必须有新鲜、可验证的空间合同，或明确失败并说明原因。
2. 图片请求记录脱敏的参考图与 wire-protocol 证据，能区分“未传参考”和“模型收到但重绘”。
3. 修复重复 prompt，避免同一段上游文本重复进入生成请求。
4. 把视频 provider 状态与本地交付状态分离，并提供独立的轮询、归档、下载超时。
5. 图片/视频模型的思考等级、质量和比例由目录声明并显示在节点控制中；虾集图片生成统一提供 1K/2K/4K，视频生成统一提供 720p/768p/1080p/2K/4K，由上游决定模型是否支持。
6. AI 优化支持逐 Beat 重试和部分成功结果，不因单个 Beat 失败丢失已成功结果。
7. 队列的全局并发、等待队列、项目上限和单用户上限按队列类型实时配置。

### 非目标

- 不强制所有模型支持 1080p；上游不支持时不显示该选项。
- 不绕过组织/项目/用户授权和计费边界。
- 不把 provider API key、签名 URL、完整 multipart 内容或原始敏感请求写入日志。
- 不取消已经运行的任务；队列配置降低后只影响后续启动和排队任务。
- 不在本阶段重写所有图片/视频 provider 适配器。

## 方案选择

### 方案 A：分阶段修复（选定）

先在现有链路上补证据、状态和参数契约，再增加运行时队列配置。优点是兼容已有模型目录、任务状态和 settings.db；风险较低，能够逐阶段部署和回滚。

### 方案 B：最小热修

只修 prompt 去重、视频交付提示和若干 1080p 配置。实现快，但无法证明参考图是否进入 provider wire payload，也不能满足实时队列配置。

### 方案 C：重写统一媒体执行层

把图片、视频、360 和交付统一到新的媒体状态机。长期结构更简单，但会同时影响计费、组织出网、任务状态和多种 provider，当前风险过高。

## 设计

### 1. 360 空间合同与参考证据

- `run_scene_360()` 在 `master + reverse` 模式下检查：
  - overlap analysis 存在且不早于两张输入图；
  - spatial contract 存在、schema 正确，且不早于 overlap analysis；
  - 两个文件均来自当前输入图版本。
- 默认启用双参考严格模式；缺少有效合同且分析网关不可用时，任务返回稳定错误码 `SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE`，不再静默生成缺少空间约束的全景。
- `scene_360_manifest.json` 增加脱敏字段：输入文件 SHA256、尺寸、参考数量、分析状态、合同状态、prompt 中合同标记、provider/model/request id。
- 生成器只保存 prompt 摘要和 SHA256，不保存 API key、签名 URL 或完整 provider payload。
- 生成结果必须仍是 2:1，并保留 topology、safe seam 和 viewer correction 信息。

### 2. 图片参考与 prompt 去重

- 继续使用前端 `orderedReferenceUrls` 作为唯一顺序源；后端按同一顺序解析文件。
- 生成历史增加：
  - `reference_count`；
  - `reference_sha256`；
  - `reference_protocol`；
  - `request_path`；
  - `provider_request_id`。
- 这些字段只包含哈希、数量、协议名和路径类别，不包含图片内容、Key 或 URL token。
- prompt 编译增加归一化去重：上游文本与节点 prompt 相同、或节点 prompt 已包含上游完整文本时，只保留一份。
- `_call_newapi_image_api()` 在发送前生成安全摘要，明确记录 `image`、`images`、`input_reference` 或 multipart 的参考数量。
- 不改变现有 catalog 的 `referenceFormat` 选择；先用证据确认具体网关协议，再针对不匹配的模型配置修复。

### 3. 视频 provider 与交付状态

定义三个内部阶段：

```text
provider_pending → provider_completed → delivery_pending → completed
                                      └→ delivery_failed
provider_failed
```

- provider 已完成后立即确认 provider 计费，不因本地交付失败退款或伪装成 provider 失败。
- 归档等待、下载、写盘分别记录稳定错误码和重试次数。
- 配置独立参数：
  - `ST_VIDEO_PROVIDER_TIMEOUT_SECONDS`；
  - `ST_VIDEO_DELIVERY_TIMEOUT_SECONDS`；
  - `ST_VIDEO_POLL_INTERVAL_SECONDS`。
- 默认行为保持约 30 分钟 provider 等待，但交付阶段拥有独立重试窗口。
- 任务结果和历史记录同时保留 `provider_task_id`、`provider_status`、`delivery_status`。
- 只有本地输出文件存在且可读时，任务才进入 `completed`；provider 已成功但无法交付时显示可重试的交付失败，而不是生成失败。

### 4. 图片/视频模型参数目录

- 继续使用 `MediaModelRequestSchema.parameters` 作为唯一参数协议。
- `thinking_level` 不再被前端无条件隐藏；只有目录声明为用户可选参数时才显示。
- 图片和视频节点统一显示：
  - thinking/reasoning level；
  - quality；
  - ratio；
  - resolution。
- 参数变化必须随 `model_id` 和 `gen_mode` 重新过滤；切换模型后不能沿用旧模型选项。
- 后端最终请求前再次按 catalog schema 校验并移除未知参数。
- 虾集 generation 档位不由 catalog `resolutionOptions` 过滤；其他模型与非-generation 路径仍沿用各自目录或功能声明。

### 5. AI 视频优化容错

- 每个 Beat 最多自动重试两次，使用短指数退避。
- 单个 Beat 失败写入任务日志和 `failed_beats`，继续处理后续 Beat。
- `updated_count > 0` 时任务为部分成功，并返回成功/失败数量；`updated_count == 0` 才为任务失败。
- 失败结果不得覆盖已经成功保存的 Beat prompt。
- 保留现有 billing 数量口径，不因重试重复计费；重试只在原始调用的失败/未接受阶段发生。

### 6. 实时队列配置

新增受权限保护的运行时配置接口：

```text
GET  /api/v1/config/task-limits
PUT  /api/v1/config/task-limits
```

配置按 `default/video/world/ffmpeg` 保存到 CE 的 `settings.db.runtime_settings`，键名统一为 `task_limits.v1`。接口返回当前生效值和默认值，不返回环境中的秘密。

每个队列配置包含：

- `global_concurrency`：全局 worker 数；
- `global_queue_limit`：等待数量；
- `project_active_limit`：项目总活动数；
- `project_user_active_limit`：单用户活动数。

安全范围：

- global concurrency：1–32；
- global queue limit：1–4096；
- project/user active limit：1–256；
- `null`/无限制不作为默认值，避免配置错误导致资源失控。

运行时行为：

- 每次入队读取当前配置；
- 配置增大时新任务立即可使用新增容量；
- 配置减小时不取消运行中任务，当前 worker 自然收缩，后续任务按新值排队；
- 旧环境变量继续作为没有 settings.db 配置时的兼容 fallback；
- 默认项目/用户限制不再隐含固定的 3 个并发，推荐默认值与项目 lane 上限一致，并由全局 lane 做最终资源保护。

前端在 Settings 增加“任务与队列”页签，展示每个队列四个数字输入、当前活动/排队快照和保存结果；保存接口必须复用现有设置权限边界。

## 接口与兼容性

- 旧客户端不发送新参数时，继续使用目录默认值。
- 旧环境变量配置继续生效，但 settings.db 的显式配置优先。
- 旧任务状态读取保持兼容；新增字段使用可选字段，不修改已有历史 JSONL 的必填结构。
- 旧 provider 没有 thinking 声明时，前端不显示对应选项；虾集 generation 分辨率按产品档位显示，不因目录缺少某一档而隐藏，unsupported 错误由上游返回。
- 视频 provider 已完成但交付失败的历史任务保留旧 `failed` 可读性，同时新增 `provider_completed` 和 `delivery_status` 字段供新前端使用。

## 安全、数据与回滚

- 队列配置接口必须有管理权限，不能由普通项目编辑者修改全局资源上限。
- 所有参考图审计只保存 SHA256、数量、尺寸和协议元数据。
- 不保存原始 API headers、授权 URL 或完整图片 payload。
- `task_limits.v1` 可删除以回退到环境变量/代码默认值。
- 新的视频交付状态字段是向后兼容的；若新交付重试逻辑异常，可关闭新 retry 配置并回到当前失败行为。
- 360 严格合同模式必须提供兼容开关，必要时可临时回退到旧的“允许生成但记录缺合同”行为；默认不建议回退。

## 分阶段验收标准

### 阶段 1：证据与 360/图片

- 双参考 360 缺少新鲜合同时可稳定失败并返回明确错误码。
- 有效合同会进入 builder 命令、prompt 和 manifest。
- 两张参考图生成请求的历史记录包含 count、hash、protocol 和 request id。
- 相同 prompt 不会在最终请求中重复出现。

### 阶段 2：视频交付

- provider 返回 completed、下载失败时任务显示 provider completed + delivery pending/failed。
- delivery retry 不会重复提交 provider 任务。
- provider 连接失败、provider 终态失败和本地交付失败能被区分。

### 阶段 3：模型参数

- catalog 声明的 thinking level 会出现在图片/视频节点菜单。
- 虾集图片 generation 显示 1K/2K/4K，视频 generation 显示 720p/768p/1080p/2K/4K；不支持的档位可提交并由上游拒绝。
- 切换模型后旧参数不会错误带入新模型。

### 阶段 4：AI 优化

- 单个 Beat 失败不会阻止其他 Beat 保存。
- 部分成功结果显示成功数和失败数。
- 全部失败才将任务标记为 failed。

### 阶段 5：实时队列

- 修改四类队列配置后，新入队任务无需重启即可使用新值。
- 降低限制不取消运行中任务。
- 项目、单用户、全局和等待队列限制分别产生可识别错误和日志。
- 未授权请求不能修改队列配置。

## 2026-10-28 验证记录

### 已验证

- 阶段 1：`tests/test_p0g4l_scene_360_subprocess_egress.py`、`tests/test_newapi_image_gateway.py`、`tests/test_freezone_image_backend.py`、`tests/test_media_reference_audit.py` 通过；双参考 360 缺合同默认返回 `SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE`，兼容回退由显式环境变量控制；图片请求历史只保存数量、SHA256、尺寸、协议、路径类别和 provider request id。
- 阶段 2：`tests/test_video_archive_delivery.py`、`tests/test_seedance2_request.py` 通过；provider completed、delivery pending/failed、terminal provider failure 已区分，delivery retry 不重新提交 provider 任务。
- 阶段 3：`tests/test_media_model_request_schema.py`、`tests/test_freezone_video_backend.py` 及对应 Vitest 通过；虾集图片统一显示 1K/2K/4K，虾集视频统一显示 720p/768p/1080p/2K/4K，模型不支持的档位交由上游返回错误；thinking_level 仅在 catalog 标记 `userSelectable` 时可见和提交，模型/模式切换会清理旧参数。
- 阶段 4：`tests/test_global_video_optimizer_retries.py` 和生命周期回归通过；每个 Beat 最多三次调用，部分成功保留成功 Beat，失败记录只包含 Beat、attempts、稳定错误码和脱敏消息。
- 阶段 5：`tests/test_task_backend_limits.py`、`tests/test_runtime_task_limits_api.py`、`tests/contract/test_l014_inline_task_backend_concurrency.py` 通过；Settings UI 的四类队列控件和 live snapshot Vitest 通过，未授权读写由 API 测试覆盖。

### 计划 focused evidence

- Backend focused: 135 tests passed。
- Frontend focused: 215 files / 1846 tests passed。
- Repository `uv run pytest`: **7313 passed, 31 skipped, 3 deselected, 0 failed** (440.42s; 835 warnings, primarily existing framework deprecations).
- Focused backend: **135 passed**. Focused compatibility/compliance regression set: **67 passed, 3 skipped**.
- Focused frontend: **215 files / 1846 tests passed**; `tsc -b` passed.
- `tests/test_env_config_ratchet.py`: **10 passed**. P0-B license inventory/compliance tests are included in the full suite and pass after regenerating the inventory/SBOM.
- Ruff on touched Python files, Python `compileall`, `git diff --check`, and runtime task-limit unauthorized read/write tests passed.
- `git diff --check`, TypeScript build, focused Ruff checks, and changed-file Python compilation passed.

### Remaining manual/provider checks

- Run one authorized real provider request per supported虾集 image/video model to confirm the upstream acceptance/error wording for 1K/2K/4K and 720p/768p/1080p/2K/4K.
- Confirm provider archive/download behavior for each EE delivery adapter and inspect production usage records for `provider_completed`, `delivery_pending`, `delivery_failed`, and `completed`.
- Do not place API keys, signed URLs, raw multipart bodies, or provider response bodies in test logs or history.

### Scope alignment

- The implementation keeps the existing provider adapters and settings.db architecture; it does not rewrite providers or cancel running tasks.
- The虾集 resolution override is intentionally limited to generation image/video paths. Video upscale, compose/export, and other non-generation resolution selectors retain their existing catalog/feature-specific behavior.
- Verification-driven compatibility alignment: `_run_inline` accepts the prior two-argument direct-call seam while scheduled lane work continues passing its captured executor; the candidate 360 fixture explicitly opts into degraded mode because it uses non-image placeholder bytes; geometry assertions now check intermediate derived dimensions and the dimension-free final wire contract. `.env.example` and generated license/SBOM evidence were aligned with tracked runtime settings and files.

## 影响面与验证

预计涉及：

- `scene_360_builder.py`、`stage_asset_tasks.py`、360/场景测试；
- `nanobanana_grid.py`、Freezone image routes/jobs、generation history；
- `video_generator.py`、Freezone video runner/jobs、video usage records；
- `media_model_request_schema.py`、前端 `ops.ts`、图片/视频节点参数组件；
- `task_backend/limits.py`、`ports/local/tasks.py`、`task_state.py`、settings routes/dialog；
- 对应 Python contract tests、backend tests、Vitest settings/canvas tests。

验证命令分阶段执行：

```bash
uv run pytest tests/test_p0g4l_scene_360_subprocess_egress.py tests/test_newapi_image_gateway.py tests/test_task_backend_limits.py tests/contract/test_l014_inline_task_backend_concurrency.py -q
pnpm --dir frontend exec vitest run src/__tests__/features/canvas src/__tests__/components/settings
uv run pytest
```

真实 provider 请求只使用用户明确授权的测试请求；测试日志必须脱敏，不能把 key、签名 URL 或完整参考图 payload 写入仓库。
