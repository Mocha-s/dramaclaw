# Media Regressions and Project Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore media parameter flow, repair 360 analysis routing, preserve project-controlled visual style, and classify video provider account failures without unsafe retries.

**Architecture:** Keep the existing gateway, task, and provider boundaries. Add a narrow analysis-route resolver for the two 360 vision aliases, pass project style through the existing panorama prompt builder, extend the existing RenderSettings/RenderPlan contract with image quality, and verify Beat video resolution remains catalog/backend-driven and reaches the single-video task.

**Tech Stack:** Python 3.11-compatible FastAPI/Pydantic, pytest, React/TypeScript, Vitest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-28-media-regressions-and-project-style-design.md`

## Global Constraints

- 360 style is controlled by the project `visual_style` and style preset; do not hardcode photographic, realistic, illustration, watercolor, or any other universal style.
- Spatial contracts constrain geometry/topology only and must not override project style.
- Keep strict dual-reference spatial-contract validation enabled by default.
- Image quality values remain `low`, `medium`, and `high` where the existing provider path supports them.
- Beat video generation resolution is distinct from project video compose/export resolution.
- Do not retry a billable video provider submission after `503 account unavailable`.
- Do not log API keys, signed URLs, raw multipart payloads, or unredacted provider responses.

## Review Focus

- Unmapped scene-analysis aliases must fail with a diagnostic route error, not silently use an unrelated media endpoint; test the fallback to the configured vision-capable text route.
- A project style preset such as `realistic` must appear in the panorama prompt without forcing a universal style; test a non-realistic preset too.
- Render quality omitted by an old client must preserve the existing default; test explicit `low`, `medium`, and `high` round trips.
- Beat video resolution must survive backend normalization for both Seedance and non-Seedance paths; test unsupported values fall back according to existing backend options.
- Provider `503 account unavailable` must remain distinguishable from local delivery failure and must not create a second provider submission.

---

### Task 1: Route 360 analysis aliases through the configured vision-capable gateway

**Files:**
- Modify: `src/novelvideo/director_world/scene_analysis_gateway.py`
- Modify: `.env.example`
- Modify: `src/novelvideo/config.py` or `src/novelvideo/model_gateway_settings.py` only if the route resolver needs a shared gateway helper
- Test: `tests/test_scene_analysis_gateway.py`

**Interfaces:**
- Produces `resolve_scene_analysis_model(model_env: str, default_model: str, model: str = "") -> str` that returns the requested model when it has an explicit configured route, otherwise the explicitly configured `SCENE_ANALYSIS_FALLBACK_MODEL`.
- Keeps `analyze_scene_references(..., capability="vision.analyze")` and existing provider credential handling intact.
- Do not implicitly fall back to `DC-freezone-text-writer-LLM`; current deployment maps it to an upstream model that returned HTTP 404.
- If neither requested route nor explicit fallback has a configured route, raise a clear configuration error without disclosing credentials.

- [ ] **Step 1: Write failing tests**
  - Add a test proving an unmapped `DC-scene-spatial-contract-LLM` resolves to explicit `SCENE_ANALYSIS_FALLBACK_MODEL`, not `DC-freezone-text-writer-LLM`.
  - Add a test proving an explicitly mapped analysis alias remains unchanged.
  - Add a test proving no valid fallback raises a clear configuration error without exposing credentials.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scene_analysis_gateway.py -q`

Expected: the new route-resolution assertions fail because the current resolver returns the unmapped alias and the gateway eventually requests `gpt-6.1-sol`.

- [ ] **Step 3: Implement the minimal resolver and document the runtime setting**
  - Resolve the effective config for the requested alias first.
  - If it resolves to a valid configured model/base/key, preserve it.
  - If it has no explicit mapping, choose `SCENE_ANALYSIS_FALLBACK_MODEL` only when that alias has an explicit configured route.
  - Add the variable to `.env.example` as an empty optional setting with a comment that the alias must map to a vision-capable upstream model.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_scene_analysis_gateway.py -q`

Expected: all scene-analysis gateway tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/novelvideo/director_world/scene_analysis_gateway.py src/novelvideo/config.py src/novelvideo/model_gateway_settings.py tests/test_scene_analysis_gateway.py
git commit -m "fix(scene): route spatial analysis through configured models"
```

### Task 2: Preserve project-controlled 360 visual style

**Files:**
- Modify: `src/novelvideo/director_world/scene_360_builder.py`
- Modify: `src/novelvideo/stage_asset_tasks.py` only if the project style is not already passed into the child command
- Test: `tests/test_p0g4l_scene_360_subprocess_egress.py` or a focused scene-builder test module

**Interfaces:**
- `build_prompt(..., style: str, ...) -> str` remains the style boundary.
- The prompt must include the selected project style preset and a style-preservation rule, but must not contain a universal `photorealistic`/`realistic` requirement.
- Spatial-contract text remains geometry-only and is appended independently of style text.

- [ ] **Step 1: Write failing tests**
  - Test `style="realistic"` includes the project style instructions and a no-style-drift rule.
  - Test `style="ink_illustration"` or another non-realistic preset does not receive a forced photographic/realistic instruction.
  - Test a spatial contract prompt insert does not replace or remove project style instructions.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_p0g4l_scene_360_subprocess_egress.py -q`

Expected: the new prompt assertions fail because the current style section is not strict enough to prevent model style drift.

- [ ] **Step 3: Implement project-style inheritance**
  - Add only project-relative wording such as “preserve the selected project visual style and medium; do not introduce a different medium or rendering language.”
  - Keep all actual style vocabulary sourced from `get_style_preset`.
  - Do not alter spatial contract semantics or strict validation.

- [ ] **Step 4: Run focused scene tests**

Run: `uv run pytest tests/test_p0g4l_scene_360_subprocess_egress.py tests/test_scene_analysis_gateway.py -q`

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/novelvideo/director_world/scene_360_builder.py src/novelvideo/stage_asset_tasks.py tests/test_p0g4l_scene_360_subprocess_egress.py
git commit -m "fix(scene): preserve project visual style in panoramas"
```

### Task 3: Restore 虾集 mainline image quality flow

**Files:**
- Modify: `src/novelvideo/api/schemas.py`
- Modify: `src/novelvideo/api/routes/generation.py`
- Modify: `src/novelvideo/task_backend/runners/render.py`
- Modify: `frontend/src/lib/queries/render-settings.ts`
- Modify: `frontend/src/components/episode/beat-workbench/render-settings-controls.tsx`
- Modify: `frontend/src/lib/queries/render-plan.ts`
- Modify: `frontend/src/components/episode/beat-workbench/render-plan-dialog.tsx`
- Test: `tests/test_api_render_settings.py` or matching render route test; `tests/test_api_generation_sketches.py`/render task test; frontend render settings and render-plan tests

**Interfaces:**
- `RenderSettingsData` gains `image_quality: str` and `RenderSettingsUpdate` accepts `image_quality?: "low" | "medium" | "high"`.
- `RenderPlanRequest` and `RenderPlanExecuteRequest` gain optional `image_quality`.
- Render task config carries `image_quality` to `run_render` and existing worker quality handling.
- Existing clients omitting the field continue to use the current project/provider default.

- [ ] **Step 1: Write failing backend and frontend tests**
  - Assert GET/PATCH render settings round-trip `image_quality`.
  - Assert render plan execute payload preserves explicit `high` and task payload contains `image_quality="high"`.
  - Assert invalid quality is rejected with 400.
  - Assert the render settings UI displays and updates the quality selector.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_render_settings.py -q` and the focused render-plan test; then run the matching Vitest files.

Expected: schema rejects/ignores the missing field and the UI has no quality control.

- [ ] **Step 3: Implement the contract end to end**
  - Validate the three allowed values at the API boundary.
  - Persist the value in project config and include it in render plan payloads.
  - Pass it into the existing `config.image_quality` worker path without changing provider adapters.
  - Add a compact quality selector beside the existing Render model selector.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/test_api_render_settings.py tests/test_api_generation_sketches.py -q` and the focused frontend render settings/render-plan Vitest files.

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/novelvideo/api/schemas.py src/novelvideo/api/routes/generation.py src/novelvideo/task_backend/runners/render.py frontend/src/lib/queries/render-settings.ts frontend/src/components/episode/beat-workbench/render-settings-controls.tsx frontend/src/lib/queries/render-plan.ts frontend/src/components/episode/beat-workbench/render-plan-dialog.tsx tests frontend/src/__tests__
git commit -m "feat(render): expose mainline image quality control"
```

### Task 4: Preserve Beat video generation resolution

**Files:**
- Modify: `src/novelvideo/api/schemas.py` only if the existing `SingleVideoRequest` contract needs normalization coverage
- Modify: `src/novelvideo/api/routes/generation.py` only where resolution is normalized or projected into task payload
- Modify: `frontend/src/components/episode/beat-workbench/video-pane.tsx` only where model options omit catalog-supported `768p`, `2K`, or `4K`
- Test: backend single-video route tests and frontend video-pane tests

**Interfaces:**
- The single Beat video request continues using `resolution: str` and task config `resolution`.
- Resolution options come from the selected backend/catalog; the allowed product set is `720p`, `768p`, `1080p`, `2K`, `4K` where advertised/accepted.
- Compose/export `project.video_resolution` remains unchanged.

- [ ] **Step 1: Write failing tests**
  - Assert `768p`, `2K`, and `4K` survive the single-video route/task payload when the selected backend advertises them.
  - Assert unsupported values normalize to the backend’s existing fallback.
  - Assert frontend options preserve catalog/backend values instead of filtering them to the old three-value union.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_video_batch_schema.py tests/test_freezone_video_backend.py -q` and the focused video-pane Vitest files.

Expected: current backend/frontend unions or normalization drop non-legacy resolutions.

- [ ] **Step 3: Implement minimal resolution preservation**
  - Expand typed option unions only where needed.
  - Reuse existing backend normalization and billing; do not alter compose/export resolution.

- [ ] **Step 4: Run focused tests**

Run the same backend and frontend commands; expected all pass.

- [ ] **Step 5: Commit**

```bash
git add src/novelvideo/api/schemas.py src/novelvideo/api/routes/generation.py frontend/src/components/episode/beat-workbench/video-pane.tsx tests frontend/src/__tests__
git commit -m "fix(video): preserve Beat generation resolutions"
```

### Task 5: Classify video provider account-unavailable failures

**Files:**
- Modify: `src/novelvideo/generators/video_generator.py` or the existing provider error classifier
- Modify: `src/novelvideo/task_backend/runners/video.py`/task projection only where user-facing error status is projected
- Test: `tests/test_video_archive_delivery.py`, `tests/test_video_processing_request.py`, or matching video provider error tests

**Interfaces:**
- A provider HTTP 503 body containing `account unavailable` maps to a stable provider-unavailable error code/message.
- It remains a provider failure; no delivery retry or second submit is attempted.
- Existing provider/delivery status fields remain backward-compatible.

- [ ] **Step 1: Write failing tests**
  - Simulate the exact 503 response and assert stable provider-unavailable classification.
  - Assert submit call count is one and delivery retry metadata is absent.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_video_archive_delivery.py tests/test_video_processing_request.py -q`

- [ ] **Step 3: Implement the narrow classifier**

- [ ] **Step 4: Run focused tests and commit**

```bash
git add src/novelvideo/generators/video_generator.py src/novelvideo/task_backend/runners/video.py tests
git commit -m "fix(video): classify unavailable provider accounts"
```

### Task 6: Full verification and deployment

- [ ] Run focused backend and frontend suites for all five tasks.
- [ ] Run `uv run pytest` and the relevant frontend suite.
- [ ] Run `git diff --check`, Ruff, TypeScript build, and secret/error-log scan.
- [ ] Set the deployment-only `SCENE_ANALYSIS_FALLBACK_MODEL=claude-sonnet-5-5` in the existing host `.env` if that model route remains configured; do not place credentials in `.env` changes or source control.
- [ ] Build/deploy the latest branch without deleting `ce-data`.
- [ ] Verify API/web HTTP 200, API health, and running image IDs.
- [ ] Keep real provider generation manual and authorized; do not submit paid tests automatically.

## Execution Notes

- Native execution is isolated in worktree branch `fix/media-regressions-project-style`, based on commit `02de0836`.
- The fallback resolver intentionally refuses to silently reuse `DC-freezone-text-writer-LLM`; production evidence showed it resolves to `gpt-6.1-sol`, which returns HTTP 404 for vision analysis. Configure the deployment-only fallback alias explicitly.
- The spec was force-added because the repository ignores `docs/superpowers/`; the implementation plan and SDD ledger remain worktree artifacts unless explicitly force-added later.
