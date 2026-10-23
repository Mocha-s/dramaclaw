# Final backend suite contract-fix report

Date: 2026-10-24

## Root cause

The remaining failures were stale tests asserting removed Sub2API mode names, removed NewAPI admin/discovery CRUD, removed service-operation spy symbols, and obsolete environment/license inventory assumptions. Production routing already returned the approved generic contract and legacy admin routes returned HTTP 410.

## TDD evidence

- RED: the supplied final-suite output reproduced the stale assertions, including `MODE_SUB2API` vs `custom`, removed route-module monkeypatch targets, NewAPI discovery expectations, four missing legacy provisioner env reads, and six tracked generated reports.
- GREEN: focused affected suite passed after changing only test contracts/ratchets and removing the six report files from the Git index.

## Verification evidence

- `uv run pytest tests/test_model_gateway_settings.py tests/test_newapi_channel_models.py tests/test_p0g4t_service_operation_exclusion.py tests/test_agent_llm_config.py tests/test_project_embedding_models.py tests/test_env_config_ratchet.py tests/test_p0b_compliance_generator.py -q` — 206 passed.
- `uv run pytest -q` — **7195 passed, 31 skipped, 3 deselected**, 835 warnings, exit 0; runtime 409.48s.
- `uv run pytest tests/test_env_config_ratchet.py::test_real_ce_repo_env_ratchet_is_clean tests/test_p0b_compliance_generator.py::test_license_inventory_covers_current_git_index -q` — 2 passed.
- `docker compose config --quiet` — passed.
- `git diff --check` — passed.

No production routing, bundled NewAPI, or approved gateway behavior was changed. The six generated `.superpowers/sdd/.../*-report.md` files remain locally available but are removed from the Git index.
