# M1.5: UI cleanup + parity tests

> Trim prototype overreach before the ledger/control-plane cutover, and lock mock behavior with a vitest regression suite.

## Process
- [x] Vision — `docs/architecture-review.md`
- [x] Design — architecture review §6–§7
- [x] Milestone — this doc
- [x] **Implement**
- [x] Verify
- [ ] Ship — PR to `staging`

## Tasks
- [x] Delete redirect stubs (`/plugins`, `/audit`, `/sources`, `/settings`); nav links point at `/settings/*`
- [x] Remove `ledger-discipline` CI grep (M2 replaces with Python AST guard)
- [x] Drop `subscribePersistence`; keep explicit `persistCurrent()` in actions
- [x] Collapse to single UI env (`polytryhard` localStorage key); keep reset-to-fixtures
- [x] Trim `types.ts` (no `prePauseState`, graduated states, circuit breaker, plugin requires/provides, `featuresSnapshot`)
- [x] Remove `strategyBlockedBy` resolver and blocked badges
- [x] Guard non-finite deposit/withdraw amounts in strategy detail UI
- [x] Add vitest behavior suite over `actions.ts` (~15 cases)
- [x] `@lru_cache` `make_engine`; fail-closed `REQUIRE_DBS` + `/healthz` degraded on unconfigured DBs

## Deleted (architecture review)
- §3.2 dual-env UI switcher and per-env fixtures
- §3.3 plugin dependency resolver (`strategyBlockedBy`, `strategiesWouldBlock`)
- §3.4 `ledger-discipline` grep job
- §3.5 `subscribePersistence` N+1 writes
- §3.6 redirect route stubs
- §3.9 `featuresSnapshot` ballast
- Graduated strategy states and `prePauseState` restoration in mock actions

## Forward to M2
- Python AST purity guard at `core/ledger/writer.py`
- OpenAPI → TypeScript codegen (`ui/src/lib/api/types.ts`)
- `/v1/*` control plane and hybrid live/mock UI

## Verification
- `cd ui && npm run check && npm run lint && npm run test && npm run build` — passed (19 vitest cases)
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q` — 6 passed, 1 skipped (Testcontainers)

## Notes
- Hand-written `ui/src/lib/types.ts` remains for prototype-only shapes until codegen lands in M2.
- Do not start M2 until this PR is merged to `staging`.
