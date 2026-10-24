# 虾集能力模型与 Claude 协议实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将虾集和主线文本模型从 `DC-*` 功能映射改为一次性能力默认模型配置，并补齐 Claude/Anthropic 原生协议与统一协议下拉 UI。

**Architecture:** 第三方网关组仍是唯一凭据和模型来源。功能只声明稳定的 feature ID 与 `text` 能力；运行时从能力默认组解析真实上游模型。OpenAI、Gemini、Anthropic 分别走各自协议适配器，旧 `DC-*` 只作为读取兼容别名。高级自定义改为操作 canonical third-party groups，不再访问 `/custom/newapi/*`。

**Tech Stack:** Python 3.11+/FastAPI/PydanticAI、React/TypeScript、TanStack Query、Radix UI Select、pytest、Vitest。

**Spec:** `docs/superpowers/specs/2026-10-24-capability-based-model-routing-design.md`

## Global Constraints

- 不恢复 NewAPI 管理 CRUD；高级自定义不得调用 `/custom/newapi/*`。
- 不删除旧设置、旧数据卷或旧 `DC-*` 数据；旧别名只读兼容，不作为新保存格式。
- 不新增独立 `vision` 能力；文本网关默认承担文本和视觉输入。
- 未配置官方网关时，不显示内置官方媒体模型。
- Claude 必须使用 Anthropic 原生鉴权和 Messages API，不得伪装成 OpenAI 协议。
- 协议菜单必须使用项目 Radix `Select` 组件，不使用原生 `<select>`。

## Review Focus

- 未映射的虾集文本任务必须自动复用已配置的文本默认组，并发送真实上游模型名；测试归属 Task 2。
- Claude 组必须发送 `x-api-key`/`anthropic-version`，不能发送 Bearer；测试归属 Task 3。
- 无 Embedding 组时只能提示未配置，不得用文本组冒充；测试归属 Task 2。
- 旧项目保存 `DC-*` 时读取仍能工作，新保存 payload 不包含 `DC-*`；测试归属 Task 2/4。
- 模型列表请求失败或未保存凭据时，按钮应显示明确状态而不是静默 disabled；测试归属 Task 4。

---

### Task 1: 固定虾集能力目录并移除前端 DC 显示

**Files:**
- Modify: `frontend/src/lib/feature-models.ts`
- Modify: `frontend/src/components/settings/settings-dialog.tsx`
- Modify: `frontend/src/lib/queries/model-gateway.ts`
- Test: `frontend/src/__tests__/stores/settings-store-feature-model-config.test.ts`
- Test: `frontend/src/__tests__/components/settings/settings-dialog.test.tsx`

**Interfaces:**
- Produces a capability-default settings view with `textModel`, optional `embeddingModel`, and media catalog references.
- Existing feature IDs remain stable; `requiresVision` is display metadata only and must not create a separate routing capability.

- [ ] **Step 1: Write the failing tests**
  - Assert the six 虾集 product features are listed once: translation, text writer, story script, recipe compiler, text vision, staging prop.
  - Assert the UI displays configured upstream model names, not `DC-*` aliases.
  - Assert old `DC-*` state is normalized into the capability default without being emitted in a new save payload.
- [ ] **Step 2: Run the focused Vitest tests and verify RED**
  - Run: `corepack pnpm exec vitest run src/__tests__/stores/settings-store-feature-model-config.test.ts src/__tests__/components/settings/settings-dialog.test.tsx`
  - Expected: failures show fixed feature models still expose `DC-*` and the old provider-channel block remains mounted.
- [ ] **Step 3: Implement the capability model catalog**
  - Add stable capability metadata for `text`, `embedding`, `image`, `video`, and `audio`.
  - Keep feature IDs and labels, but stop treating `defaultModel` as a user-editable upstream model.
  - Render one text default selector and one embedding selector; media selectors continue using canonical media catalogs.
- [ ] **Step 4: Run focused tests and verify GREEN**
- [ ] **Step 5: Commit**
  - `git commit -m "refactor(settings): define capability defaults without DC aliases"`

### Task 2: Backend capability resolution and DC compatibility

**Files:**
- Modify: `src/novelvideo/model_gateway_settings.py`
- Modify: `src/novelvideo/config.py`
- Modify: `src/novelvideo/official_defaults.py`
- Modify: `src/novelvideo/api/routes/model_gateway.py`
- Test: `tests/test_model_gateway_settings.py`
- Test: `tests/test_brainclaw_contract.py`
- Test: `tests/test_agent_llm_config.py`

**Interfaces:**
- Add a resolver with the effective behavior of `resolve_capability_default(capability: str) -> EffectiveGatewayConfig | None`.
- Add a compatibility resolver that accepts old logical aliases but returns the configured upstream model and credentials.
- Keep `get_effective_llm_config(model=...)` as the runtime boundary used by existing callers.

- [ ] **Step 1: Write failing tests**
  - Multiple text groups with only one generic default must route every unmapped text feature to that group.
  - A configured text group with `gpt-6.1-sol` must make `EPISODE_PROP_PLANNER` send `gpt-6.1-sol`, never `DC-episode-prop-planner-LLM`.
  - New capability-default settings serialize only group/model references, not `DC-*` mappings.
  - Missing embedding group returns a structured not-configured result.
- [ ] **Step 2: Run RED**
  - Run: `uv run pytest tests/test_model_gateway_settings.py tests/test_brainclaw_contract.py tests/test_agent_llm_config.py -q`
- [ ] **Step 3: Implement resolution**
  - Resolve exact feature mappings first, then the configured text default group, then fail with a capability-specific error.
  - Map legacy `DC-*` values at the boundary only.
  - Remove the need for users to define every feature alias.
- [ ] **Step 4: Run GREEN**
- [ ] **Step 5: Commit**
  - `git commit -m "fix(gateway): resolve feature routes from capability defaults"`

### Task 3: Add the Anthropic/Claude native protocol adapter

**Files:**
- Create: `src/novelvideo/model_gateway_protocols.py`
- Modify: `src/novelvideo/model_gateway_settings.py`
- Modify: `src/novelvideo/config.py`
- Modify: `src/novelvideo/api/routes/model_gateway.py`
- Modify: `frontend/src/lib/queries/model-gateway.ts`
- Test: `tests/test_model_gateway_protocols.py`
- Test: `tests/test_model_gateway_settings.py`

**Interfaces:**
- Protocol union becomes `openai | gemini | anthropic`.
- Add protocol helpers for base URL normalization, model listing, and request credential headers.
- The text model factory selects the native Anthropic provider when `protocol == "anthropic"`; OpenAI/Gemini behavior remains unchanged.

- [ ] **Step 1: Write failing tests**
  - Validate and save an Anthropic group.
  - Fetch models from an Anthropic-compatible `/v1/models` response.
  - Assert request headers include `x-api-key` and `anthropic-version`, with no `Authorization: Bearer` header.
  - Assert a Claude text model reaches the native Messages provider with the configured upstream model name.
  - Reject Anthropic groups configured for unsupported media generation capabilities in the current scope.
- [ ] **Step 2: Run RED**
  - Run: `uv run pytest tests/test_model_gateway_protocols.py tests/test_model_gateway_settings.py -q`
- [ ] **Step 3: Implement native adapter**
  - Default base URL: `https://api.anthropic.com`.
  - Use configurable Base URL for compatible gateways.
  - Preserve masked-key behavior and never return full keys.
  - Keep protocol-specific model discovery behind one backend route.
- [ ] **Step 4: Run GREEN**
- [ ] **Step 5: Commit**
  - `git commit -m "feat(gateway): add native Anthropic Claude protocol"`

### Task 4: Replace Advanced Custom NewAPI channel UI and align protocol menus

**Files:**
- Modify: `frontend/src/components/settings/settings-dialog.tsx`
- Modify: `frontend/src/lib/queries/model-gateway.ts`
- Modify: `frontend/public/locales/zh/translation.json`
- Modify: `frontend/public/locales/en/translation.json`
- Test: `frontend/src/__tests__/components/settings/settings-dialog.test.tsx`
- Test: `frontend/src/__tests__/lib/queries/model-gateway.test.tsx`

**Interfaces:**
- Advanced Custom saves through canonical third-party group mutation only.
- Protocol selection uses the existing Radix `Select` primitives and supports OpenAI, Gemini, and Anthropic.
- Model discovery uses the selected group’s protocol and is enabled when the group has a saved key or an explicitly entered key.

- [ ] **Step 1: Write failing tests**
  - Advanced Custom does not render `ProviderChannelsBlock`, `FeatureModelsBlock`, or NewAPI channel buttons.
  - Saving a Claude group calls the third-party group endpoint with `protocol: "anthropic"`.
  - The protocol menu renders as a project Select component with all three options.
  - Fetch-models is not disabled merely because there is no legacy provisioner channel; it is disabled only while loading or when Base URL/key are genuinely missing.
  - Error response from model discovery is shown to the user.
- [ ] **Step 2: Run RED**
  - Run: `corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx src/__tests__/lib/queries/model-gateway.test.tsx`
- [ ] **Step 3: Implement UI migration**
  - Remove old NewAPI channel save/sync/fetch hooks from Advanced Custom.
  - Add capability-default controls using groups and real upstream model choices.
  - Replace native `<select>` protocol and endpoint selectors with Radix Select styling.
- [ ] **Step 4: Run GREEN**
- [ ] **Step 5: Commit**
  - `git commit -m "fix(settings): make Advanced Custom use third-party groups"`

### Task 5: End-to-end verification and rollout

**Files:**
- Modify: `docs/superpowers/specs/2026-10-24-capability-based-model-routing-design.md`
- Test: existing backend and frontend suites

- [ ] **Step 1: Run targeted backend tests**
  - `uv run pytest tests/test_model_gateway_settings.py tests/test_brainclaw_contract.py tests/test_model_gateway_protocols.py tests/test_newapi_image_gateway.py -q`
- [ ] **Step 2: Run targeted frontend tests and build**
  - `corepack pnpm exec vitest run src/__tests__/components/settings/settings-dialog.test.tsx src/__tests__/lib/queries/model-gateway.test.tsx`
  - `corepack pnpm exec tsc --noEmit`
  - `corepack pnpm build:ce`
- [ ] **Step 3: Run full suites**
  - `uv run pytest -q`
  - `corepack pnpm exec vitest run`
- [ ] **Step 4: Run live smoke checks**
  - Verify `/api/v1/model-gateway/config`.
  - Verify third-party group model discovery for OpenAI, Gemini, and Anthropic protocols.
  - Verify an unmapped虾集 text route resolves to the configured text upstream model.
  - Verify no `LingShan-*` or `DC-*` values are exposed in the new frontend model options.
- [ ] **Step 5: Commit and deploy**
  - `git diff --check`
  - Rebuild API/Web without deleting data volumes.
