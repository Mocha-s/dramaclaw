# Task 1 Report — Canonical third-party settings and safe migration

## Status

Implemented canonical third-party gateway group storage and CE migration in `src/novelvideo/model_gateway_settings.py`, with focused migration coverage in `tests/test_model_gateway_settings.py`.

## What changed

- Added `get_third_party_gateway_groups()` and `save_third_party_gateway_groups()`.
- Added versioned, idempotent SQLite migration with an atomic transaction.
- Migrates Sub2API groups and legacy per-capability keys without deleting source settings.
- Normalizes legacy `sub2api` mode to `custom`.
- Migrates only external HTTP(S) Custom endpoints; rejects loopback/container-local endpoints.
- Preserves legacy image-edit metadata and leaves NewAPI admin-plane data untouched.
- Adds non-secret migration warnings to gateway status and masked canonical group output.
- Existing canonical settings take precedence and are never overwritten.

## Verification

- RED: initial focused run failed during collection due a test fixture syntax typo; after correction, the new migration tests failed with missing canonical APIs/status fields as expected.
- GREEN: `uv run pytest tests/test_model_gateway_settings.py -q -k 'third_party_groups or third_party_migration or custom_newapi_external or migration_warning'` — 4 passed.
- GREEN: `uv run python -m compileall -q src/novelvideo/model_gateway_settings.py`.
- GREEN: `git diff --check`.

## Concerns

The existing focused suite contains legacy assertions expecting `sub2api` to remain the active mode and old resolver precedence; those assertions conflict with the approved migration policy and are not changed outside Task 1's new migration coverage.

## Commit

Committed as `46a3ce0c` (`refactor(gateway): migrate to generic third-party settings`).

## Review fixes

- Added regression coverage for malformed canonical JSON preservation/retryability, canonical runtime resolution, legacy `sub2api` mode normalization, and private/loopback IPv4/IPv6 rejection.
- RED: the three review-fix tests initially failed: malformed canonical data produced no warning, canonical groups were ignored by runtime resolution, and legacy mode resolved through the old path.
- GREEN: focused review-fix run passed 7 tests.
- Full requested run: `uv run pytest tests/test_model_gateway_settings.py -q` — 138 passed, 10 legacy assertions failed because they require the superseded `sub2api` active mode/old resolver behavior; one existing SQLite retry assertion also observes the additional required migration read.
- The review fixes are committed in the follow-up commit below.
