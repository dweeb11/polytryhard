# Deployment

polytryhard deploys to Coolify on lxc-107 as **one Docker Compose application per environment** (`event-market-staging`, production equivalent on `main`).

## Repository mirror

- GitHub (review): `git@github.com:dweeb11/polytryhard.git`
- Gitea (Coolify build source): `git@git.critterhaus.net:2222/homelab/polytryhard.git`
- **Staging branch:** `staging` → `https://staging-event-market.critterhaus.net`
- **Production branch:** `main` → `https://event-market.critterhaus.net`

GitHub merges mirror to Gitea; Coolify deploys from Gitea on branch push.

## Compose stack (`docker-compose.coolify.yml`)

| Service | Image | Port | Coolify domain |
|---------|-------|------|----------------|
| `ui` | `Dockerfile.ui` (nginx + static SvelteKit) | 80 | Primary — e.g. `staging-event-market.critterhaus.net` |
| `api` | `Dockerfile.api` (FastAPI + scheduler) | 8080 | Subdomain — e.g. `api.staging-event-market.critterhaus.net` |
| `postgres` | `postgres:16` | internal | none |

### Coolify domain assignment

In the compose application → **Domains** (or per-service domain settings):

1. **`ui` service** — primary FQDN, port **80** (e.g. `staging-event-market.critterhaus.net`)
2. **`api` service** — subdomain FQDN, port **8080** (e.g. `api.staging-event-market.critterhaus.net`)

The browser must reach the API at a **public HTTPS URL** — not a Docker-internal hostname like `http://api:8080`.

### Staging health checks

- **UI** `GET /healthz` on port 80 → plain text `ok`
- **API** `GET /healthz` on port 8080 → JSON with `db_shared` / `db_per_env`

## Coolify environment variables

Set in the application's **Environment Variables** panel. The compose file passes them into containers (values in Coolify, wiring in git).

### Required (staging)

| Variable | Used by | Notes |
|----------|---------|-------|
| `POSTGRES_PASSWORD` | postgres, api | Generated/encrypted in Coolify |
| `CONTROL_PLANE_TOKEN` | api; ui build (via compose) | `openssl rand -hex 32` — single secret for API auth and UI bundle |
| `PUBLIC_BACKEND_URL` | ui build | Public API URL, e.g. `https://api.staging-event-market.critterhaus.net` |

Compose passes `CONTROL_PLANE_TOKEN` into the UI build as `PUBLIC_BACKEND_TOKEN`; you do **not** need a separate `PUBLIC_BACKEND_TOKEN` in Coolify for deploy.

### Recommended

| Variable | Default in compose | Notes |
|----------|-------------------|-------|
| `CORS_ALLOW_ORIGINS` | staging UI origin | Must include the UI URL |
| `SCHEDULER_ENABLED` | `1` | Set `0` only to disable ingestion |

### Optional (Kalshi — source stays degraded without these)

`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY`, `KALSHI_API_BASE`, `KALSHI_SERIES_PREFIXES`

### UI build-time note

`PUBLIC_BACKEND_URL` and the control-plane token are baked into the static bundle during `docker build` (`build/_app/env.js`). Changing them requires a **redeploy/rebuild** of the `ui` service, not just a container restart.

**Security:** The token is embedded in client-side JS (required for browser bearer auth). Treat it as a control-plane credential scoped to what the UI calls — acceptable for single-user homelab; do not use a production-wide admin secret unrelated to this app.

## Verify after deploy

```bash
# API
curl https://api.staging-event-market.critterhaus.net/healthz
curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  https://api.staging-event-market.critterhaus.net/v1/sources

# UI — open in browser; header badge should show "Backend: ok" and mode "Live backend"
```

Open-Meteo ingests without Kalshi creds. Kalshi reports `degraded` until configured.

## Local development

See root `README.md` and `.env.example`. For local UI live mode, set both `PUBLIC_BACKEND_URL` and `PUBLIC_BACKEND_TOKEN` (local dev does not use compose token dedupe):

```bash
PUBLIC_BACKEND_URL=http://localhost:8080 PUBLIC_BACKEND_TOKEN=dev npm run dev --prefix ui
```

## Other Dockerfiles

- **`Dockerfile.ui`** — used by Coolify compose for the `ui` service (includes `PUBLIC_*` build args).
- **`Dockerfile`** — legacy UI-only image path; not used by Coolify compose. Prefer `Dockerfile.ui` for new deploy work.
