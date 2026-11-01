# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` at the repo root is the canonical contributor guide (structure, style, the Hermes sandbox
contract); this file complements it. Read `AGENTS.md` before touching `chat/`, `deploy/`, or sandbox code.

## What this is

DramaClaw Community Edition (package name `supertale-ce`, Python package `novelvideo`): a
single-machine "novel → finished short-drama video" pipeline. One FastAPI service (`:8780`) hosts
everything; tasks run in-process; state is SQLite + files on the local disk; all LLM / image / video /
audio inference goes through an **OpenAI-compatible gateway** (nothing runs models locally). Frontend
is a separate React SPA in `frontend/` (`:5173` dev, `:8080` in Docker).

Licensed **Elastic License 2.0 — source-available**. Never describe the project with the OSI term
(Chinese or English) in any tracked text: `scripts/lint_banned_words.py` fails CI on it. Add a
`banned-word-allow` marker to a line only for explanatory text that states what the project is *not*.

## Commands

### Backend (uv, Python 3.11–3.12)

```bash
uv sync --group dev                      # install runtime + dev deps from uv.lock
cp .env.example .env                     # then configure the gateway (see .env.example §1)
uv run novelvideo api --port 8780        # REST API (uvicorn, novelvideo.api.app:app)
scripts/start-ce.sh                      # API + bundled frontend together (installs Hermes)

uv run pytest -n auto                    # full suite (what CI runs); ee/e2e markers excluded by default
uv run pytest tests/test_api_assets.py   # one file
uv run pytest tests/test_api_assets.py::test_name -x   # one test
uv run pytest -m ee                      # enterprise-only tests (need control-plane modules)

uv run ruff check .                      # lint; rule set frozen to E4/E7/E9/F in pyproject
uv lock --check                          # CI fails if uv.lock is out of sync with pyproject
```

Other CLI subcommands live in `src/novelvideo/cli.py` (`import-novel`, `generate`,
`migrate-scene-names`, `repair-asset-names`, `backup ...`). Run `uv run novelvideo --help`.

### Frontend (pnpm 11.5.0, Node 22)

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev                 # Vite on :5173, proxies /api/v1 + /static to :8780
pnpm build               # tsc -b && vite build  (this IS the type check — CI runs it)
pnpm build:ce            # CE release bundle (loads .env.ce)
pnpm test                # vitest single run; pnpm test:watch for watch mode
pnpm vitest run src/lib/task-scope.test.ts   # one test file
```

### Repo-level gates (all run in CI; run the relevant ones before pushing)

```bash
python3 scripts/lint_ce_imports.py              # forbidden EE imports in src/ or pyproject
uv run python scripts/check_ce_port_closure.py  # every port resolves to novelvideo.ports.local.*
python3 scripts/lint_ee_terms.py                # forbidden package names in strings/docs/config
python3 scripts/ce_allowlist.py                 # validates ce-allowlist.toml (exemption registry)
python3 scripts/lint_banned_words.py            # OSI-licensing term in docs (see "What this is")
python3 scripts/check_backend_i18n.py           # hardcoded Chinese in backend user-facing copy
python3 scripts/check_frontend_i18n.py          # any CJK in frontend/src/*.ts(x)
uv run python scripts/check_workflow_agent_contracts.py --json
pre-commit run --all-files                      # gitleaks + banned-words
```

Every commit needs a DCO sign-off: `git commit -s`. CI rejects PRs with unsigned commits.

## Architecture

### Ports & Adapters: one codebase, two editions

The core rule of this repo: **CE code never imports EE code.** `src/novelvideo/ports/` defines
Protocol interfaces (auth, project_registry, project_access, task_backend, cancellation_store,
usage_meter, credit_quote, audit_sink, lifecycle, egress, model_credentials, …). CE default
implementations live in `ports/local/` (SQLite registry, inline task backend, no-op metering, etc.).
The commercial EE ships adapters for the same interfaces as a separate package registered via the
`novelvideo.ports_bootstrap` entry-point group.

- `ports/registry.py::ensure_bootstrap()` picks the edition: `ST_EDITION` (`ce`|`ee`), with
  `ST_CONTROL_PLANE_DSN` non-empty implying EE. CE + DSN together is a hard error.
- Business code obtains ports through the facade getters in `ports/__init__.py`
  (`get_task_backend()`, `get_project_registry()`, …), never by importing an implementation.
- Never import `novelvideo_ee`, `supertale_admin`, or `novelvideo.control_plane` — CI's <!-- banned-word-allow -->
  import-lint and ee-terms gates are hard-zero (no baseline). Exemptions for legitimate mentions go
  in `ce-allowlist.toml`.
- `tests/conftest.py` snapshots/restores the port registry around every test; if a test needs a
  different port implementation, `register_port()` it inside the test.

### Request flow

`api/app.py` builds the FastAPI app; `api/__init__.py` assembles `api_router` (prefix `/api/v1`)
from `api/routes/*.py`. A typical project-scoped handler:

1. `Depends(get_api_user)` (`api/auth.py`) — cookie-backed (`st_api_key`), local single user in CE.
2. `resolve_project_context(...)` (`project_context.py`) → a `ProjectContext` carrying
   `project_id`, owner, and the three per-project directories.
3. Short work runs inline; long work is enqueued via
   `get_task_backend().enqueue_project_task(ctx, task_type=..., product_surface=..., payload=...)`
   (`task_backend/client.py` is the facade). The route returns a task id and the frontend follows
   progress over SSE (`/api/v1/.../tasks/...`).

Keep handlers thin — reusable logic belongs in `services/`, `generators/`, or the relevant domain
package, not in `api/routes/`.

### Task execution

`task_backend/` is queue-agnostic: `producer.py` builds signed `TaskEnvelope`s (HMAC; CE
auto-generates a keyring under `NOVELVIDEO_STATE_DIR`), `consumer.py` validates them, and
`task_backend/runners/*.py` hold one runner per `task_type` (ingest, script, sketch, video, audio,
render, freezone, …). CE's `InlineTaskBackend` (`ports/local/tasks.py`) executes runners on
background threads with per-lane concurrency limits (`task_backend/limits.py`). Task rows and
progress live in the project's SQLite via `task_state.py` / `task_jobs.py`. There is no Celery/Redis
in CE even though those deps are installed; `ST_TASK_BACKEND` defaults to `celery` as a *name* but the
port registry decides what actually runs.

### Storage and directory layout

`config.py` resolves three roots from env (`NOVELVIDEO_DATA_ROOT` defaults to cwd):

- `state/<user>/<project>/data.db` — SQLite (`sqlite_store.py`, schema in `sqlite_schema.py`)
- `output/<user>/<project>/` — generated media and assets
- `runtime/<user>/<project>/` — scratch / worker workspaces

`shared/project_dirs.py::default_project_dirs()` is the single source of these paths. `.env` is
loaded by `env.py::load_project_dotenv()` with real environment taking priority over the file.

### Domain packages (what lives where)

| Package | Role |
|---|---|
| `cognee/` | Story knowledge graph — novel ingest, characters, scenes, timeline (Cognee + embeddings) |
| `agents/` | pydantic-ai agents: episode planner/reviewer/fixer, identity planners, prompt builders |
| `workflows/` | Script-writing workflows that chain agents |
| `generators/` | Image / TTS / video / compose adapters behind factory functions (`create_image_generator`, …) |
| `seedance2_i2v/` | Seedance 2.0 image-to-video asset manifests |
| `freezone/` | "XiaHua" infinite canvas — node graph generate/edit jobs, recipes, style templates |
| `director_world/` | 3D previz stage persistence (Python owns paths/schema/IO; the Vite editor is the live runtime) |
| `verification/` | Quality gates: sketch/keyframe fact-check, character consistency, render QA |
| `render_plan/`, `export/` | Final episode compose and deliverable export |
| `chat/` | "Xia Director" assistant: Hermes / Codex / Claude backends, MCP servers, event→UI presentation mapping |
| `backup/` | Project backup/restore CLI (`novelvideo backup`) |
| `security/`, `authz_retry.py`, `egress_context.py` | Admission, egress claims, credential resolution |

### Model gateway

Providers are configured in the UI (Settings → Model Config) and persisted to SQLite, which takes
precedence over `.env`. Three modes: **Official** (RelayClaw, `DC-*-LLM` logical model names, no
mapping), **Custom** (user's OpenAI/Gemini-compatible gateway groups), **Hybrid**.
`model_gateway_settings.py` / `model_gateway_runtime.py` resolve a *logical* model name
(e.g. `EPISODE_SCENE_PLANNER_MODEL=DC-episode-scene-planner-LLM`) to a concrete gateway + model id.
`official_media_models.json` is the shipped catalog for image/video/audio models.

`pydantic-ai-slim` is pinned to `==1.107.0` on purpose — 2.x removed `Agent(output_retries=...)`
which the agents use. Do not bump without migrating every agent.

### Chat backends and sandboxing

`chat/service.py::_chat_backend()` reads `DRAMACLAW_CHAT_BACKEND` (fallback
`SUPERTALE_CHAT_BACKEND`): `hermes` (default for source checkouts via `scripts/start-ce.sh`),
`codex` (default in Docker images), or `claude`. Hermes workers run under an OS sandbox; the
fail-closed / degrade rules and `SUPERTALE_ALLOW_UNSANDBOXED` are specified in `AGENTS.md` — read it
before changing `chat/hermes_*`, `deploy/`, or sandbox tests.

`.mcp.json` registers the `dramaclaw` MCP server (`novelvideo.chat.dramaclaw_mcp`) for local agent
use against a running API; `agent-kit/` is the redistributable Skill + MCP package for third-party
agents.

### Env var prefixes

Three generations coexist: `NOVELVIDEO_*` (dirs, host/port), `SUPERTALE_*` / `ST_*` (edition,
control plane, sandbox, task backend), `DRAMACLAW_*` (newest: chat backend, image/version, local
agent trust). When reading a setting, check for an existing alias chain (e.g. `DRAMACLAW_X` →
`SUPERTALE_X`) before adding a new name. `docs/en/reference/environment-variables.md` is the
reference; `.env.example` is heavily commented.

## Conventions that CI enforces (beyond ruff)

- **Backend i18n**: any Chinese that reaches the frontend via `current_task=`, `logs=[...]`,
  `report()/update_progress()/log()` args, or a response `"message"` must be wrapped in
  `lmsg("<code>", "<中文>", **params)` (`i18n_message.py`) and the code added to
  `frontend/public/locales/{zh,en}/translation.json`. The allowlist in
  `scripts/backend_i18n_allowlist.json` is a ratchet — counts may only go down; new files must be
  clean.
- **Frontend i18n**: zero CJK characters in `frontend/src/**/*.ts(x)` after comment stripping. Use
  `t(...)`; for genuinely non-translatable literals add `// i18n-exempt` (or
  `// i18n-exempt-start` / `-end` around a block).
- **Ruff baseline**: `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml` is a frozen snapshot of
  legacy violations. New files get no exemptions; when you clean a listed file, delete its entry.
- **Design tokens**: `DESIGN.md` mirrors the CSS variables in `frontend/src/index.css`. Change both
  in the same commit and keep `npx @google/design.md lint DESIGN.md` at 0 errors.
- **Dependency licenses**: strong copyleft (GPL/AGPL/SSPL) is denied by
  `scripts/check_dependency_licenses.py`; `license-inventory.csv` and `sbom.spdx.json` are
  compliance artifacts, regenerated on release rather than hand-edited.

## Testing notes

- `pytest-asyncio` is in `auto` mode — `async def test_*` just works, no decorator.
- Default `addopts = "-m 'not ee and not e2e'"`. Mark enterprise-only tests `@pytest.mark.ee` and
  full pipeline tests `@pytest.mark.e2e`; `m01`–`m10` markers tag OSS-split acceptance modules.
- `tests/contract/` pins API/port contracts, `tests/ports/` covers the registry and local adapters,
  `tests/compliance/` covers the lint gates themselves.
- Autouse fixtures close every `SQLiteStore` a test creates and restore the ports registry — rely on
  them rather than writing teardown.
- Frontend tests colocate as `*.test.ts(x)` beside the source; `src/__tests__/setup.ts` wires
  jest-dom and MSW.
- `scripts/acceptance/run.sh M01 ce` runs a module acceptance suite against a live API and writes
  evidence logs to `acceptance-logs/` (not committed).

## Docs

`docs/en/` and `docs/zh/` are kept in parallel — update both when changing user-facing behavior.
`docs/en/concepts/architecture.md` has the port→adapter table; `docs/en/getting-started/` covers
install and model configuration; `docs/adr/` holds architecture decision records.
