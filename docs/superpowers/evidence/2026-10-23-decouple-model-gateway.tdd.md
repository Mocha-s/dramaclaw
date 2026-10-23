# Decouple Model Gateway — Verification Evidence

## Scope

- Platform endpoint is `https://api.aigcdo.top/v1`.
- Compose continues to start/build the bundled gateway as an optional existing workflow.
- Media/project model IDs use neutral names such as `gpt-image-2`, `nano-banana-2`, and `seedance-2.0`.
- BrainClaw behavior remains intact; `CUSTOM_LLM_MODE_RELAYCLAW_BRAINCLAW` was not removed.
- Existing Custom/Hybrid/BrainClaw settings APIs/widgets remain intact.

## Evidence

| Guarantee | Command | Result |
|---|---|---|
| Platform endpoint and custom mapping contract | `uv run pytest tests/test_model_gateway_settings.py::test_platform_gateway_defaults_to_owned_endpoint_and_neutral_identity tests/test_model_gateway_settings.py::test_sub2api_media_catalog_keeps_custom_logical_names_without_newapi_prefix` | PASS |
| Legacy platform key is not reused and is retired after replacement | `uv run pytest tests/test_model_gateway_settings.py::test_platform_gateway_does_not_reuse_legacy_official_key tests/test_model_gateway_settings.py::test_saving_platform_key_retires_legacy_official_key` | PASS |
| Compose preserves bundled gateway and uses owned platform URL | `uv run pytest tests/test_docker_persistence_config.py` | PASS |
| BrainClaw route still works | `uv run pytest tests/test_chat_service_user_agent_scope.py::test_ce_codex_model_sends_brainclaw_only_for_custom_brainclaw_mode tests/test_brainclaw_contract.py::test_custom_brainclaw_endpoint_does_not_replace_official_gateway` | PASS |
| Frontend neutral model fallbacks and capability routing | `corepack pnpm exec vitest run src/__tests__/features/canvas/provider-model-picker-defaults.test.ts src/__tests__/features/canvas/video-model-capabilities.test.ts src/__tests__/features/canvas/video-node-generation-matrix.test.tsx` | PASS (150 tests) |
| Frontend TypeScript compilation | `corepack pnpm exec tsc -b` | PASS |
| Backend full suite | `uv run pytest -n 4 -q` | PASS: 7243 passed, 31 skipped |

## Known gaps

- No credentialed live smoke test was run against `api.aigcdo.top`; external compatibility remains unverified beyond request/configuration tests.
- Frontend full suite was not rerun after the final backend-only changes; targeted frontend tests and TypeScript build passed.
- RelayClaw/NewAPI wording remains in historical documentation and internal compatibility function names. The bundled service and settings surface remain by design to protect existing functionality.
