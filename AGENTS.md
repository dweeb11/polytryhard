# AGENTS.md

General contributor and architecture guidance lives in `CLAUDE.md` and `README.md`.
Standard lint/test/build/run commands are documented there and in `.github/workflows/ci.yml`.

## Cursor Cloud specific instructions

The dependency-refresh update script (run automatically on VM startup) only recreates the
Python venv (`.venv`, Python 3.11) and runs `npm ci` in `ui/`. System dependencies
(Python 3.11, Node 24 via nvm, PostgreSQL 16) and the local databases are already baked into
the VM snapshot — do not reinstall them. The notes below cover non-obvious caveats for
starting/running the services.

### Services

- **API** (FastAPI, repo root `core/`): `uvicorn core.api.main:app` on `:8080`. Bundles the
  ingestion scheduler in-process (`SCHEDULER_ENABLED`). Control-plane routes under `/v1/*` need
  `Authorization: Bearer <CONTROL_PLANE_TOKEN>`; `GET /healthz` is open.
- **UI** (SvelteKit/Vite, `ui/`): `npm run dev` on `:5173`. Runs in **mock** mode standalone, or
  **live** mode when `PUBLIC_BACKEND_URL`/`PUBLIC_BACKEND_TOKEN` are set and `/healthz` is reachable.
- **PostgreSQL 16**: local cluster, not Docker. Start it with `sudo pg_ctlcluster 16 main start`
  (check with `pg_lsclusters`). Two databases exist: `polytryhard_shared` and `polytryhard_staging`,
  both owned by role `polytryhard` (password `polytryhard`). Connect over TCP at `127.0.0.1:5432`.

### Running the full stack (live mode)

```bash
# API (full DB mode) — from repo root
DATABASE_URL_SHARED="postgresql+psycopg://polytryhard:polytryhard@127.0.0.1:5432/polytryhard_shared" \
DATABASE_URL_PER_ENV="postgresql+psycopg://polytryhard:polytryhard@127.0.0.1:5432/polytryhard_staging" \
REQUIRE_DBS=1 CONTROL_PLANE_TOKEN=dev SCHEDULER_ENABLED=0 \
./.venv/bin/uvicorn core.api.main:app --reload --port 8080

# UI live mode — from ui/
PUBLIC_BACKEND_URL=http://localhost:8080 PUBLIC_BACKEND_TOKEN=dev npm run dev
```

Apply migrations after a fresh DB (requires Postgres running) — both Alembic trees:

```bash
DATABASE_URL_SHARED=... DATABASE_URL_PER_ENV=... ./.venv/bin/python - <<'PY'
import os
from core.migrations import run_upgrade
run_upgrade("shared", os.environ["DATABASE_URL_SHARED"])
run_upgrade("per_env", os.environ["DATABASE_URL_PER_ENV"])
PY
```

### Non-obvious gotchas

- **Node version**: the non-interactive shell's `node` resolves to a system `node` v22 ahead of
  nvm on `PATH`. CI uses Node 24. Run UI commands from a login/`tmux` shell (which sources
  `~/.bashrc` where nvm's default Node 24 is prepended), or explicitly prefix:
  `export PATH="$HOME/.nvm/versions/node/v24.18.0/bin:$PATH"`.
- **Do not export `DATABASE_URL_*` when running `pytest`.** Tests use SQLite via `conftest.py`
  with `REQUIRE_DBS=0`; a real `DATABASE_URL_SHARED`/`DATABASE_URL_PER_ENV` in the environment
  leaks into `tests/test_healthz.py` and makes it fail (it expects an `unconfigured`/`503` health
  state). Run tests clean, e.g. `env -u DATABASE_URL_SHARED -u DATABASE_URL_PER_ENV REQUIRE_DBS=0 pytest -q`.
- **Scheduler + healthz**: when `SCHEDULER_ENABLED=1` and no engine tick has run yet, `/healthz`
  reports `degraded` (503) until the first cycle. Set `SCHEDULER_ENABLED=0` for a clean control-plane
  demo, or wait for the first tick.
- Kalshi is optional; the source reports `degraded` without `KALSHI_*` creds. Open-Meteo needs no key.
