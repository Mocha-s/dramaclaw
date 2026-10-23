# Decouple Platform Gateway from NewAPI — Design

## Intent

Remove the product and deployment dependency on RelayClaw and the bundled NewAPI service. CE's platform gateway becomes `https://api.aigcdo.top/v1`. Users can route capabilities through configured third-party gateway groups using custom logical model names, without provider prefixes such as `newapi_gpt_image2`.

## Why

The current implementation combines model identity, provider selection, and gateway branding. Project/media values include `newapi_*`; video dispatch parses that prefix; Compose requires a separate NewAPI container even when the platform gateway is selected. This makes a third-party gateway harder to configure and makes locally bundled NewAPI appear mandatory.

## Goals

- Use `https://api.aigcdo.top/v1` as the fixed platform gateway base URL.
- Require a separately configured platform gateway API key; never reuse an old RelayClaw key for the new host.
- Remove the bundled NewAPI service, data volume, source-checkout build dependency, admin/provisioning flow, and settings UI for managing that service.
- Make model identity independent of provider: IDs are custom logical names, while catalog metadata carries provider/protocol, API model, and upstream model separately.
- Permit multiple groups to expose the same real upstream model under distinct logical names.
- Preserve the existing OpenAI/Gemini protocol choices, image edit formats, video endpoints, audio and embedding request behavior.
- Do not add a migration or compatibility aliases for old `newapi_*` project model IDs; old projects must select a model again.

## Non-goals

- Do not implement new provider protocols or translate unsupported provider-specific APIs.
- Do not remove direct OpenAI, Google, HuiMeng, OpenRouter, Fal, or ComfyUI integrations that are independent of the bundled NewAPI management plane.
- Do not change billing semantics, generation request fields, or media reference storage except where necessary to remove model-prefix routing.
- Do not make `api.aigcdo.top`'s model catalog or capabilities dynamic unless already supported by current configuration.

## Design

1. Keep a platform mode backed by a non-secret fixed base URL and a dedicated key saved in the CE settings database. A key previously saved for RelayClaw is not considered valid for the new endpoint and is not automatically forwarded.
2. Keep configurable third-party account groups. Each group has a stable group ID/name, protocol (`openai` or `gemini`), Base URL, capability set, key, and explicit `requestPattern -> upstreamModel` entries. Exact custom logical names are the normal route; existing wildcard mapping support remains for broad text routes.
3. Treat catalog model IDs as caller-facing logical names. The catalog's `providerId`, `apiModel`, `gatewayModel`, protocol and request schema control dispatch. Provider selection must not be inferred by parsing a model ID prefix.
4. Reuse the existing protocol adapters and request schemas for image generation/editing, asynchronous video (`/videos` or `/video/generations`), audio and embeddings. The gateway model sent on the wire comes from the resolved mapping.
5. Remove the local NewAPI control plane (setup, channel administration, SQLite data mount, provisioner endpoints and UI). Keep the application-owned settings database and third-party group configuration.
6. Update built-in media catalog labels/default values and documentation to use neutral names and the owned platform gateway. No legacy `newapi_*` project-value aliases are provided.

The platform's bundled model/capability catalog starts from the current checked-in `official_media_models.json`: preserve its upstream names and capability metadata while replacing the provider branding and prefixed logical IDs with neutral IDs. The repository has no credentialed live contract evidence for `api.aigcdo.top`, so this catalog is a request contract, not a claim that every model has been live-verified.

## Constraints and security

- Never send a platform key to a configured third-party Base URL or vice versa.
- Model IDs are user/configuration data; validate as non-empty bounded strings and reject ambiguous same-specificity group mappings instead of choosing nondeterministically.
- Third-party endpoint protocols remain explicit; do not infer Gemini or OpenAI protocol from a model name.
- Compose release and source builds must work without the sibling `dramaclaw-gateway` checkout or a `newapi-data` volume.

## Acceptance criteria

- Platform route resolution returns `https://api.aigcdo.top/v1` and the key saved through the platform settings path; changing the endpoint is not a user setting.
- The API never falls back from a missing platform key to the process NewAPI/RelayClaw environment variables in CE.
- Custom image and video logical IDs such as `poster-main` and `trailer-fast` appear unchanged in catalog rows and requests; their configured upstream names are what the wire payload uses.
- Video mappings preserve the selected async endpoint; image mappings preserve the selected edit format; Gemini groups retain native `v1beta` behavior; audio and embedding mapping tests stay green.
- No generated/default project model ID or runtime routing decision requires a `newapi_` prefix.
- CE Compose defines only API and web services and does not mount NewAPI's database or depend on a NewAPI checkout.
- Settings no longer expose RelayClaw registration or local NewAPI setup/channel-management controls; platform keys remain masked in responses.
- Python focused tests, frontend targeted tests/build, Compose contract tests and default pytest suite pass. Any unavailable frontend package manager or integration credentials are reported as verification gaps, not inferred passes.

## Rollout and data impact

- Existing user settings containing an old RelayClaw key are not copied to the new platform endpoint; the user must save the new key.
- Keep an existing RelayClaw key inert (never expose it as configured and never resolve it for requests) until the user saves the new platform key; then erase the old key in the same settings transaction.
- Existing project/model choices containing `newapi_*` are intentionally not migrated. Users must choose the desired model in each affected project.
- The bundled `newapi-data` volume is no longer consumed by the new release. This implementation must not delete user volumes; operators may back them up or remove them separately after upgrading.
- Rollback is application-image/Compose rollback. Reverting restores the old service definition but does not recover a removed volume; no volume deletion is part of this change.

## Open items for implementer

- Where the existing feature-model configuration UI relies on NewAPI admin APIs, remove that service-specific surface; ensure the retained model-group mapping interface still routes app task model aliases for all advertised capabilities.
- Do not claim live compatibility with `api.aigcdo.top` without credentials and a real API smoke test; unit/contract tests prove request construction only.

Implementation note: the current branch removes the bundled Compose service and keeps the legacy settings widgets/API intact to avoid silently breaking existing Custom/BrainClaw workflows. Removing or replacing those widgets is a follow-up UI/API operation requiring its own migration design and test coverage.
