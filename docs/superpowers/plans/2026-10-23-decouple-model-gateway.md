# Decouple Model Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove the RelayClaw and bundled NewAPI assumptions from the CE deployment and model identity, use `https://api.aigcdo.top/v1` as the platform gateway, and route third-party models through explicit configurable mappings without `newapi_` model IDs.

**Architecture:** Keep the existing gateway transport protocols and capability-specific request schemas, but make the catalog entry (`providerId`, `apiModel`, `gatewayModel`, and protocol) the routing authority. Platform mode points at the owned gateway; Sub2API groups remain the configurable third-party route. Bundled NewAPI provisioning and service orchestration are removed rather than retained as a compatibility path.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, SQLite settings, React 19, TypeScript, Vitest, pytest, Docker Compose.

**Spec:** Confirmed in the conversation: owned platform gateway `https://api.aigcdo.top`, current protocol mappings unchanged, custom logical model names allowed, no compatibility migration for existing `newapi_*` project values.

## Global Constraints

- Do not send existing RelayClaw credentials to `api.aigcdo.top`; platform credentials must be entered/saved for the new endpoint.
- Do not introduce automatic migration or aliases for old `newapi_*` project model values.
- Preserve existing OpenAI/Gemini, image reference-format, video endpoint, audio, and embedding protocol behavior.
- Do not commit secrets, generated media, or local runtime state.
- Keep backend model routing explicit; no model-prefix parsing may select a provider.

## Review Focus

- A configured Sub2API image mapping with a custom logical name must emit that name in the catalog and the mapped upstream model on the wire; cover in gateway settings tests.
- A configured Sub2API video mapping must not gain a `newapi_` prefix and must still select the async endpoint from its mapping; cover in catalog and video routing tests.
- A platform-mode credential must resolve against `https://api.aigcdo.top/v1` and must not reuse an old RelayClaw key; cover in settings tests.
- A fresh project must default to neutral image/video IDs and the frontend fallback catalog must match; cover in backend/frontend tests.
- Compose source and release files must boot only API/web and must not require a gateway checkout or `newapi-data`; cover in compose contract tests.

---

### Task 1: Establish the neutral platform gateway contract

**Files:**
- Modify: `src/novelvideo/official_defaults.py`
- Modify: `src/novelvideo/model_gateway_settings.py`
- Modify: `src/novelvideo/config.py`
- Test: `tests/test_model_gateway_settings.py`

**Interfaces:**
- Produce a platform gateway constant for `https://api.aigcdo.top/v1` and neutral default model names.
- Make platform mode resolve only the platform endpoint and its separately stored key.

- [ ] Write failing tests for platform endpoint resolution, neutral defaults, and no RelayClaw credential fallback.
- [ ] Run the focused tests and verify the intended RED failures.
- [ ] Implement the smallest settings/config changes.
- [ ] Run the focused tests and verify GREEN.
- [ ] Commit the RED/GREEN checkpoint as appropriate.

### Task 2: Remove NewAPI prefixes from media catalog identities

**Files:**
- Modify: `src/novelvideo/model_gateway_settings.py`
- Modify: `src/novelvideo/freezone/video_node.py`
- Modify: `src/novelvideo/generators/video_generator.py`
- Modify: `src/novelvideo/api/schemas.py`
- Modify: `src/novelvideo/freezone/route_helpers.py`
- Modify: `src/novelvideo/official_media_models.json`
- Test: `tests/test_newapi_channel_models.py`
- Test: `tests/test_newapi_context_budget.py`
- Test: relevant video/catalog tests

**Interfaces:**
- Catalog `id`/`apiModel` values are neutral logical names; `gatewayModel` remains the upstream model.
- Provider selection comes from catalog/provider configuration, not from a `newapi_` prefix.

- [ ] Add failing tests for neutral Sub2API image/video catalog entries and explicit provider routing.
- [ ] Run focused tests for RED.
- [ ] Replace prefix construction and prefix-based dispatch with explicit catalog/provider routing.
- [ ] Run focused backend tests for GREEN.
- [ ] Commit the catalog/routing checkpoint.

### Task 3: Remove bundled NewAPI deployment and provisioner surface

**Files:**
- Modify: `docker-compose.yml`
- Modify: `docker-compose.release.yml`
- Modify: `.env.example`
- Modify: `src/novelvideo/api/routes/model_gateway.py`
- Modify: frontend model settings API/panels
- Delete or make unreachable: `src/novelvideo/newapi_provisioner.py` and NewAPI-only management routes/components as dictated by tests.
- Test: compose and model-gateway route tests

**Interfaces:**
- Deployment contains API and web only.
- Model settings expose platform and third-party mapping configuration without local NewAPI initialization/channel management.

- [ ] Add failing compose/settings tests proving no bundled service, volume, admin URL, or initialization path is required.
- [ ] Run focused tests for RED.
- [ ] Remove the service, volume, provisioning environment, and management-only route surface.
- [ ] Run backend and frontend settings tests for GREEN.
- [ ] Commit the deployment/settings checkpoint.

### Task 4: Update frontend catalogs, labels, and defaults

**Files:**
- Modify: `frontend/src/features/canvas/ui/ProviderModelPicker.tsx`
- Modify: `frontend/src/features/canvas/application/imageUpscale.ts`
- Modify: `frontend/src/features/canvas/domain/catalogImageModels.ts`
- Modify: `frontend/src/features/canvas/nodes/shared/videoModelCapabilities.ts`
- Modify: affected frontend model and settings tests
- Modify: `readme/README_zh.md`, `docs/zh/**`, `docs/en/**` gateway/deployment references

**Interfaces:**
- UI presents neutral logical IDs and user-defined mapping labels; provider metadata remains separate.
- Documentation describes the owned platform gateway and third-party mappings, not RelayClaw or bundled NewAPI.

- [ ] Update/add failing frontend tests for neutral fallback IDs and catalog display.
- [ ] Run targeted Vitest tests for RED.
- [ ] Implement frontend catalog/default/label changes.
- [ ] Run targeted Vitest tests for GREEN.
- [ ] Update docs and remove stale deployment instructions.
- [ ] Commit the frontend/documentation checkpoint.

### Task 5: Full verification and delivery evidence

**Files:**
- Test: all changed backend/frontend tests
- Create: `docs/superpowers/evidence/2026-10-23-decouple-model-gateway.tdd.md`

- [ ] Run `uv run pytest` with the repository's default markers.
- [ ] Run frontend `pnpm test` and `pnpm build:ce`.
- [ ] Run `ruff`/pre-commit checks applicable to changed files.
- [ ] Search the diff and tracked source for forbidden RelayClaw, bundled NewAPI service, and hardcoded `newapi_` model identities.
- [ ] Record actual RED/GREEN and final verification output in the evidence report.
- [ ] Review the final diff and branch status before reporting results.
