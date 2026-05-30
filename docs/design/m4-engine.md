# M4 design — Engine spine (features through paper fills)

> Wire the deterministic live tick: raw data → features → strategy → risk/sizing → paper executor → ledger. Same code path backtest will later drive via a replay clock.

**Status:** Approved design, pre-implementation.
**Depends on:** M3 (ingestion: Kalshi + Open-Meteo sources, scheduler, `/v1/sources`, Source Health UI), merged to `staging`.
**PDD references:** §3.3–§3.4 (core vs plugins, repo layout), §4.1 (live tick), §5.1/§5.2 (shared + per-env schema), §6 (fail-closed), §7 (ledger invariants), §8.1–§8.2 (unit + integration tests).

---

## 1. Goal & rationale

M3 started the historical record: Kalshi market snapshots and Open-Meteo forecast runs land in the shared DB on a schedule. M4 wires the **deterministic engine** that turns that data into paper trades.

The MVP scope (PDD §1.2) is "paper-trade Kalshi end-to-end on weather markets." M4 delivers the core of that loop — features, strategies, sizing, and a paper executor writing to the ledger. Eval metrics, calibration UI, and backtest replay are deferred to M5.

Rationale for this cut:
- The per-env schema (`signal`, `paper_position`, `paper_fill`, `cash_event`) already exists from M2; M4 adds engine logic, not new ledger tables.
- The `IngestionSource` ABC + explicit registry pattern is the template for feature/strategy/executor contracts.
- Stopping at paper fills (not resolution/eval) keeps M4 reviewable while proving the full tick path works.

## 2. Scope

### In scope

- **Feature layer:** shared migration `003` adding `feature_value`; `FeatureProvider` ABC + tri-state `FeatureValue` DTO; explicit registry; three statistical providers:
  - `ensemble_mean_temp` — mean ensemble temperature for a location/valid window
  - `forecast_disagreement` — spread between GFS and ECMWF ensemble means
  - `kalshi_spread` — bid-ask spread from latest market snapshot
- **Strategy layer:** `Strategy` ABC (pure function contract) + explicit registry + AST purity guard; one or two weather strategies (e.g. `weather_ensemble_disagreement`, `weather_stale_quote`).
- **Risk/sizing:** deterministic `core/risk` — fractional Kelly with confidence weighting, free-cash gate, global exposure cap, simple correlation cap, `max_input_age` freshness check → `Order` or `Rejection` mapped to existing `SignalOutcome` enum.
- **Paper executor:** `Executor` ABC + `paper_executor` filling against latest `raw_market_snapshot`, writing positions/fills/cash through `core/ledger` only.
- **Tick orchestration:** scheduler hook after ingestion — compute features → evaluate strategies → size → execute → persist every signal (including rejections) under one `request_id`.
- **Read API:** `GET /v1/signals` + `GET /v1/positions` (bearer-auth, read-only) + OpenAPI → TS regen.
- **Tests:** pure unit tests (features, strategies, sizing); integration test (fake clock, seeded shared rows → expected `signal` + `paper_fill` rows in per-env DB); ledger AST purity guard stays green.

### Out of scope (M5+)

- Position resolution / realized P&L (needs `contract_resolution` ground-truth table).
- Eval metrics (`eval_metric_snapshot`), calibration plots, P&L dashboard wiring.
- Replay clock, dirty-set dependency propagation, WebSocket push.
- NWS source, manifest/filesystem plugin discovery.
- Live Kalshi executor.

## 3. Architectural decisions

### 3.1 Tri-state feature values

Features are `present(value, as_of)` | `missing(reason)` | `stale(value, as_of)`. Strategies refuse to emit signals on missing required features by default; must opt in to tolerating missing. No defaulted zeros (PDD §2.6, §6.1).

### 3.2 Code layout mirrors `core/sources/`

Not the PDD's `plugins/` directory sketch yet. Contracts and implementations live under:
```
core/
  contracts/
    feature.py      FeatureProvider ABC
    strategy.py     Strategy ABC
    executor.py     Executor ABC
  features/
    registry.py     explicit list; enabled filter
    ensemble_mean_temp/
    forecast_disagreement/
    kalshi_spread/
  strategies/
    registry.py
    weather_ensemble_disagreement/
    weather_stale_quote/
  risk/
    sizing.py       Kelly + caps + freshness (NOT pluggable)
  executors/
    registry.py
    paper/
  engine/
    tick.py         orchestrates one evaluation cycle
```

### 3.3 Executor writes only through `core/ledger`

Bankroll mutations stay in `core/ledger/writer.py`. The paper executor calls ledger writer functions for position open/close and fee debits. The AST purity guard in `tests/test_ledger_purity_guard.py` stays green.

### 3.4 Correlation cap is intentionally minimal

PDD §10 flags the real correlation metric as an open question. M4 implements a permissive default (e.g. same settlement-date + same variable grouping) with a TODO for the hand-tuned similarity matrix when politics/sports markets arrive.

### 3.5 Full evaluation each tick (no dirty-set yet)

M3 deferred dirty-set propagation because there were no features/strategies to propagate to. M4 still skips it — the engine does a simple full evaluation on each scheduler wake rather than walking a dependency graph. Dirty-set arrives when the plugin count justifies the complexity.

## 4. Tick flow (wall clock)

```
Scheduler wakes (after ingestion source completes, or on a fixed engine interval)
  → For each enabled FeatureProvider: compute(as_of <= clock.now()) → feature_value row
  → For each enabled Strategy in SIGNAL_EMITTING state:
       evaluate(market_state, features) → Signal | None
       → signal row written (per-env DB, with feature snapshot)
       → Risk/sizing: Kelly + caps + freshness → Order | Rejection
       → If Order: paper_executor.place(order) → Fill
            → ledger writes: paper_position, paper_fill, cash_event (fee)
            → signal outcome = order_placed
       → If Rejection: signal outcome = rejected_* with reason
  → request_id flows through entire tick (PDD §6.1)
```

Every evaluation that produces a signal is recorded — including rejections. This is essential for later evaluation: knowing what the strategy *wanted* to do, separately from what risk let it do.

## 5. Shared-DB schema (additive migration `003`)

- **`feature_value`** — `id, provider_name, provider_version, subject_kind ENUM('market','location'), subject_id, as_of TIMESTAMPTZ, value_numeric, value_jsonb, input_hash, computed_at`; `INDEX (provider_name, subject_kind, subject_id, as_of DESC)`; `UNIQUE (provider_name, provider_version, subject_kind, subject_id, as_of)`.

Per-env tables (`signal`, `paper_position`, `paper_fill`, `cash_event`) already exist from M2 migration `002`. No per-env migration needed for M4.

## 6. Feature providers

All pure given inputs (test with synthetic raw rows). Each declares `name`, `version`, `inputs` (which raw tables/sources it reads), and `async compute(as_of, ctx) -> FeatureValue`.

### `ensemble_mean_temp`
- Input: latest `raw_forecast_run` rows for a location, filtered `as_of <= clock.now()`.
- Output: mean temperature across ensemble members for the target valid window.

### `forecast_disagreement`
- Input: GFS and ECMWF ensemble means from `ensemble_mean_temp` (or recomputed inline).
- Output: absolute difference between model means; high disagreement → potential edge signal.

### `kalshi_spread`
- Input: latest `raw_market_snapshot` for a ticker, filtered `as_of <= clock.now()`.
- Output: `ask_yes - bid_yes`; wide spread → stale-quote opportunity.

## 7. Strategies

Pure functions: `(market_state, features) → Signal | None`. No I/O, no clock access, no DB imports. AST purity guard enforces this.

### `weather_ensemble_disagreement`
- Markets: weather series from `reference_market`.
- Features needed: `ensemble_mean_temp`, `forecast_disagreement`, `kalshi_spread`.
- Logic: emit signal when forecast disagreement exceeds threshold AND market mid diverges from ensemble mean by more than spread-adjusted margin.

### `weather_stale_quote` (optional second strategy)
- Features needed: `kalshi_spread`, `ensemble_mean_temp`.
- Logic: emit signal when spread is unusually wide relative to recent history AND ensemble mean supports a directional bet.

## 8. Risk/sizing (`core/risk`)

Deterministic, not pluggable. Input: `(signal, strategy_instance, open_positions, system_state)`. Output: `Order` or `Rejection(reason)`.

Checks (in order):
1. System paused (`system_state.state == PAUSED`) → `rejected_system_paused`
2. Strategy not in `SIGNAL_EMITTING_STATES` → skip (no signal row)
3. Input freshness: any required feature `as_of` older than strategy's `max_input_age_seconds` → `rejected_stale_inputs`
4. Kelly sizing: fractional Kelly with confidence weighting; zero edge → `rejected_kelly_zero`
5. Free cash: order cost basis exceeds `bankroll - open_position_cost` → `rejected_below_min_position`
6. Global exposure cap → `rejected_exposure_cap`
7. Correlation cap (same date + adjacent region) → `rejected_correlation_cap`
8. Below confidence threshold → `rejected_below_threshold`

## 9. Paper executor

Same interface as future live executor: `async place(order) -> Fill`.

Fill simulation against latest `raw_market_snapshot`:
- Buy YES at `ask_yes`, sell YES at `bid_yes`.
- Fees: configurable flat rate (default 0 for paper).
- Writes through `core/ledger`: open/update `paper_position`, insert `paper_fill`, debit fee via `cash_event` if applicable.

Position resolution (market settles YES/NO) is M5 — M4 only opens positions and records fills.

## 10. Read API

- **`GET /v1/signals`** — paginated list; filter by `strategy_name`, `ticker`, `outcome`. Returns full signal DTO including `features_snapshot_jsonb`, `market_state_jsonb`, `outcome`, `rejection_reason`.
- **`GET /v1/positions`** — paginated list; filter by `strategy_name`, `status` (open/closed). Returns position DTO with unrealized P&L computed from latest snapshot mid.

OpenAPI → TS regen; existing CI drift check covers new schemas.

## 11. PR slicing (one concern each, ordered)

| # | PR | Concern |
|---|----|---------|
| M4.1 | Shared schema `003` — `feature_value` table + SQLAlchemy model | Backend/migration |
| M4.2 | `FeatureProvider` ABC + tri-state `FeatureValue` DTO + explicit registry | Backend |
| M4.3 | Stat feature providers (`ensemble_mean_temp`, `forecast_disagreement`, `kalshi_spread`) + unit tests | Backend domain |
| M4.4 | `Strategy` ABC + registry + AST purity guard | Backend |
| M4.5 | Weather strategy/strategies + unit tests incl. negation cases | Backend domain |
| M4.6 | `core/risk` sizing engine + unit tests | Backend |
| M4.7 | `Executor` ABC + `paper_executor` + tests | Backend |
| M4.8 | Tick orchestration in scheduler + integration test | Backend |
| M4.9 | `/v1/signals` + `/v1/positions` endpoints + OpenAPI regen | Backend/API |
| M4.10 | (optional) Minimal read-only Signals/Positions UI panel | UI |

Ten slices (nine required + one optional UI), each independently reviewable and roughly within the ~300-line target. Tests ride with the slice whose behavior they lock.

## 12. Invariants honored

- Every feature row is `as_of`-stamped; backtest queries will use `WHERE as_of <= clock.now()` (PDD §5.3).
- Shared migration `003` is additive-only.
- Strategies are pure functions — AST guard + no I/O (PDD §2.3).
- Bankroll mutations only through `core/ledger/writer.py` (PDD §7.1).
- Every signal persisted, including rejections (PDD §4.1).
- `request_id` flows through each tick (PDD §6.1).
- Fail closed: missing/stale features → no signal or `rejected_stale_inputs` (PDD §2.1, §6).

## 13. Open questions carried into implementation

- **Weather strategy thresholds** — concrete values for disagreement margin, spread percentile, confidence floor. Start with hand-tuned defaults in `config_jsonb`; tune against live data in staging.
- **Engine tick cadence** — run after each ingestion source completes, or on a fixed interval independent of ingestion? Likely piggyback on Kalshi snapshot completion for freshness.
- **Exposure cap default** — percentage of total bankroll across all strategies. Start conservative (e.g. 50%); make per-env configurable later.
- **Paper fill slippage model** — fill at quoted price (optimistic) vs mid + half-spread (realistic). Start at quoted; add slippage assumption to `simulator_assumptions_jsonb` for audit.
