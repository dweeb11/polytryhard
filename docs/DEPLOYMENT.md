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

## Branch flow

GitHub remains the review surface. Protected `main` and `staging` branches mirror to Gitea after GitHub accepts them, and Coolify deploys from Gitea.
