# M2: Ledger and control plane

> Land the ledger safety floor, `/v1/*` control-plane API, OpenAPI → TypeScript codegen, and hybrid live/mock UI.

## Process
- [x] Vision — `docs/PDD.md` §7
- [x] Design — `.cursor/plans/m2_ledger_control_plane_f6e09e45.plan.md`
- [x] Milestone — this doc
- [x] **Implement**
- [ ] Verify
- [ ] Ship — PR to `staging`

## Tasks
- [x] Alembic `002_strategy_ledger` + SQLAlchemy models
- [x] `core/domain` DTOs + pure `state_machine` + unit tests
- [x] `core/ledger` writer/queries/reconcile/seed + AST purity guard
- [x] `/v1/*` routes, bearer auth, startup seed, API tests
- [x] `openapi-typescript` regen script + CI drift check
- [x] UI hybrid `api/client` + `api/mode` + live vitest cases
- [x] `.env.example`, README, Greptile glossary

## Out of scope (M3+)
- Ingestion, paper executor, scheduler, graduated states, nightly reconciliation, WebSocket push

## Verification
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- `cd ui && npm run check && npm run lint && npm run test && npm run build`
- `docker compose up`: `/healthz` ok, `GET /v1/strategies` returns seeded strategies with bearer token

## Notes
- Bankroll mutations only in `core/ledger/writer.py` (AST guard in `tests/test_ledger_purity_guard.py`).
- Hand-written `ui/src/lib/types.ts` remains for prototype-only shapes; API types live in `ui/src/lib/api/types.ts`.
