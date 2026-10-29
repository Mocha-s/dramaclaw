# 媒体生成可靠性与运行时队列控制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按已批准的方案 A，修复 360/图片参考/视频交付/AI 优化的可观测性与状态语义，并增加图片、视频模型参数和任务队列的实时配置能力。

**Architecture:** 保留现有 provider、任务 envelope、catalog 和 CE `settings.db` 架构；新增脱敏媒体请求证据和视频交付状态，不重写 provider 适配层。队列配置通过独立 runtime settings 读取，InlineTaskBackend 支持安全热重配，已运行任务不被取消。

**Tech Stack:** Python 3.11/3.12、FastAPI、SQLite、pytest、React 19、TypeScript、Vitest、现有媒体 catalog/request schema。

**Spec:** `docs/superpowers/specs/2026-10-27-media-reliability-and-runtime-controls-design.md`

## Global Constraints

- 不保存 API key、签名 URL、完整 multipart 内容或原始敏感请求。
- 360 双参考模式使用新鲜 overlap analysis 和 spatial contract；缺失时返回稳定错误，不静默生成无合同全景。
- provider completed 与本地 delivery pending/failed 必须分开表达；provider 任务不得因本地重试被重复提交。
- 1080p、thinking/reasoning、quality、ratio 只从媒体 catalog 声明中显示。
- 队列配置降低时不取消已经运行的任务。
- 旧环境变量继续作为没有 settings.db 显式配置时的 fallback。
- 所有生产代码改动遵循 TDD：先写测试并确认失败，再写最小实现。

## Review Focus

1. **双参考但合同缺失：** 新 master/reverse 不能误用旧合同或静默进入无约束生成；由 360 contract 测试覆盖。
2. **两张参考图和重复 prompt：** 参考数量、顺序、协议字段必须可证明，且同一 prompt 不得重复；由 image history/wire 测试覆盖。
3. **provider 已完成但交付失败：** 不得重新提交 provider 任务或退款为未提交；由 video archive/delivery 测试覆盖。
4. **降低队列限制时已有任务运行：** 运行中任务继续完成，后续任务按新配置排队；由 inline backend 动态重配测试覆盖。
5. **模型切换后的参数泄漏：** 旧模型的 thinking/resolution 参数不得带到新模型；由 catalog/React 参数测试覆盖。

---

### Task 1: 通用运行时设置与队列限制解析

**Files:**
- Create: `src/novelvideo/runtime_settings.py`
- Modify: `src/novelvideo/task_backend/limits.py`
- Modify: `src/novelvideo/api/routes/config.py` or create `src/novelvideo/api/routes/task_limits.py`
- Modify: API router registration file under `src/novelvideo/api/`
- Test: `tests/test_task_backend_limits.py`
- Test: new `tests/test_runtime_task_limits_api.py`

**Interfaces:**
- `read_runtime_json(key: str, default: object) -> object`
- `write_runtime_json(key: str, value: object) -> None`
- `TaskLimitsConfig` with four lane records: `default`, `video`, `world`, `ffmpeg`
- `GET /api/v1/config/task-limits -> {data: current, defaults: defaults}`
- `PUT /api/v1/config/task-limits -> {data: saved, effective: effective}`

- [ ] **Step 1: Write failing tests**
  - Assert default `project_user_active_limit` no longer introduces a hidden default-lane cap of 3; default lane inherits the project lane limit unless explicitly configured.
  - Assert valid settings persist to SQLite and are read by `project_lane_active_limit`, `project_user_lane_active_limit`, `global_lane_concurrency`, and `global_lane_queue_limit`.
  - Assert values outside the ranges global `1..32`, queue `1..4096`, active `1..256` return HTTP 422/400 without changing saved settings.
  - Assert unauthorised settings mutation is rejected and no secret values are returned.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/test_task_backend_limits.py tests/test_runtime_task_limits_api.py -q`
  - Expected: new persistence/API tests fail because runtime settings and route do not exist.
- [ ] **Step 3: Implement runtime settings and API**
  - Create a small SQLite-backed JSON setting helper using the existing CE `settings.db` location and `runtime_settings` table shape.
  - Make explicit settings override environment variables; use environment variables only as fallback.
  - Add `task_limits.v1` validation and the protected GET/PUT route. Reuse the repository’s existing CE settings-management authorization boundary.
  - Change default project/user limits so the default lane is not silently capped at 3; keep global lane defaults as `8/2/1/1` and queue defaults as `512/128/64/64`.
- [ ] **Step 4: Run tests to verify they pass**
  - Run: `uv run pytest tests/test_task_backend_limits.py tests/test_runtime_task_limits_api.py -q`
  - Expected: PASS.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/runtime_settings.py src/novelvideo/task_backend/limits.py src/novelvideo/api tests/test_task_backend_limits.py tests/test_runtime_task_limits_api.py`
  - `git commit -m "feat(tasks): persist runtime lane limits"`

### Task 2: Inline backend hot reconfiguration

**Files:**
- Modify: `src/novelvideo/ports/local/tasks.py`
- Modify: `src/novelvideo/ports/local/__init__.py`
- Test: `tests/contract/test_l014_inline_task_backend_concurrency.py`

**Interfaces:**
- `InlineTaskBackend.reload_limits() -> None`
- `InlineTaskBackend.lane_snapshot() -> dict[str, dict[str, int]]` remains compatible and reports effective values.

- [ ] **Step 1: Write failing tests**
  - Start a lane with concurrency 1, run one blocking task, update settings to concurrency 2, enqueue another task, and assert the second starts without restarting the backend.
  - Lower concurrency while two tasks are active and assert neither task is cancelled; assert no new task starts above the new value after they finish.
  - Lower queue limit and assert existing queued tasks remain but new enqueue is rejected at the new limit.
  - Assert increasing settings through the API calls the registered local backend reload hook.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/contract/test_l014_inline_task_backend_concurrency.py -q`
  - Expected: hot-reload tests fail because lane values are fixed in `__init__`.
- [ ] **Step 3: Implement hot reload**
  - Add a reload method that reads the current limits, updates lane counters and queue limits, and safely replaces executors only for future work; active futures keep their existing executor.
  - Make enqueue refresh the configuration before admission and have the PUT route call the local backend reload hook immediately.
  - Never cancel active jobs when reducing a limit; only drain queued jobs up to the new concurrency.
- [ ] **Step 4: Run tests to verify they pass**
  - Run: `uv run pytest tests/contract/test_l014_inline_task_backend_concurrency.py -q`
  - Expected: PASS with existing fairness and queue overflow tests unchanged.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/ports/local/tasks.py src/novelvideo/ports/local/__init__.py tests/contract/test_l014_inline_task_backend_concurrency.py`
  - `git commit -m "feat(tasks): hot reload inline lane limits"`

### Task 3: Settings UI for all queue limits

**Files:**
- Modify: `frontend/src/components/settings/settings-dialog.tsx`
- Modify: frontend API/settings hook files discovered beside the existing model gateway settings client
- Modify: frontend locale files for Chinese/English settings labels
- Test: settings dialog Vitest tests

**Interfaces:**
- API client methods `getTaskLimits()` and `saveTaskLimits(value)` use `/api/v1/config/task-limits`.
- Four lane rows expose `globalConcurrency`, `globalQueueLimit`, `projectActiveLimit`, `projectUserActiveLimit`.

- [ ] **Step 1: Write failing tests**
  - Assert the settings dialog renders all four lanes and four editable values per lane.
  - Assert invalid values are blocked client-side and server errors are shown without overwriting the last saved state.
  - Assert saving refreshes the effective snapshot and displays active/queued counts.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `pnpm --dir frontend exec vitest run src/__tests__/components/settings/task-limits-dialog.test.tsx`
  - Expected: test file/components do not exist.
- [ ] **Step 3: Implement UI**
  - Add a “任务与队列” settings page using existing SettingsDialog tabs and form controls.
  - Use number inputs with the backend ranges, save via the new API, and render current active/queued snapshots read-only.
  - Do not expose secrets or environment variable names in the UI.
- [ ] **Step 4: Run tests to verify they pass**
  - Run: `pnpm --dir frontend exec vitest run src/__tests__/components/settings/task-limits-dialog.test.tsx`
  - Expected: PASS.
- [ ] **Step 5: Commit**
  - `git add frontend/src/components/settings frontend/src/api frontend/src/i18n tests`
  - `git commit -m "feat(settings): add live task queue controls"`

### Task 4: 360 contract enforcement and prompt/reference audit

**Files:**
- Modify: `src/novelvideo/stage_asset_tasks.py`
- Modify: `src/novelvideo/director_world/scene_360_builder.py`
- Modify: `src/novelvideo/task_backend/runners/freezone.py`
- Modify: `src/novelvideo/freezone/history.py`
- Modify: `src/novelvideo/generators/nanobanana_grid.py`
- Modify: `frontend/src/features/canvas/nodes/shared/useImageGenerationForm.ts`
- Test: `tests/test_p0g4l_scene_360_subprocess_egress.py`
- Test: `tests/test_newapi_image_gateway.py`
- Test: new prompt dedup/history tests

**Interfaces:**
- `Scene360ReferenceAudit` contains input hashes, dimensions, freshness, and contract status.
- `build_node_history_record(..., reference_audit: dict | None = None)` adds optional redacted evidence.
- `_newapi_safe_request_context(...)` includes reference count, protocol and request path but never raw URLs/tokens.

- [ ] **Step 1: Write failing tests**
  - Assert a missing/stale overlap or spatial contract causes `SCENE_360_SPATIAL_CONTRACT_UNAVAILABLE` in strict dual-reference mode.
  - Assert a valid contract appears in builder argv, prompt metadata, and manifest.
  - Assert the two reference files produce two hashes in history and the selected protocol is recorded.
  - Assert identical upstream/node prompt text occurs once in the final generation prompt.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/test_p0g4l_scene_360_subprocess_egress.py tests/test_newapi_image_gateway.py tests/test_freezone_image_backend.py -q`
  - Expected: strict missing-contract, audit, and prompt-dedup tests fail.
- [ ] **Step 3: Implement contract/audit/dedup behavior**
  - Reuse the existing freshness/schema checks; add strict-mode error handling and the manifest audit fields.
  - Pass a redacted reference audit from the image runner into node history.
  - Deduplicate normalized upstream/node prompt text before compiling the request.
  - Preserve all existing reference format branches (`images`, `input_reference`, `multipart`, `dc-media`).
- [ ] **Step 4: Run tests to verify they pass**
  - Run the focused command from Step 2.
  - Expected: PASS and no sensitive values appear in captured logs.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/stage_asset_tasks.py src/novelvideo/director_world src/novelvideo/task_backend/runners/freezone.py src/novelvideo/freezone/history.py src/novelvideo/generators/nanobanana_grid.py frontend/src/features/canvas/nodes/shared/useImageGenerationForm.ts tests`
  - `git commit -m "fix(media): audit references and enforce scene contracts"`

### Task 5: Video provider/delivery state and timeout separation

**Files:**
- Modify: `src/novelvideo/generators/video_generator.py`
- Modify: `src/novelvideo/freezone/jobs.py`
- Modify: `src/novelvideo/freezone/video_node.py`
- Modify: `src/novelvideo/task_backend/runners/video.py`
- Modify: `src/novelvideo/video_request_usage.py`
- Modify: `src/novelvideo/config.py`
- Test: `tests/test_video_archive_delivery.py`
- Test: `tests/test_seedance2_request.py`
- Test: new provider/delivery state tests

**Interfaces:**
- `VideoGenResult.provider_status` and `VideoGenResult.delivery_status` are optional backward-compatible fields.
- New configuration readers: `video_provider_timeout_seconds()`, `video_delivery_timeout_seconds()`, `video_poll_interval_seconds()`.
- Usage status records distinguish `provider_completed`, `delivery_pending`, `delivery_failed`, and `completed`.

- [ ] **Step 1: Write failing tests**
  - Simulate provider `completed` followed by archive pending and assert no second provider submission occurs.
  - Simulate provider `completed` followed by download failure and assert delivery retry metadata is returned instead of a provider failure message.
  - Simulate terminal provider failure and assert it remains `provider_failed`.
  - Assert timeout values are independently configurable and default to the current approximately 30-minute provider window.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/test_video_archive_delivery.py tests/test_seedance2_request.py -q`
  - Expected: delivery-state assertions fail because current code returns `VideoGenStatus.FAILED` for all post-provider failures.
- [ ] **Step 3: Implement state separation**
  - Keep provider polling bounded by provider timeout; after provider completion, stop polling provider status and run a bounded delivery retry loop.
  - Confirm billing at provider completion; do not resubmit or locally refund an accepted provider task.
  - Add safe status/error fields to task result/history and preserve old `status` compatibility for clients that only understand completed/failed.
  - Expose delivery-pending/failed details to Freezone UI without exposing provider credentials or signed URLs.
- [ ] **Step 4: Run tests to verify they pass**
  - Run the focused command from Step 2.
  - Expected: PASS, including existing archive retry and egress tests.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/generators/video_generator.py src/novelvideo/freezone src/novelvideo/task_backend/runners/video.py src/novelvideo/video_request_usage.py src/novelvideo/config.py tests`
  - `git commit -m "fix(video): separate provider completion from delivery"`

### Task 6: Catalog-driven thinking and resolution controls

**Files:**
- Modify: `src/novelvideo/media_model_request_schema.py`
- Modify: `src/novelvideo/model_gateway_settings.py`
- Modify: `src/novelvideo/freezone/video_node.py`
- Modify: `frontend/src/api/ops.ts`
- Modify: `frontend/src/features/canvas/ui/MediaModelParameterChip.tsx`
- Modify: `frontend/src/features/canvas/nodes/shared/useImageGenerationForm.ts`
- Modify: `frontend/src/features/canvas/nodes/shared/useVideoGenerationForm.ts`
- Modify: `frontend/src/features/canvas/nodes/shared/VideoGenerationForm.tsx`
- Modify: image/video catalog and settings components as required by existing structure
- Test: `tests/test_media_model_request_schema.py`
- Test: `tests/test_freezone_video_backend.py`
- Test: frontend catalog/model parameter tests

**Interfaces:**
- `MediaModelParameterDefinition` remains the single parameter definition shape.
- `userSelectableMediaModelParameters()` includes `thinking_level` only when the catalog explicitly marks it user-selectable.
- Catalog entries continue to use `resolutionOptions`, `qualityOptions`, `ratioOptions`, and `request.parameters`.

- [ ] **Step 1: Write failing tests**
  - Assert catalog-declared thinking options are visible for image and video models.
  - Assert undeclared thinking options are not rendered or submitted.
  - Assert selecting a model with `1080p` exposes it and selecting a model without it does not.
  - Assert changing model or generation mode removes stale model parameters before submit.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/test_media_model_request_schema.py tests/test_freezone_video_backend.py -q` and focused Vitest catalog tests.
  - Expected: thinking-level visibility and model-switch assertions fail.
- [ ] **Step 3: Implement catalog-driven controls**
  - Remove unconditional hiding of `thinking_level`; preserve mode filtering and server-only parameters declared separately.
  - Normalize catalog resolution/quality/thinking options through the existing schema and submit paths.
  - Add `1080p` only to catalog entries whose upstream capability is verified; do not add a universal fallback.
- [ ] **Step 4: Run tests to verify they pass**
  - Run both focused Python and frontend commands.
  - Expected: PASS.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/media_model_request_schema.py src/novelvideo/model_gateway_settings.py src/novelvideo/freezone/video_node.py frontend/src/api/ops.ts frontend/src/features/canvas tests`
  - `git commit -m "feat(media): expose catalog thinking and resolution controls"`

### Task 7: AI video optimization retries and partial success

**Files:**
- Modify: `src/novelvideo/task_backend/runners/video.py`
- Modify: `src/novelvideo/api/routes/generation.py` only if response projection needs new fields
- Modify: frontend task-result/status component used by global video optimize
- Test: new `tests/test_global_video_optimizer_retries.py`
- Test: existing `frontend/src/__tests__/components/episode/beat-workbench/batch-bar.test.tsx` or the matching task status test

**Interfaces:**
- Worker result: `{optimized: int, failed: int, failed_beats: list[dict], beats: list[dict]}`.
- Failure record fields: `beat_number`, `attempts`, `error_code/message` with provider details redacted.

- [ ] **Step 1: Write failing tests**
  - Simulate one Beat failing twice then succeeding and assert it is persisted once with `attempts=3`.
  - Simulate one Beat permanently failing and another succeeding; assert the task completes with partial-success metadata and the successful Beat remains saved.
  - Simulate all Beats failing; assert the task remains failed with the last safe error.
  - Assert retry does not create an additional billing quantity.
- [ ] **Step 2: Run tests to verify they fail**
  - Run: `uv run pytest tests/test_global_video_optimizer_retries.py -q`
  - Expected: retry/partial-result tests fail because current worker only accumulates plain failure strings.
- [ ] **Step 3: Implement bounded retries**
  - Wrap each `optimize_single_beat` call with two retries and short exponential backoff.
  - Persist each successful Beat immediately; return structured failed-beat metadata.
  - Update task progress/log projection to show `optimized/total` and failed count.
- [ ] **Step 4: Run tests to verify they pass**
  - Run focused Python and frontend status tests.
  - Expected: PASS.
- [ ] **Step 5: Commit**
  - `git add src/novelvideo/task_backend/runners/video.py src/novelvideo/api/routes/generation.py frontend/src tests/test_global_video_optimizer_retries.py`
  - `git commit -m "fix(video): retry optimizer beats independently"`

### Task 8: Cross-module verification and documentation alignment

**Files:**
- Modify: `docs/superpowers/specs/2026-10-27-media-reliability-and-runtime-controls-design.md` status/verification section
- Modify: installation or operations docs if the new runtime settings endpoint requires operator instructions
- Test/Review: no product code; verification only

- [ ] **Step 1: Run focused backend verification**
  - `uv run pytest tests/test_p0g4l_scene_360_subprocess_egress.py tests/test_newapi_image_gateway.py tests/test_video_archive_delivery.py tests/test_task_backend_limits.py tests/contract/test_l014_inline_task_backend_concurrency.py tests/test_global_video_optimizer_retries.py -q`
- [ ] **Step 2: Run focused frontend verification**
  - `pnpm --dir frontend exec vitest run src/__tests__/features/canvas src/__tests__/components/settings src/__tests__/components/episode/beat-workbench`
- [ ] **Step 3: Run repository verification**
  - `uv run pytest`
  - Record unrelated pre-existing failures separately; do not hide them.
- [ ] **Step 4: Run diff/security checks**
  - `git diff --check`
  - Search changed logs/tests for API keys, signed URLs, raw multipart bodies, and unredacted provider responses.
  - Verify runtime queue endpoints reject unauthorised writes.
- [ ] **Step 5: Update the spec status and report impact alignment**
  - Mark each acceptance criterion with evidence, list remaining provider-dependent manual checks, and document any scope drift before release.
- [ ] **Step 6: Commit**
  - `git add docs tests`
  - `git commit -m "docs: record media reliability verification"`

## Dependency Order

```text
Task 1 ──> Task 2 ──> Task 3
Task 4 ──> Task 5 ──> Task 6
Task 7
Task 8 depends on Tasks 1–7
```

Tasks 4 and 1 can start independently. Task 2 depends on Task 1 only for the runtime settings persistence helper if the queue API shares the same module; otherwise it can run in parallel. Task 3 depends on Task 2. Tasks 4–7 are independent of the queue UI and can be delivered as separate commits.

## Self-Review

- **Spec coverage:** all seven goals and five acceptance groups map to Tasks 1–8.
- **Scope:** no provider rewrite, no database migration beyond the existing runtime settings table, no media payload secrets, and no automatic cancellation.
- **Compatibility:** old environment variables, task states, history records, and catalog entries remain readable.
- **Main unresolved implementation risk:** provider-specific archive/delivery responses vary; Task 5 must use captured synthetic responses and preserve an explicit unknown state rather than assuming a single response shape.
