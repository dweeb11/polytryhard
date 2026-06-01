# M5: Resolution & Evaluation — close the loop

> Resolve paper positions into realized P&L and honest calibration metrics, so strategies become measurable and graduation-eligible.

## Process
- [x] Vision — `docs/PDD.md` §1.4, §5.2, §7.5
- [x] Design — `docs/design/m5-eval.md`
- [x] Milestone — this doc
- [ ] **Implement** <- current stage
- [ ] Verify
- [ ] Ship — ordered PRs to `staging`

## Tasks (PR slices, ordered)
- [x] M5.1 Shared schema `004` — `contract_resolution` table + `ContractResolution` enum + model
- [x] M5.2 `kalshi_resolution` Source plugin + pure parse unit tests
- [x] M5.3 Resolution tick + `resolve_position` / `record_realized_pnl` ledger writers + per-env tests
- [ ] M5.4 `core/eval` pure metrics (hit rate, Brier, log-loss, drawdown, sharpe proxy, posterior edge, calibration bins) + unit tests
- [ ] M5.5 `eval_metric_snapshot` writer + post-resolution & nightly recompute + integration test
- [ ] M5.6 `/v1/eval` endpoints + schemas + OpenAPI/TS regen
- [ ] M5.7 Read-only Calibration & P&L UI panel + `regen-api-types`

## Out of scope (M6+)
- Live (real-money) Kalshi executor — graduation criteria informed by M5 metrics, promotion is a later milestone
- Backtest replay clock, dirty-set propagation, WebSocket push
- NWS source, manifest/filesystem plugin discovery
- New drawdown auto-pause machinery (M5 documents/tests the hook, reuses existing state logic)
- Rubric/news features, auto-top-up, reconciliation extensions

## Verification
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- Ledger AST purity guard stays green; strategies remain pure
- Per-env: YES/NO × win/loss + void assert `cash_event`, bankroll, free-cash recovery, `status=resolved`, HWM, audit pairing
- Eval units: Brier/log-loss/hit-rate/posterior vs hand-computed fixtures incl. `n=0`, all-wins, single-trade
- Integration: seed shared snapshots/forecasts + one strategy + fake clock → open position → write `contract_resolution` → resolution tick → expected `realized_pnl` `cash_event` + `eval_metric_snapshot` rows
- `cd ui && npm run check && npm run lint && npm run test && npm run build`

## Notes
- Design decisions locked in brainstorming: resolution via a **Source plugin** (`kalshi_resolution`, writes shared DB) with a separate per-env resolution step; posterior edge = **Normal-Normal on per-trade ROI** with skeptical prior `N(0, τ²)`, default `τ=0.5`; M5 includes the read-only UI panel (mirrors M4's slice).
- Builds on existing scaffolding: `record_realized_pnl` stub (`core/ledger/writer.py:246`), `PaperPositionRow.status='resolved'` + nullable `realized_pnl_cents`, `reference_market.settlement_time/status`. `contract_resolution` is new (specced in PDD §5.1).
- Cost basis is reserved (not spent) at open → resolution moves bankroll by net P&L only; keeps `bankroll == Σ cash_event`.
- Linear: create milestone **M5 — Resolution & Evaluation** in the `polytryhard` project (team Apps); issues in dependency order M5.1→M5.7.
