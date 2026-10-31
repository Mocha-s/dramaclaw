# Render queue, image size, and 360 timeout — TDD evidence

## User journeys

- A user regenerating one beat can still start rendering another beat; each active render shows its own progress and stop action.
- A user can choose 1K, 2K, or 4K for Render, and that explicit size reaches the image-generation request and matching credit quote. Projects without an explicit Render size retain the existing mode-based size.
- A slow 360 spatial-contract request gets a longer bounded analysis window, while missing or stale spatial evidence still blocks panorama generation.

## RED → GREEN evidence

| Guarantee | Test target | RED evidence | GREEN evidence |
|---|---|---|---|
| Render settings expose, persist, and validate `render_image_size`; single-render enqueue carries explicit size | `tests/test_api_render_settings.py`, `tests/test_api_render_regenerate.py` | 4 focused failures: missing GET field, PATCH dropped size, invalid size accepted, task payload missing size | `uv run pytest tests/test_api_render_settings.py tests/test_api_render_regenerate.py ... -q` — included in the 124-pass focused set and full Python suite |
| Render runner passes explicit size to the generator; unset size preserves mode defaults | `tests/test_render_runner_canvas_skill_inputs.py` and render runner tests | Assertion requires `generator_config.image_size` and `force_image_size` to be `2K` | Same focused set passed |
| A beat's render task does not claim another beat's controller; size control persists 2K | Frontend `render-section.test.tsx`, `render-settings-controls.test.tsx` | 2 focused failures for missing `coversBeat` and image-size control | `pnpm exec vitest run --no-file-parallelism ...` — 38 tests passed; `pnpm exec tsc -b --pretty false` passed |
| 360 reference analysis gets enough bounded time for slow spatial-contract responses | `tests/test_media_reference_and_scene_analysis_regressions.py` | Both default-timeout tests failed at 300/600 seconds | Python suite passed with the new 600/1800-second defaults; strict evidence tests remain green |

## Verification and known gaps

- Full Python suite: `uv run pytest -q` — **7,433 passed, 31 skipped, 3 deselected**.
- Focused Python regression set — **124 passed**. Touched-file Ruff and `git diff --check` passed.
- Focused frontend suite — **38 passed**; TypeScript build check passed.
- Full frontend Vitest run exceeded the 10-minute command limit and reported four failures in unrelated `model-scoped-create-schema` and `catalog-image-model-request` tests. Full-repository Ruff also reports existing issues outside this change; touched-file Ruff is clean.
- Coverage was not run.
- Live API evidence for task `b30427a9-2b78-4db6-b45e-e5803581d84f` shows the spatial-contract request timed out in `asyncio.wait_for` at its 300-second bound. The current running container still has `SCENE_ANALYSIS_TIMEOUT_SECONDS=300` and `SCENE_ANALYSIS_SUBPROCESS_TIMEOUT_SECONDS=600`; this worktree has no `.env`. Deploy with **600** and **1800** respectively, then restart the API and run a fresh 360 task. Strict evidence admission has not been weakened.

## Checkpoint commits

- `6ee5de52 test: cover render concurrency and image size propagation` — RED tests.
- `06f0769a fix(render): unblock per-beat generation and honor image size` — implementation and GREEN verification.
