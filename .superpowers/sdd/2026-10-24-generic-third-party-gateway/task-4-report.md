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
