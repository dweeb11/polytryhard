# M8: Strategy Correctness & Honest Accounting

> Make `prob_yes` a real strike-aware probability and make paper P&L honest (fees, dedupe, enforced drawdown pause) so eval metrics measure something meaningful.

## Process
- [x] Vision — strategy review session (2026-07-01)
- [x] Design — docs/design/m8-strategy-correctness.md
- [x] Milestone — this doc
- [ ] **Implement** <- current stage
- [ ] Verify
- [ ] Ship

## Tasks
- [ ] M8.1: Strike metadata — shared migration 005, parse, persistence, backfill script (APP-376)
- [ ] M8.2: `core/domain/weather_markets.py` — target date, bracket predicate, smoothed probability (APP-377)
- [ ] M8.3: Empirical bracket-semantics verification script (mismatches=0 on staging, evidence in PR) (APP-382)
- [ ] M8.4: Daily-high member query + `weather_model_prob` feature provider (APP-379)
- [ ] M8.5: Kalshi trading-fee model (`core/risk/fees.py`) (APP-378)
- [ ] M8.6: Sizing fixes — fee-aware edge, binary Kelly, per-ticker dedupe, per-strategy exposure cap (APP-380)
- [ ] M8.7: Rewrite both strategies on `weather_model_prob`; delete fake temp↔prob mapping (APP-383)
- [ ] M8.8: Automatic drawdown pause in engine tick (APP-381)

## Notes
One PR per task, branch from `staging`, CodeRabbit review only. T3 is an evidence
gate: T7 must not ship until bracket semantics verify with zero mismatches against
recorded resolutions. Full task detail (code, tests, commands) lives in the design
doc. Follow-ons M9 (replay harness), M10 (new strategies), M11 (expansion) are
scoped at the bottom of the design doc and need their own design docs.
