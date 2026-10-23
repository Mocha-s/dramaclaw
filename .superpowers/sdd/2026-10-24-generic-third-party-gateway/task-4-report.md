# Task 4 report — Generic gateway settings UI

## Status
Implemented and committed the generic third-party gateway settings surface.

## RED evidence
Ran from `frontend`:

```text
corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx src/__tests__/lib/queries/model-gateway.test.tsx
```

The first test-first run failed as expected: `useSaveThirdPartyGatewayConfig` did not exist and the obsolete `Sub2API` tab was still rendered.

## GREEN evidence
Targeted verification:

```text
corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx src/__tests__/lib/queries/model-gateway.test.tsx src/__tests__/i18n/locales-json.test.ts
# 3 files passed, 51 tests passed

corepack pnpm build:ce
# build completed successfully

corepack pnpm exec tsc --noEmit
# completed successfully

git diff --check
# clean
```

## Changes
- Added canonical third-party gateway types and generic config/model-discovery mutation hooks using `/third-party/*` routes.
- Kept legacy `sub2api` response fallback parsing for migration compatibility.
- Moved group editing into Custom and Hybrid; removed the standalone Sub2API tab from the rendered UI.
- Added independent accessible disclosures, saved groups collapsed by default, and newly added groups expanded.
- Kept API key previews masked, surfaced top-level migration warnings, retained video endpoint selection, and removed image-edit-format writes/control.
- Updated en/zh/vi locale keys and frontend regression tests.

## Concerns
- Legacy NewAPI implementation components remain exported but are no longer rendered by this settings path, preserving unrelated code while avoiding visible NewAPI administration controls.
- The canonical `ModelGatewayConfig` type retains legacy fields for compatibility with older responses.

## Review-fix pass (TDD)

### RED evidence
Added regression tests for the review findings and ran:

```text
corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx
```

The new tests initially failed because Custom no longer rendered the BrainClaw/advanced LLM and provider feature-model surfaces, and disclosure keyboard activation did not update the controlled state. The generic fallback-ID test also guarded against any new `sub2api-` prefix.

### GREEN evidence
After restoring the valid Custom/Hybrid composition and replacing the mixed `<details>` implementation with a single controlled button/conditional-content disclosure:

```text
corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx src/__tests__/lib/queries/model-gateway.test.tsx src/__tests__/i18n/locales-json.test.ts
# 3 files passed, 54 tests passed

corepack pnpm build:ce
# completed successfully

corepack pnpm exec tsc --noEmit
# completed successfully

git diff --check
# clean
```

### Review fixes
- Restored Custom BrainClaw and Advanced Custom LLM tabs; Advanced mode retains the provider feature-model settings surface. Hybrid also retains the provider feature-model settings surface alongside Official and third-party groups.
- Replaced native-details-plus-parent-state with one controlled `button[aria-expanded]` state authority. Enter and Space keyboard activation are explicitly handled and tested independently across multiple groups.
- Added/retained Vietnamese third-party gateway translations and kept locale key parity green.
- Kept NewAPI-specific initialization/channel-admin components out of the generic rendered path while retaining unrelated feature-model functionality.
- Changed generated group fallback IDs from `sub2api-*` to `third-party-*`.
