# Task 3 Report: Remove bundled NewAPI deployment dependency

## Result

Removed the bundled NewAPI service from source and release CE Compose. Both Compose variants now deploy only `api` and `web`; the API has no NewAPI service dependency, provisioning/admin environment, or NewAPI data mount. `ce-data` remains configured and no volume deletion/pruning was added. The legacy settings database keys and any existing `newapi-data` volume contents were not modified.

Updated the Compose contract tests and `.env.example`; refreshed deployment and gateway setup guidance in the English and Chinese docs and README translations to use externally configured third-party gateways.

## TDD evidence

**RED**, before changing Compose definitions:

```text
uv run pytest tests/test_docker_persistence_config.py -q
4 failed, 11 passed
```

The expected failures detected `newapi` in service sets, NewAPI provisioner environment on `api`, and the `newapi-data` volume.

**GREEN**, after implementation and again after commit:

```text
uv run pytest tests/test_docker_persistence_config.py -q
15 passed
```

## Verification

- `docker compose config --quiet` — passed.
- `docker compose -f docker-compose.release.yml config --quiet` — passed.
- `git diff --check` — passed.
- Working tree clean after commit.

## Commit

`2ff7be03 refactor(deploy): remove bundled NewAPI service`

## Notes

The retained `newapi-data` volume is orphaned from the normal Compose configuration by design and remains untouched for manual recovery or rollback. Existing legacy settings database keys remain in place.

## Documentation drift follow-up

Rewrote English and Chinese self-hosting guidance to describe the two-service `api`/`web` CE stack, external OpenAI-compatible or Gemini-compatible gateway configuration, and the legacy `newapi-data` volume as retained outside normal Compose for manual recovery/rollback only. Repaired the English installation gateway section by removing the incomplete `docker run` example and sibling checkout directions. Aligned English/Chinese quickstarts and localized README deployment and provider snippets with the current Compose contract. Updated model configuration pages to remove bundled-service and provisioner storage claims.

Follow-up verification (fresh run before follow-up commit):

```text
git diff --check — passed
docker compose config --quiet — passed
uv run pytest tests/test_docker_persistence_config.py -q — 15 passed
```

## Documentation scoped re-review follow-up

Rewrote the remaining English and Chinese model-configuration sections to use generic third-party groups with explicit OpenAI/Gemini protocol selection, app-owned logical-model mappings, and independent provider guidance. The docs now state that NewAPI-specific admin CRUD, channel catalogs/synchronization, and root initialization are not portable and are not performed by CE. Updated troubleshooting and ComfyUI guidance without removing useful provider behavior.

Removed the obsolete port-3000 bundled-admin requirement and corrected network requirements in the root and localized READMEs. Audited the localized deployment snippets for three-service startup, bundled admin UI, sibling checkout, and stale port claims; corrected the remaining contradictions and repaired the Thai system-requirements link markup.

Fresh verification:

```text
git diff --check — passed
docker compose config --quiet — passed
uv run pytest tests/test_docker_persistence_config.py -q — 15 passed
targeted stale-instruction grep — no matches
```

## Documentation re-review follow-up

Updated the environment-variable references to describe external OpenAI/Gemini-compatible groups and clarify that legacy NewAPI-named variables are compatibility-only and do not add a service to CE Compose. Replaced English and Chinese troubleshooting advice about Local NewAPI services, runtime tokens, channel mappings, and admin settings with checks for Base URL, protocol, capabilities, model mappings, API keys, and container reachability. Explicitly documented that NewAPI-specific admin CRUD is not portable or supported by CE. Corrected the remaining architecture wording to remove the bundled-gateway implication.

Fresh verification:

```text
git diff --check — passed
uv run pytest tests/test_docker_persistence_config.py -q — 15 passed
docker compose config --quiet — passed
```

Targeted operator-doc grep found no bundled-service, three-service, sibling-checkout, port-3000-admin, or local-admin instructions. Remaining matches are explanatory compatibility/legacy notes and the clearly marked historical design/spec files, not setup instructions.
