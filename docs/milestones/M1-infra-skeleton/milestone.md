# M1: Infra Skeleton

> Stand up the backend, migration, CI, Docker, and Coolify staging foundations without adding trading domain behavior.

## Process
- [x] Vision — `docs/PDD.md`
- [x] Design — `docs/PDD.md` §3, §5, §8, §9
- [x] Milestone — this doc
- [x] **Implement** <- current stage
- [x] Verify
- [ ] Ship — PR to `staging`, then Coolify deploy confirmation

## Tasks
- [x] Bootstrap Python 3.11 project dependencies and backend package skeleton.
- [x] Add FastAPI `/healthz`, request-id middleware, JSON-ready status payload, and UTC `now_iso()`.
- [x] Add shared/per-env DB session helpers and a BIGINT cents helper.
- [x] Add Alembic trees for shared and per-env migrations; per-env starts with append-only `audit_event`.
- [x] Add Dockerfile, local compose, Coolify compose, `.env.example`, and startup migration script.
- [x] Add backend unit and integration tests, including a Testcontainers Postgres path for CI.
- [x] Extend CI with backend Ruff, mypy, and pytest checks.
- [x] Prepare Coolify `event-market-staging` app on lxc-107 for compose deployment from `staging`.
- [x] Add a UI backend-status badge using `PUBLIC_BACKEND_URL`; UI remains mock-authoritative.
- [x] Document milestone verification and deployment notes.

## Verification
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && ./.venv/bin/pytest -q`
  - Result: Ruff passed, mypy passed, `6 passed, 1 skipped`.
  - Skip reason: local machine has no `docker` binary, so the Testcontainers Postgres test is skipped locally and will run in GitHub Actions.
- `cd ui && npm run check && npm run lint && npm run build`
  - Result: Svelte check passed with 0 warnings, ESLint passed, production build completed.
- `ReadLints` on edited backend/UI paths
  - Result: no linter errors found.

## Coolify Notes
- Existing Coolify project: `Polytryhard`.
- Existing staging application: `event-market-staging`.
- Staging domain: `https://staging-event-market.critterhaus.net`.
- The application is configured for `dockercompose` with `/docker-compose.coolify.yml` and a generated encrypted `POSTGRES_PASSWORD` environment variable.
- `/healthz` can only be verified on the staging domain after this branch is merged or otherwise deployed to the remote `staging` branch, because Coolify builds from git.

## PDD Links
- PDD §3.2: monolith deploy unit, plugin architecture later.
- PDD §5.3: shared additive-only and per-env migration discipline.
- PDD §6.1: `request_id` and fail-closed operational visibility.
- PDD §7.1: cents as integer ledger foundation.
- PDD §8: test strategy.
- PDD §9.1: branch-to-Coolify operating model.

## Notes
- M1 intentionally adds no ingestion, strategy, executor, `/v1/*` control-plane endpoint, or live trading behavior.
- Backend status in the UI is informational only; the prototype state remains localStorage-backed until the control-plane milestone.
- M1 uses synchronous SQLAlchemy sessions with `psycopg` for the API and Alembic path. `asyncpg` is installed for the planned asyncio scheduler/ingestion layer, but that layer is deliberately deferred.
