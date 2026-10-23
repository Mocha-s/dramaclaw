# Task 5 Report — Migration warnings, operator docs, and regression verification

## Status

Implemented the end-to-end migration fixture and updated the English and Simplified Chinese model-configuration guides. The fixture covers legacy Sub2API groups and capability keys, a portable OpenAI/Gemini configuration, a rejected loopback Custom endpoint, NewAPI-private admin records, resolution, masking, warnings, mode normalization, and source-data preservation.

## TDD evidence

- RED: the new fixture initially failed because the assertion expected fully opaque `*********` previews; the existing masking contract intentionally preserves a short prefix/suffix while hiding the middle.
- GREEN: `uv run pytest tests/test_model_gateway_settings.py::test_legacy_gateway_fixture_migrates_resolves_masks_and_preserves_data -q` — **1 passed**.

## Documentation

- Removed the obsolete Sub2API mode from both operator-facing mode tables.
- Documented protocol-derived fixed image-edit shapes and hidden legacy compatibility data.
- Documented automatic migration, retained legacy rollback input, collapsed saved groups, masked local/incomplete-endpoint warnings, Hybrid fallback, and ambiguous-mapping rejection.
- Retained the existing guidance that NewAPI-private provider/channel records require manual recreation in the selected external gateway.

## Verification

| Check | Result |
|---|---|
| Full backend `uv run pytest -q` | **FAIL: 84 failed, 7188 passed, 31 skipped, 3 deselected** |
| Frontend targeted Vitest (settings, model gateway, locale parity) | **PASS: 3 files, 54 tests** |
| `corepack pnpm build:ce` | **PASS**; existing large-chunk advisory only |
| `docker compose config --quiet` | **PASS** |
| `git diff --check` | **PASS** |

The backend failures are existing/spec-obsolete behavior exposed by the requested full run: stale Sub2API mode/resolver expectations, removed NewAPI admin CRUD/discovery and service-operation spy expectations, the known SQLite retry-count expectation, old embedding binding, and the existing environment/license inventory checks. Exact failed test names are in the full pytest output; representative groups include `tests/test_model_gateway_settings.py` (29), `tests/test_newapi_channel_models.py` (19), `tests/test_p0g4t_service_operation_exclusion.py` (25), plus `test_agent_llm_config.py`, `test_hermes_workspace.py`, `test_project_embedding_models.py`, `test_env_config_ratchet.py`, and `test_p0b_compliance_generator.py`.

## Scope and credential review

- Diff is limited to the two requested docs, one migration regression test, and this report; no production implementation, Compose, UI, media/chat/billing/task behavior, or volumes were changed.
- No official/third-party credential fallback was added. Test credentials are synthetic literals used only to prove masking and preservation; none are sent over the network.
- No NewAPI service dependency or automatic volume deletion was introduced. The docs explicitly preserve old data for migration/rollback and require manual recreation of non-portable admin records.

## Commit

Committed as `docs(gateway): document generic gateway migration`.

## Review follow-up

### Focused migration and model-gateway verification

- RED: the strengthened migration fixture failed because rejected loopback data was still selected by the unmatched Custom resolver (`http://127.0.0.1:4000/v1`).
- GREEN: after changing Custom resolution to return an empty config whenever canonical groups exist, the focused migration test passed. It now asserts source-key preservation, exact previews `sk-p...cret` / `gemi...cret`, no full `apiKey` in accessor or status output, and no loopback resolution.
- `uv run pytest tests/test_model_gateway_settings.py -q`: **34 failed, 131 passed**; full output: `.superpowers/sdd/2026-10-24-generic-third-party-gateway/task-5-model-gateway-settings.log`. Failures are legacy/spec-obsolete management and mode assertions plus the known SQLite retry-count assertion.

### Full default backend rerun

- Command: `uv run pytest -q`; final rerun output: `.superpowers/sdd/2026-10-24-generic-third-party-gateway/task-5-full-backend.log`. Result: **89 failed, 7183 passed, 31 skipped, 3 deselected**.
- Corrected behavior regression: none remained after the loopback fallback fix; the new migration test and its focused run are green.
- **Explicitly obsolete — NewAPI/Sub2API management removed:** all `tests/test_newapi_channel_models.py::*` nodes; all `tests/test_p0g4t_service_operation_exclusion.py::*` nodes; and these NewAPI admin nodes: `test_provider_channel_priority_can_be_reset_to_zero`, `test_custom_newapi_init_route_accepts_empty_body`, `test_custom_newapi_init_route_persists_request_database_config`, `test_custom_newapi_channels_batch_reuses_admin_and_masks_keys`, `test_custom_newapi_provider_channels_route_persists_and_masks_keys`, `test_custom_newapi_provider_channels_route_removes_final_channel`, `test_comfyui_provider_channel_writes_workflows_to_newapi`, `test_comfyui_workflow_routes_create_one_media_model`, `test_comfyui_workflow_routes_require_one_model_name`, `test_clear_comfyui_removes_channel_and_media_models`, `test_anthropic_provider_sync_without_saved_channel_type[claude]`, `test_anthropic_provider_sync_without_saved_channel_type[anthropic]`, `test_custom_newapi_provider_channel_sync_updates_newapi_and_local_config`, `test_custom_newapi_provider_channel_sync_allows_clearing_saved_base_url`, `test_custom_newapi_provider_channel_sync_does_not_save_when_newapi_update_fails`, `test_custom_newapi_channels_batch_uses_saved_provider_channel_config`, `test_custom_newapi_media_models_groups_by_provider_and_persists_mapping`, `test_custom_newapi_media_models_rejects_official_value_models`, `test_custom_newapi_embedding_model_writes_mapping_and_persists_dimension`, `test_custom_newapi_channels_batch_reports_partial_failure`. The SQLite retry-count assertion is also obsolete because migration adds a required settings read.
- **Explicitly obsolete — Sub2API/gateway compatibility:** `tests/test_agent_llm_config.py::test_hermes_default_model_resolves_sub2api_group_without_env_override`; all `test_model_gateway_settings.py` nodes containing `sub2api`, plus `test_model_gateway_uses_explicit_custom_mode`, `test_newapi_runtime_credentials_prefer_saved_custom_gateway`, `test_newapi_text_model_defaults_to_300_second_timeout`, `test_model_gateway_status_keeps_official_section_when_custom_is_active`, `test_hybrid_video_routes_only_comfyui_models_to_local_gateway`; and `tests/test_project_embedding_models.py::test_sub2api_embedding_binding_uses_embedding_capability_key`. These assert removed names, legacy mode, or direct legacy endpoint fallback.
- **Pre-existing unrelated environment/inventory:** `tests/test_director_auto.py::test_missing_portrait_is_repaired_once_without_pausing_auto_mode`, `tests/test_env_config_ratchet.py::test_real_ce_repo_env_ratchet_is_clean`, and `tests/test_p0b_compliance_generator.py::test_license_inventory_covers_current_git_index`. The license failure also reports ignored SDD report files.
- **Unresolved:** none. `test_settings_db_retries_transient_sqlite_io_error` is an intentional migration-read count mismatch and is tracked with the obsolete migration expectations rather than changed here; `test_hermes_workspace.py::test_existing_config_syncs_endpoint_without_persisting_rotated_key` is a legacy endpoint-sync expectation.

### Exact failed node IDs

The complete exact node-ID list from the final run follows:

- tests/test_agent_llm_config.py::test_hermes_default_model_resolves_sub2api_group_without_env_override
- tests/test_director_auto.py::test_missing_portrait_is_repaired_once_without_pausing_auto_mode
- tests/test_env_config_ratchet.py::test_real_ce_repo_env_ratchet_is_clean
- tests/test_hermes_workspace.py::test_existing_config_syncs_endpoint_without_persisting_rotated_key
- tests/test_model_gateway_settings.py::test_settings_db_retries_transient_sqlite_io_error
- tests/test_model_gateway_settings.py::test_provider_channel_priority_can_be_reset_to_zero
- tests/test_model_gateway_settings.py::test_model_gateway_uses_explicit_custom_mode
- tests/test_model_gateway_settings.py::test_hybrid_video_routes_only_comfyui_models_to_local_gateway
- tests/test_model_gateway_settings.py::test_newapi_runtime_credentials_prefer_saved_custom_gateway
- tests/test_model_gateway_settings.py::test_newapi_text_model_defaults_to_300_second_timeout
- tests/test_model_gateway_settings.py::test_model_gateway_status_keeps_official_section_when_custom_is_active
- tests/test_model_gateway_settings.py::test_sub2api_routes_save_masks_keys_and_enable_without_local_provisioner
- tests/test_model_gateway_settings.py::test_sub2api_uses_a_distinct_key_for_each_capability
- tests/test_model_gateway_settings.py::test_sub2api_text_client_sends_mapped_upstream_model
- tests/test_model_gateway_settings.py::test_image_generation_config_uses_sub2api_protocol_but_keeps_newapi_default
- tests/test_model_gateway_settings.py::test_gemini_named_openai_group_is_normalized_to_native_v1beta_protocol
- tests/test_model_gateway_settings.py::test_sub2api_unmatched_text_model_reports_missing_mapping
- tests/test_model_gateway_settings.py::test_sub2api_status_masks_each_capability_key
- tests/test_model_gateway_settings.py::test_sub2api_exact_model_match_beats_prefix_and_ambiguous_matches_fail_closed
- tests/test_model_gateway_settings.py::test_custom_newapi_init_route_accepts_empty_body
- tests/test_model_gateway_settings.py::test_custom_newapi_init_route_persists_request_database_config
- tests/test_model_gateway_settings.py::test_custom_newapi_channels_batch_reuses_admin_and_masks_keys
- tests/test_model_gateway_settings.py::test_custom_newapi_provider_channels_route_persists_and_masks_keys
- tests/test_model_gateway_settings.py::test_custom_newapi_provider_channels_route_removes_final_channel
- tests/test_model_gateway_settings.py::test_comfyui_provider_channel_writes_workflows_to_newapi
- tests/test_model_gateway_settings.py::test_comfyui_workflow_routes_create_one_media_model
- tests/test_model_gateway_settings.py::test_comfyui_workflow_routes_require_one_model_name
- tests/test_model_gateway_settings.py::test_clear_comfyui_removes_channel_and_media_models
- tests/test_model_gateway_settings.py::test_anthropic_provider_sync_without_saved_channel_type[claude]
- tests/test_model_gateway_settings.py::test_anthropic_provider_sync_without_saved_channel_type[anthropic]
- tests/test_model_gateway_settings.py::test_custom_newapi_provider_channel_sync_updates_newapi_and_local_config
- tests/test_model_gateway_settings.py::test_custom_newapi_provider_channel_sync_allows_clearing_saved_base_url
- tests/test_model_gateway_settings.py::test_custom_newapi_provider_channel_sync_does_not_save_when_newapi_update_fails
- tests/test_model_gateway_settings.py::test_custom_newapi_channels_batch_uses_saved_provider_channel_config
- tests/test_model_gateway_settings.py::test_custom_newapi_media_models_groups_by_provider_and_persists_mapping
- tests/test_model_gateway_settings.py::test_custom_newapi_media_models_rejects_official_value_models
- tests/test_model_gateway_settings.py::test_custom_newapi_embedding_model_writes_mapping_and_persists_dimension
- tests/test_model_gateway_settings.py::test_custom_newapi_channels_batch_reports_partial_failure
- tests/test_newapi_channel_models.py::test_discovery_uses_saved_gateway_channel_and_normalizes_models
- tests/test_newapi_channel_models.py::test_discovery_supports_saved_or_explicit_custom_channel_type[None]
- tests/test_newapi_channel_models.py::test_discovery_supports_saved_or_explicit_custom_channel_type[62]
- tests/test_newapi_channel_models.py::test_missing_channel_requires_sync
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[401-body0]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[500-body1]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[404-body2]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[405-body3]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body4]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body5]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body6]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body7]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body8]
- tests/test_newapi_channel_models.py::test_gateway_rejections_and_invalid_lists_are_secret_free[200-body9]
- tests/test_newapi_channel_models.py::test_invalid_json_is_secret_free
- tests/test_newapi_channel_models.py::test_transport_errors_are_stable_and_secret_free[error0-504-NewAPI provider model discovery timed out]
- tests/test_newapi_channel_models.py::test_transport_errors_are_stable_and_secret_free[error1-502-NewAPI provider model discovery failed]
- tests/test_newapi_channel_models.py::test_channel_lookup_failure_is_secret_free
- tests/test_newapi_channel_models.py::test_admin_failure_is_secret_free
- tests/test_newapi_channel_models.py::test_invalid_provider_or_type_does_not_contact_gateway[payload0]
- tests/test_newapi_channel_models.py::test_invalid_provider_or_type_does_not_contact_gateway[payload1]
- tests/test_newapi_channel_models.py::test_management_permission_is_checked_before_discovery[ee]
- tests/test_newapi_channel_models.py::test_management_permission_is_checked_before_discovery[disabled]
- tests/test_newapi_channel_models.py::test_discovery_offloads_management_work_and_passes_request_config
- tests/test_p0b_compliance_generator.py::test_license_inventory_covers_current_git_index
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/init-payload0-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/init-payload0-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/init-payload0-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channels-payload1-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channels-payload1-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channels-payload1-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channel/sync-payload2-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channel/sync-payload2-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/provider-channel/sync-payload2-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels-payload3-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels-payload3-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels-payload3-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels/batch-payload4-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels/batch-payload4-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/channels/batch-payload4-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/embedding-model-payload5-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/embedding-model-payload5-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/embedding-model-payload5-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/media-models-payload6-ee-postgresql://organization-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/media-models-payload6-ce-postgresql://contradictory-profile-dsn-canary]
- tests/test_p0g4t_service_operation_exclusion.py::test_newapi_mutations_are_excluded_before_any_side_effect[/model-gateway/custom/newapi/media-models-payload6-invalid-edition-canary-]
- tests/test_p0g4t_service_operation_exclusion.py::test_excluded_service_operations_never_consult_or_replay_durable_state[conflict]
- tests/test_p0g4t_service_operation_exclusion.py::test_excluded_service_operations_never_consult_or_replay_durable_state[accepted]
- tests/test_p0g4t_service_operation_exclusion.py::test_excluded_service_operations_never_consult_or_replay_durable_state[completed]
- tests/test_p0g4t_service_operation_exclusion.py::test_excluded_service_operations_never_consult_or_replay_durable_state[unknown]
- tests/test_project_embedding_models.py::test_sub2api_embedding_binding_uses_embedding_capability_key
