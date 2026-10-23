# Final Fix Report — Generic Third-Party Gateway

Date: 2026-10-24

## Scope

Fixed the two final-review regressions in the legacy Custom compatibility path:

1. A valid external `save_custom_newapi_gateway()` save now creates/replaces the canonical `legacy-custom-newapi` third-party group, so an existing empty `third_party_gateway_groups` value cannot shadow the newly saved endpoint. Legacy `custom_newapi_*` settings remain persisted for rollback/audit.
2. If legacy migration fails before establishing canonical groups, Custom resolution refuses to use preserved legacy URL/key values. The values remain stored for rollback, but uncertain or local/container endpoints cannot become runtime credentials.

Loopback/private/incomplete compatibility saves remain fail-closed: they do not create a canonical group.

## TDD evidence

### RED

Added:

- `test_legacy_custom_save_updates_empty_canonical_groups`
- `test_malformed_legacy_migration_cannot_resolve_preserved_custom_endpoint`

Before the production fix:

```text
2 failed, 165 deselected
```

The first observed `effective` result was `('custom', '', '')` instead of the canonical external group. The second resolved `http://127.0.0.1:4000/v1` with `local-secret` instead of refusing.

### GREEN

```text
uv run pytest tests/test_model_gateway_settings.py -q -k 'legacy_custom_save_updates_empty_canonical_groups or malformed_legacy_migration_cannot_resolve_preserved_custom_endpoint or custom_newapi_external_endpoint_migrates_but_loopback_does_not or malformed_canonical_groups_are_preserved_and_retryable'
4 passed, 163 deselected

uv run pytest tests/test_hermes_workspace.py -q -k 'existing_config_syncs_endpoint_without_persisting_rotated_key or hermes_uses_settings_db_newapi_before_root_env'
2 passed, 62 deselected
```

Compile and diff checks:

```text
uv run python -m compileall -q src tests/test_model_gateway_settings.py tests/test_hermes_workspace.py  # passed
git diff --check  # passed
```

## Full module status / concerns

The requested full command was run:

```text
uv run pytest tests/test_model_gateway_settings.py -q
```

Result: `133 passed, 34 failed, 8 warnings`.

The failures are branch expectations for removed/deprecated bundled NewAPI administration and old Sub2API/loopback behavior (including 410 responses and expectations that local endpoints resolve). They are outside this fix and conflict with the current canonical third-party/legacy fail-closed contract. The focused migration, compatibility, and Hermes workspace regressions are green.
