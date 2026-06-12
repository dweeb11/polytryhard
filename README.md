# polytryhard

Statistical research lab for prediction markets — FastAPI control plane, per-env Postgres ledger, and a SvelteKit UI that runs in **live** or **mock** mode.

See [docs/PDD.md](docs/PDD.md) for the full product design.

## Quick start (local)

```bash
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env   # edit DATABASE_URL_* and CONTROL_PLANE_TOKEN

docker compose up -d postgres   # or point URLs at existing Postgres
./.venv/bin/alembic -c alembic.ini upgrade head  # per-env tree via scripts/start-api.sh

REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=dev ./.venv/bin/uvicorn core.api.main:app --reload --port 8080
```

```bash
cd ui
npm install --cache .npm-cache
# optional live mode:
# PUBLIC_BACKEND_URL=http://localhost:8080 PUBLIC_BACKEND_TOKEN=dev npm run dev
npm run dev
```

Open http://localhost:5173 — header shows **Live backend** when `/healthz` is ok and `PUBLIC_BACKEND_*` are set; otherwise **Mock prototype**.

## Commands

| Area | Command |
|------|---------|
| API lint/type/test | `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q` |
| UI | `cd ui && npm run check && npm run lint && npm run test && npm run build` |
| Regen API types | `REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export ./.venv/bin/python scripts/export_openapi.py && cd ui && npm run regen-api-types` |

## Repo

Canonical remote: `git@github.com:dweeb11/polytryhard.git`

**Branches:** `staging` (integration) ← feature PRs; `main` (production) ← promote via PR after staging soak. See [.cursor/rules/git-workflow.mdc](.cursor/rules/git-workflow.mdc).

## Architecture (M2)

- `core/ledger/writer.py` — sole bankroll mutator; every change writes `cash_event` + `audit_event`
- `core/api/v1/` — bearer-auth control plane (`/v1/strategies`, `/v1/system`, `/v1/audit`)
- `ui/src/lib/api/types.ts` — generated from OpenAPI; mock-only types stay in `ui/src/lib/types.ts`
