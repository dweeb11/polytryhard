# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**polytryhard** is a self-hosted statistical research lab for prediction markets. It paper-trades Kalshi weather contracts via pluggable strategies, evaluates them against honest calibration metrics, and graduates winners to live execution. AI is used as a feature extractor only — never in the decision path.

Canonical remote: `git@github.com:dweeb11/polytryhard.git`  
Deployed on Coolify (lxc-107): `main` and `staging` as separate services. See `docs/DEPLOYMENT.md`.

## Commands

### Backend (repo root)

```bash
# Install
python3.11 -m venv .venv
./.venv/bin/pip install -r requirements-dev.txt

# Run all tests (SQLite, no Postgres needed)
REQUIRE_DBS=0 pytest -q

# Run a single test file
REQUIRE_DBS=0 pytest tests/test_ledger_state_machine.py -v

# Lint + type-check + test (full gate)
./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q

# Start API locally (no Postgres)
REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=dev ./.venv/bin/uvicorn core.api.main:app --reload --port 8080

# Apply DB migrations (requires Postgres)
./.venv/bin/alembic -c alembic.ini upgrade head

# Export OpenAPI schema (for UI type regen)
REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export ./.venv/bin/python scripts/export_openapi.py
```

### Frontend (`ui/`)

```bash
npm install --cache .npm-cache
npm run dev                    # Vite dev server at :5173
npm run check && npm run lint && npm run test && npm run build   # full gate
npm run regen-api-types        # regenerate ui/src/lib/api/types.ts from OpenAPI
```

Live mode: set `PUBLIC_BACKEND_URL=http://localhost:8080` and `PUBLIC_BACKEND_TOKEN=dev` before `npm run dev`. Header shows **Live backend** vs **Mock prototype** based on `/healthz` reachability.

## Architecture

### Two databases, strict separation

- **shared** (`DATABASE_URL_SHARED`): append-only raw market data, ingested features, reference data (locations). Written by the ingestion/feature layer; read by strategies.
- **per_env** (`DATABASE_URL_PER_ENV`): ledger, audit log, signals, paper positions, strategy config. One DB per deployment env (staging/main). Never mix.

Each has its own Alembic migration tree under `migrations/shared/` and `migrations/per_env/`. Run both with the `alembic.ini` at repo root (it dispatches by env key).

### Engine tick (`core/engine/tick.py`)

The central loop: `run_engine_tick()` wires everything together in order:
1. Compute features from all enabled providers → persist to shared DB
2. Build market states from shared DB
3. For each active strategy × each market: evaluate → risk-size → record signal → place order
4. Commit both sessions

The scheduler (`core/scheduler.py`) runs this on a timer. Disable it in tests via `SCHEDULER_ENABLED=0`.

### Ledger (`core/ledger/writer.py`)

**The sole bankroll mutator.** Every balance change writes a paired `cash_event` row + `audit_event` row in a single flush. Call `writer.*` functions for all ledger mutations — never update `StrategyInstanceRow.bankroll_cents` directly.

Key functions: `deposit`, `withdraw`, `record_signal`, `open_paper_position`, `apply_kill_switch`, `clear_kill_switch`, strategy lifecycle (`activate_strategy`, `pause_strategy`, `resume_strategy`, `decommission_strategy`).

### Pluggable contracts (`core/contracts/`)

Four ABC interfaces that define the extension points:
- `Strategy` — pure function `(market, features, ctx) → SignalDraft | None`. No I/O, no clock.
- `FeatureProvider` — async `compute(as_of, ctx) → list[FeatureValue]`.
- `Source` — data ingestion; reports health and last-fetch time.
- `Executor` — places orders; `PaperExecutor` is the only live implementation in MVP.

Register implementations in their respective `registry.py` files.

### UI mode switching (`ui/src/lib/api/`)

The SvelteKit frontend has two modes: **live** (calls real backend) and **mock** (uses fixtures). The mode is determined at runtime by `PUBLIC_BACKEND_URL`/`PUBLIC_BACKEND_TOKEN` env vars and `/healthz` reachability. `ui/src/lib/api/types.ts` is generated from OpenAPI — edit the FastAPI schemas, not this file. Mock-only types live in `ui/src/lib/types.ts`.

### API (`core/api/v1/`)

All control-plane routes under `/v1/` require `Authorization: Bearer <CONTROL_PLANE_TOKEN>`. Exception: `GET /healthz` is unauthenticated. Pydantic schemas in `core/api/v1/schemas.py` are the API contract — don't remove response fields.

## Key invariants

- **Strategies are pure.** `evaluate()` receives `(market_state, features_dict, ctx)` and returns a signal or `None`. No I/O, no clock calls, no randomness.
- **Missing is first-class.** `FeatureValue.status` can be `PRESENT`, `MISSING`, or `STALE`. Strategies receive `FeatureStatus.MISSING` — never a defaulted zero.
- **Fail closed.** Degraded source, stale feature, breached cap → reject signal, record rejection reason in audit log, do nothing.
- **All timestamps UTC.** `core/utils/time.py` provides `utc_now()` and `now_iso()`. The `Clock` abstraction (`core/clock.py`) makes time injectable for backtest vs. live.
- **Request IDs everywhere.** Every ledger write and audit event requires a `request_id`. The API generates one per request via middleware; the engine generates one per tick.

## Testing

Tests use SQLite via `conftest.py` fixtures — no Postgres required for `pytest`. `REQUIRE_DBS=0` disables the startup DB check. Integration tests requiring a real DB are gated with `pytest.mark.skipif` or `testcontainers`.

The `api_client` fixture from `conftest.py` gives a `TestClient` wired to SQLite with `SCHEDULER_ENABLED=False`.

## Git workflow

Feature branches from `staging`, not `main`. PRs always target `staging`. Promote to `main` via `staging → main` PR after staging soak. Branch naming: `feat/<linear-id>-<slug>`. One concern per PR (target < ~300 lines). **PR review:** CodeRabbit only — do not invoke Codex review on polytryhard PRs. See `.cursor/rules/git-workflow.mdc` and `.cursor/rules/pr-slicing.mdc` for full rules.

## GBrain Configuration (configured by /setup-gbrain)

- Mode: **remote-http** (primary brain on bot-top) + **local PGLite** (per-machine code index)
- Remote MCP: `http://100.79.29.118:3131/mcp` (bot-top via Tailscale; LAN `192.168.1.197:3131` when on home network)
- Local code source: `gstack-code-polytryhard-e50058b4` (pinned via `.gbrain-source`)
- Setup date: 2026-06-25
- MCP registered: yes (`~/.cursor/mcp.json` → server name `gbrain`, Tailscale URL above)
- Token: `~/.cursor/mcp.json` + `~/.config/gbrain/token` (do not commit)
- Artifacts repo: `https://github.com/dweeb11/gstack-artifacts-davidpaolone-webb.git`
- Artifacts sync: full
- Current repo policy: read-write (`github.com/dweeb11/polytryhard`)
- CLI PATH: `~/.bun/bin` (fish: `config.fish`; zsh: `~/.zshrc` for Cursor agent shell)
- **Cursor MCP status:** configured in `~/.cursor/mcp.json`; if the `user-gbrain` server shows errored in Cursor Settings, confirm bot-top is up and Tailscale can reach `100.79.29.118:3131`. Local `gbrain` CLI still works against `~/.gbrain/brain.pglite` when remote is down.

### Call-graph quirks (this repo)

The call graph is built (`code-callers` status `ready`), but bare symbol names often miss:

| Intent | Command |
|--------|---------|
| Python `writer.deposit` callers | `gbrain code-callers "core.ledger::deposit"` (not bare `deposit`) |
| TS `actions.deposit` body | `gbrain code-callees deposit` |
| Both definitions | `gbrain code-def deposit` → Python `writer.py` + TS `actions.ts` |
| UI / Svelte call sites | **Not in graph** — `.svelte` is not code-synced; use `gbrain code-refs deposit` or grep |
| Vitest merged chunks | Caller edges from `ui/src/lib/__tests__/*.spec.ts` are often dropped (no `symbol_name_qualified` on merged chunks) |

After meaningful code changes: `gbrain sync --strategy code` then `gbrain extract --stale` if sync reports un-extracted edges. Re-run `gbrain dream --source "$(cat .gbrain-source)"` only when the graph is stale — it does not fix Svelte gaps or qualified-name lookup.

## GBrain Search Guidance (configured by /sync-gbrain)
<!-- gstack-gbrain-search-guidance:start -->

GBrain is set up and synced on this machine. The agent should prefer gbrain
over Grep when the question is semantic or when you don't know the exact
identifier yet.

**This worktree is pinned to a worktree-scoped code source** via the
`.gbrain-source` file in the repo root (kubectl-style context).
`gbrain code-def`, `code-refs`, `code-callers`, `code-callees`, `search`, and
`query` from anywhere under this worktree route to that source by default —
no `--source` flag needed (gbrain >= 0.41.38.0; on older gbrain the call-graph
commands need `--source "$(cat .gbrain-source)"`). Conductor sibling worktrees
of the same repo each have their own pin and their own indexed pages, so
semantic results match the code on disk here.

Call-graph queries (`code-callers`/`code-callees`) also need the graph to be
built first — run `/sync-gbrain --dream` (or `--full`) if they return
`count: 0`. This only works if this source's gbrain schema pack extracts code
symbols; on a non-code-aware pack `--dream` completes but the graph stays empty
and reports a WARN. `code-def`/`code-refs` need the same extraction.

Two indexed corpora available via the `gbrain` CLI:
- This worktree's code (auto-pinned via `.gbrain-source`).
- `~/.gstack/` curated memory (registered as `gstack-brain-<user>` source via
  the existing federation pipeline).

Prefer gbrain when:
- "Where is X handled?" / semantic intent, no exact string yet:
    `gbrain search "<terms>"` or `gbrain query "<question>"`
- "Where is symbol Y defined?" / symbol-based code questions:
    `gbrain code-def <symbol>` or `gbrain code-refs <symbol>`
- "What calls Y?" / "What does Y depend on?":
    `gbrain code-callers <symbol>` / `gbrain code-callees <symbol>`
- "What did we decide last time?" / past plans, retros, learnings:
    `gbrain search "<terms>" --source gstack-brain-<user>`

Grep is still right for known exact strings, regex, multiline patterns, and
file globs. Run `/sync-gbrain` after meaningful code changes; for ongoing
auto-sync across all worktrees, run `gbrain autopilot --install` once per
machine — gbrain's daemon handles incremental refresh on a schedule.

Safety: don't run `/sync-gbrain` while `gbrain autopilot` is active — the
orchestrator refuses destructive source ops when it detects a running autopilot
to avoid racing it (#1734). Prefer registering user repos with `gbrain sources
add --path <dir>` (no `--url`): URL-managed sources can auto-reclone, and the
sync code walk for them requires an explicit `--allow-reclone` opt-in.

<!-- gstack-gbrain-search-guidance:end -->
