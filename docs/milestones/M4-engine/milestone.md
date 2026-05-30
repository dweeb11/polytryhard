# M4: Engine spine — features through paper fills

> Wire the deterministic live tick: raw data → features → strategy → risk/sizing → paper executor → ledger.

## Process
- [x] Vision — `docs/PDD.md` §1.2, §4.1
- [x] Design — `docs/design/m4-engine.md`
- [x] Milestone — this doc
- [ ] **Implement** <- current stage
- [ ] Verify
- [ ] Ship — ordered PRs to `staging`

## Tasks (PR slices, ordered)
- [ ] M4.1 Shared schema `003` — `feature_value` table
- [ ] M4.2 `FeatureProvider` ABC + tri-state `FeatureValue` DTO + explicit registry
- [ ] M4.3 Stat feature providers (`ensemble_mean_temp`, `forecast_disagreement`, `kalshi_spread`) + unit tests
- [ ] M4.4 `Strategy` ABC + registry + AST purity guard
- [ ] M4.5 Weather strategy/strategies + unit tests incl. negation cases
- [ ] M4.6 `core/risk` sizing engine (Kelly, caps, freshness) + unit tests
- [ ] M4.7 `Executor` ABC + `paper_executor` writing through `core/ledger` + tests
- [ ] M4.8 Tick orchestration in scheduler + integration test
- [ ] M4.9 `/v1/signals` + `/v1/positions` endpoints + OpenAPI regen
- [ ] M4.10 (optional) Minimal read-only Signals/Positions UI panel

## Out of scope (M5+)
- Position resolution / realized P&L (`contract_resolution` table)
- Eval metrics (`eval_metric_snapshot`), calibration plots, P&L dashboard wiring
- Replay clock, dirty-set propagation, WebSocket push
- NWS source, manifest/filesystem plugin discovery
- Live Kalshi executor

## Verification
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- Ledger AST purity guard stays green
- Integration test: seeded shared snapshots/forecasts + one enabled strategy + fake clock → expected `signal` + `paper_fill`/`paper_position`/`cash_event` rows in per-env DB
- `cd ui && npm run check && npm run lint && npm run test && npm run build` (if M4.10 included)

## Notes
- Per-env schema (`signal`, `paper_position`, `paper_fill`, `cash_event`) already exists from M2 — M4 adds engine logic only.
- Linear: milestone **M4 — Engine** in the `polytryhard` project (team Apps); issues to be created in dependency order.
- Closed stale backlog: APP-184 (engine cache, done in M1.5), APP-186 (Dockerfile COPY, done). Remaining M3 Kalshi nits (APP-197–204) stay in backlog — none block M4.
