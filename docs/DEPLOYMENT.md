# Deployment

polytryhard currently deploys as a static SvelteKit prototype.

## Coolify

Use the mirrored Gitea repository for homelab deployment:

- Repository: `git@git.critterhaus.net:2222/homelab/polytryhard.git`
- Production branch: `main`
- Staging branch: `staging`
- Build pack: Dockerfile
- Dockerfile location: `/Dockerfile`
- Exposed port: `80`
- Health check path: `/healthz`
- Health check port: `80`
- Production URL: `https://event-market.critterhaus.net`
- Staging URL: `https://staging-event-market.critterhaus.net`

The root `Dockerfile` builds `ui/` with Node 24 and serves the static `ui/build` output through nginx.

## Backend API (FastAPI)

Deployed via `docker-compose.coolify.yml` on port `8080` (see `Dockerfile.api`).

- **`REQUIRE_DBS`** (default `1`): when enabled, the API process refuses to start unless both `DATABASE_URL_SHARED` and `DATABASE_URL_PER_ENV` are set (non-empty). Set `REQUIRE_DBS=0` in `.env` or the process environment for local pytest without Postgres.
- **`GET /healthz`**: returns **200** when both databases respond; **503** when either is `down` or `unconfigured`. Docker/Coolify health checks should treat non-2xx as unhealthy.

## Branch flow

GitHub remains the review surface. Protected `main` and `staging` branches mirror to Gitea after GitHub accepts them, and Coolify deploys from Gitea.
