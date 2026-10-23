# Task 2 Report — Custom/Hybrid resolution and generic management routes

## Outcome

- Added canonical third-party mapping resolution to Hybrid: selected most-specific group mapping wins; otherwise the official gateway credentials are returned. Mapping ties raise a clear `ValueError` rather than silently selecting a credential.
- Added `/model-gateway/third-party/config`, `/models`, and `/enable`; old `/sub2api/*` paths delegate to these handlers. Group keys are retained internally and masked in status responses.
- Custom and Hybrid activation checks require valid third-party groups; Hybrid also requires the official key. Generic group writes use the Task 1 accessor and new writes discard legacy image-edit selectors. Gemini/native and existing legacy runtime compatibility remain.
- Replaced legacy NewAPI admin handlers with a non-secret HTTP 410 “not portable” response.

## RED/GREEN evidence

- RED: `uv run pytest tests/test_model_gateway_settings.py tests/test_newapi_text_gateway.py tests/test_newapi_image_gateway.py -q` — new Hybrid-resolution assertion failed because Hybrid ignored third-party mappings; generic config returned 404. Existing suite also exposed stale mode and migration expectations.
- GREEN focused: `uv run pytest tests/test_model_gateway_settings.py::test_custom_resolution_uses_canonical_group tests/test_model_gateway_settings.py::test_hybrid_uses_most_specific_third_party_mapping_then_official tests/test_model_gateway_settings.py::test_generic_third_party_config_and_enable_routes_are_available tests/test_model_gateway_settings.py::test_legacy_sub2api_mode_resolves_through_canonical_custom_groups -q` — 4 passed.
- GREEN related request suites: `uv run pytest tests/test_model_gateway_settings.py::test_hybrid_uses_most_specific_third_party_mapping_then_official tests/test_model_gateway_settings.py::test_generic_third_party_config_and_enable_routes_are_available tests/test_newapi_text_gateway.py tests/test_newapi_image_gateway.py -q` — 79 passed.
- `git diff --check` and `python3 -m compileall -q src/novelvideo/model_gateway_settings.py src/novelvideo/api/routes/model_gateway.py` passed.
- Required broader command `uv run pytest tests/test_model_gateway_settings.py tests/test_newapi_text_gateway.py tests/test_newapi_image_gateway.py tests/test_freezone_image_backend.py -q` did not pass: stale tests still expect pre-spec `MODE_SUB2API` status and active NewAPI provisioner/channel CRUD behavior. It reported 37 failed / 482 passed, including expected incompatible legacy-route assertions; several resolver/runtime compatibility failures remain to investigate.

## Concerns

- The broader suite remains red and should be reconciled with the updated spec before merge. In particular old tests covering NewAPI provisioner handlers need replacement with explicit HTTP 410 assertions, while unrelated legacy runtime paths need their intended coverage preserved.
- Existing dependency deprecation warnings were emitted by installed Cognee/Pydantic/FastAPI code.

## Review fix pass

- Added Hybrid text/LLM mapping coverage and routed `get_effective_llm_config()` through the same canonical mapping resolver, with official fallback and no request retry behavior.
- Added exact-vs-extremely-long-prefix coverage; mapping precedence now uses ordered `(kind, specificity)` ranks so exact always wins.
- Added same-endpoint mapping rewrite coverage; hidden legacy `imageEditFormat` survives only when the mapping and protocol are unchanged, while rewritten mappings use protocol defaults.
- Audited base NewAPI admin routes: all ten existing `/custom/newapi/*` paths now have explicit HTTP 410 compatibility handlers/assertions. Generic discovery errors no longer mention Sub2API.
- RED: review-fix tests failed for Hybrid LLM routing, exact precedence, mapping rewrite cleanup, and generic error wording (route assertion invocation was also corrected before implementation verification).
- GREEN: focused review-fix tests passed: 14 passed. Direct affected gateway suites passed: `tests/test_newapi_text_gateway.py tests/test_newapi_image_gateway.py tests/test_freezone_image_backend.py` — 369 passed.
- Required broad command now reports 29 failures / 212 passed in the model-gateway-inclusive run; the 29 are spec-obsolete NewAPI admin CRUD/sync expectations (now intentionally 410), stale Sub2API mode expectations, and one pre-existing SQLite retry-count expectation changed by required migration reads. No failures occurred in the directly affected text/image/freezone suites.
