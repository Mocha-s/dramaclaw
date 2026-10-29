# 媒体回归与项目风格继承修复设计

**日期：** 2026-10-28
**状态：** 已实施，待真实 provider 验证

## 意图

修复最新部署中暴露的四类问题：360 空间分析模型路由 404、360 生成结果偏离项目风格、虾集主线 render 缺少图片质量和视频分辨率参数；同时让视频 provider 账户不可用时显示准确的外部依赖错误。

## 目标

1. `DC-scene-overlap-analyzer-LLM` 和 `DC-scene-spatial-contract-LLM` 能通过当前有效 gateway 配置完成分析；路由缺失时给出可诊断错误，不静默生成。
2. 360 prompt 继承项目 `visual_style` 与对应 style preset。空间合同只约束几何、拓扑、物体位置和拼接，不写死 realistic、photographic 或其他具体画风。
3. 虾集主线 render 的图片质量和 Beat 视频生成分辨率从项目设置/前端选择器进入 render plan、任务 payload、worker 和 provider billing/request；视频合成/导出分辨率保持现有路径。
4. 视频 provider 返回 `503 account unavailable` 时保留 provider-unavailable 语义，不误报为本地交付或普通生成失败。

## 非目标

- 不把 360 统一改成摄影写实。
- 不覆盖项目已有的插画、国风、动画或其他 style preset。
- 不把视频合成/导出分辨率与 Beat 视频生成分辨率混为一个设置。
- 不绕过严格空间合同；分析失败仍应阻断双参考 360，并保留明确错误码。
- 不自动重试收费的视频 provider submit。
- 不修改用户的 gateway key 或现有数据卷内容。

## 方案

### 方案 A：能力路由 + 项目风格继承 + 主线质量闭环（采用）

- 分析模型先按逻辑 alias 查找当前 gateway；若没有精确 alias，只使用显式配置的 `SCENE_ANALYSIS_FALLBACK_MODEL`，并把实际 upstream model 记录到脱敏日志；不再隐式复用当前已返回 404 的 generic text route。
- 360 只增加风格继承/防漂移规则：`visual_style` 由项目决定，空间合同不得覆盖它。
- RenderSettings、RenderPlan 请求/执行、前端控件和 worker 统一使用 `image_quality`；Beat 视频生成使用已有 catalog/backend `resolutionOptions` 和 `resolution` 字段。
- 对 provider 503 做稳定分类和前端可读提示。

优点：修复完整、保留项目创作控制，失败边界清晰。代价：涉及后端 schema、gateway 路由、worker 和前端 render 设置。

### 方案 B：只补 gateway 映射和质量字段

不调整 360 prompt。实现较小，但无法修复项目风格漂移。

### 方案 C：分析失败兼容降级

允许没有空间合同时继续生成。短期减少失败，但会重新引入无拓扑约束的 360 产物，不符合当前严格合同目标。

## 验收

- 分析模型路由缺失时测试能识别 404/缺映射；有效视觉模型映射时分析任务可以继续。
- 项目风格为不同 preset 时，生成 prompt 包含对应 preset，不包含固定 realistic/photographic 断言；空间合同只增加空间约束。
- RenderSettings API、RenderPlan API、前端设置控件和 worker 测试都能保留 `low/medium/high` 图片质量值，并保留视频 `720p/768p/1080p/2K/4K` 分辨率值到单 Beat 视频提交路径。
- provider 503 account unavailable 被记录为 provider-unavailable；现有任务状态和计费边界保持兼容。
- 相关 Python/Vitest 测试通过，部署后 API/web health 通过。

## 回滚

回滚到部署前镜像即可；不删除 `ce-data`，不修改用户 gateway 配置。严格空间合同保持默认开启，必要时仍使用既有显式兼容开关。

## 2026-10-28 验证记录

- Scene analysis/style focused backend: 38 tests passed.
- Render quality focused backend: 33 tests passed; focused frontend render settings/plan: 14 tests passed; TypeScript build passed.
- Beat video resolution/provider focused backend: 204 tests passed; video-pane suite: 65 tests passed.
- Provider account-unavailable regression: 21 video archive/processing/provider tests passed.
- Full backend suite: **7331 passed, 31 skipped, 3 deselected**.
- Frontend focused suite: **216 files / 1849 tests passed**.
- `git diff --check`, locale JSON parsing, Python compilation, and focused Ruff checks passed. Existing unrelated Ruff findings remain in `tests/test_model_gateway_settings.py` (unused legacy imports/E402).
- No paid provider request was issued during verification.
- Deployment verification: API image `sha256:9d035a3c81255a59ef07b8d2081937b54b9e7813148849d7f74524c64bc9fd55`, web image `sha256:c7a31d96f672ef3e286a9e918f66eaaaf7873410a5408db2361f656d3bd033a1`; API health is healthy and API/web return HTTP 200.
- The deployment-only fallback resolves inside the running API container to `claude-sonnet-5-5`; the existing `dramaclaw_ce-data` volume remains mounted.
- Live video catalog verification: `minimax-h3-768p-930-8-22` advertises `768p/2k`; exact catalog matching keeps `seedance-2.0-mini` at its own `480p/720p` capabilities.
