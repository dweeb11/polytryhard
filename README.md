# polytryhard

Statistical research lab for prediction markets — **frontend prototype only** (no FastAPI, Postgres, or Docker yet).

The dashboard in `ui/` is a live, in-browser mock: every control mutates persisted state, writes audit events, and enforces PDD ledger/state-machine rules. See [docs/PDD.md](docs/PDD.md) for the full product design.

## Run the UI

```bash
cd ui
npm install --cache .npm-cache   # use local cache if global npm cache has permission issues
npm run dev
```

Open http://localhost:5173

Other commands:

```bash
npm run build    # production static build
npm run check    # svelte-check
npm run lint
```

## Repo

Canonical remote: `git@github.com:dweeb11/polytryhard.git`

## What works in the prototype

- Environments `main` / `staging` with separate `localStorage` namespaces
- Strategy roster, detail (bankroll + calibration SVG), sources, plugins, audit log
- Single mutation surface: `ui/src/lib/actions.ts`
- Simulated tick loop (~3s) for P&L drift, source aging, and signal emission
- Kill switch, deposit/withdraw with free-cash gating, plugin dependency blocking
