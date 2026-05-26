# Deployment

polytryhard currently deploys as a static SvelteKit prototype.

## Coolify

Use a private GitHub application connected to:

- Repository: `git@github.com:dweeb11/polytryhard.git`
- Branch: `main`
- Build pack: Dockerfile
- Dockerfile location: `/Dockerfile`
- Exposed port: `80`
- Health check path: `/healthz`
- Health check port: `80`
- Domain: `https://polytryhard.critterhaus.net` once DNS/proxy routing exists

The root `Dockerfile` builds `ui/` with Node 24 and serves the static `ui/build` output through nginx.

## Private repo access

Coolify needs one of these before it can deploy:

- A Coolify GitHub App installation with access to `dweeb11/polytryhard`.
- A deploy key registered on the GitHub repo.

Do not make the repo public just to simplify deployment.
