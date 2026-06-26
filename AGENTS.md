# AGENTS.md

See `README.md` and `CLAUDE.md` for architecture and the canonical lint/test/build/run commands. This file only adds Cursor Cloud environment caveats.

## Cursor Cloud specific instructions

### Runtime layout
- Python **3.11** is required (`pyproject.toml` pins `>=3.11,<3.12`); the backend venv lives at `.venv` (use `./.venv/bin/...`).
- **PostgreSQL 16** runs locally (not Docker) on `localhost:5432`. Role/password `polytryhard`/`polytryhard`, databases `polytryhard_shared` and `polytryhard_staging`. The cluster is not auto-started on boot — start it each session with `sudo pg_ctlcluster 16 main start` before running the API or migrations.
- Service env vars live in `.env.local` (gitignored). Source it when starting the API: `set -a && . ./.env.local && set +a`.

### Gotcha: do NOT create a root `.env` with DB URLs
- Pydantic `Settings` (`core/settings.py`) auto-loads a root `.env`. If that `.env` defines `DATABASE_URL_*`, then `tests/test_healthz.py::test_healthz_reports_version_request_id_and_database_status` fails, because it builds `create_app()` with no settings and expects an **unconfigured** backend (503/`unconfigured`). The README's `cp .env.example .env` step therefore breaks the test suite.
- Keep dev env in `.env.local` (which pydantic does not read) instead of `.env`, and run the backend suite with no DB URLs exported: `REQUIRE_DBS=0 ./.venv/bin/pytest -q` (272 pass, 1 skipped).

### Running the stack (both already verified working)
- Backend (API + in-process scheduler), with migrations auto-run on lifespan startup:
  `set -a && . ./.env.local && set +a && ./.venv/bin/uvicorn core.api.main:app --reload --port 8080`
- UI in live mode (talks to the API): from `ui/`,
  `PUBLIC_BACKEND_URL=http://localhost:8080 PUBLIC_BACKEND_TOKEN=dev npm run dev` → http://localhost:5173 (header shows "LIVE BACKEND").

### Migrations
- The documented `alembic -c alembic.ini upgrade head` fails with `KeyError: 'url'` (the ini sets no URL). Migrations are applied automatically by the API lifespan / `scripts/start-api.sh`. To run them manually, use the helper: `core.migrations.run_upgrade("shared"/"per_env", <url>)`.
