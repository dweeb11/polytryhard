# polytryhard — Product Design Document

> A statistical research lab for prediction markets. Paper-trades Kalshi via pluggable strategies, evaluates them honestly, graduates winners to live execution. AI is used as a feature extractor, never as a decision maker.

**Status:** Frontend prototype (mock data, live UI). Reviewed 2026-05-25.
**Owner:** Dave (designer + assistant producer); Claude (producer + engineer).
**Repo home:** `~/projects/apps/polytryhard/` (GitHub: `git@github.com:dweeb11/polytryhard.git`, canonical).
**Deployment:** Coolify on lxc-107, mirroring TradeBrain's pattern. `main` and `staging` branches deployed as separate Coolify apps.

---

## 1. Overview

### 1.1 Purpose

polytryhard is a self-hosted, Dockerized **strategy research platform** for prediction markets. The goal is to find statistical edges in Kalshi event contracts, evaluate them honestly across paper trading and historical backtests, and graduate the winners to live execution.

It is **explicitly not**:
- A latency-arb / market-making system (different infrastructure category entirely)
- An LLM-driven trading agent (LLMs are stochastic; trading decisions must not be)
- An extension of TradeBrain (TradeBrain's first non-negotiable is "no automated trading — ever"; polytryhard does automated execution and so must be its own app)

### 1.2 MVP scope

The first shippable slice is **paper-trade Kalshi end-to-end on weather markets**. Concretely:

- Ingest Kalshi weather markets (orderbook + last trade) and NOAA/NWS + Open-Meteo (GFS, ECMWF ensemble) forecasts
- Run 1–3 hand-authored weather strategies in parallel against a paper executor
- Backtest those strategies against historical data using the same code path as live
- Operator dashboard: per-strategy P&L, calibration, controls (deposit / withdraw / pause / resume / kill switch), source health

### 1.3 What's deferred

- **Live (real-money) Kalshi execution.** Wired behind the same executor interface, off in MVP.
- **Polymarket integration.** Polymarket has effectively no weather markets and is offshore/crypto-based with US-person restrictions. Re-enters the picture when we expand to politics/sports markets where it's a useful comparison-data source.
- **News / event-driven features (LLM rubric scoring).** The architecture supports them; the MVP weather strategies don't need them. Rubric infrastructure arrives with the first news-using strategy.
- **Auto-top-up from reserve pools, auto-rebalancing, auto-recovery.** All recovery is operator-initiated in MVP.

### 1.4 Edge thesis

We are not faster than the market. We are betting that the market is **mispriced over hours-to-days relative to better-calibrated public forecast models**, and that we can identify those mispricings with disciplined statistical methods. This thesis informs every architectural choice — reactive (not sub-second) tick model, statistical (not microstructure) features, calibration-first (not P&L-first) evaluation.

We adopt an **explore-first** posture: build the platform, try multiple strategies in parallel, let measured calibration + Bayesian edge estimates decide which graduate to live trading.

---

## 2. Core principles (non-negotiables)

These are the rules every later decision is checked against. Listed in priority order.

1. **Fail closed.** When in doubt — degraded source, stale feature, suspicious rubric, executor error, breached cap — the system refuses to act and surfaces the reason. Inaction has bounded cost (a missed trade). Action on bad data has unbounded cost.
2. **AI is in the feature layer, never in the decision path.** LLMs produce versioned, cached, calibrated numeric features. Strategies and risk/sizing are deterministic.
3. **Strategies are pure functions** of `(market_state_at_t, features_as_of_t) → (probability, confidence)`. No I/O, no clock access, no LLM calls.
4. **Same code path for live and backtest**, separated only by a clock abstraction and a time-aware data layer. Look-ahead bias is prevented structurally, not by review.
5. **Ledger is the source of truth.** Bankroll only changes through paired `cash_event` writes. Nightly reconciliation enforces it.
6. **"Missing" is a first-class feature value.** No defaulted zeros. A missing forecast is not a forecast of zero.
7. **Risk and ledger are not pluggable.** Strategies, sources, features, rubrics, executors are. Risk and ledger are the safety floor.
8. **Recovery is operator-initiated** in MVP. The system surfaces what's wrong; the human decides what to do.

---

## 3. Architecture

### 3.1 System overview

```
                              ┌─────────────────────────────────┐
                              │     SvelteKit Dashboard (UI)    │
                              │  strategies · positions · P&L · │
                              │   calibration · controls · logs │
                              └────────────────┬────────────────┘
                                               │ REST + WS
                              ┌────────────────┴────────────────┐
                              │     FastAPI Control Plane       │
                              │  /v1/* — auth, ledger reads,    │
                              │   start/stop, deposit/withdraw  │
                              └────────────────┬────────────────┘
                                               │ in-process
   ┌──────────┬──────────┬──────────┬─────────┴──────┬──────────┬─────────────┐
   │Ingestion │ Feature  │ Strategy │ Risk & Sizing  │ Executor │ Ledger /    │
   │schedulers│ providers│  engine  │   (Kelly +     │ (paper / │ Evaluation  │
   │ (Kalshi, │ (stat +  │ (pure fn │  exposure /    │  live    │ (Brier,     │
   │  NWS,    │  rubric- │  per     │  correlation   │  Kalshi  │  log-loss,  │
   │  GFS,    │  scored, │  strat)  │  caps)         │  client) │  Bayesian   │
   │  ECMWF,  │  versioned)         │                │          │  edge)      │
   │  news)   │          │          │                │          │             │
   └────┬─────┴────┬─────┴────┬─────┴────────┬───────┴────┬─────┴──────┬──────┘
        │          │          │              │            │            │
        ▼          ▼          ▼              ▼            ▼            ▼
   ┌─────────────────────────────────────┐  ┌──────────────────────────────┐
   │  Shared DB (Postgres, append-only)  │  │  Per-Env DB (Postgres)       │
   │  raw + features + rubrics + refs    │  │  ledgers + portfolios + evals│
   └─────────────────────────────────────┘  └──────────────────────────────┘

   ┌──────────────────────────────────────────────────────────┐
   │  Clock abstraction (live = wall, backtest = replay)      │
   │  All data lookups go through clock-aware queries.        │
   └──────────────────────────────────────────────────────────┘
```

### 3.2 Deployment topology

**Monolith deploy unit, plugin architecture internally.** Two orthogonal choices:

- *Deployment:* one FastAPI app per environment (`polytryhard-main`, `polytryhard-staging`), each its own Coolify service on lxc-107. Schedulers run as asyncio background tasks in the same process. Simplest to operate, debug, and reason about. Refactor path to a separate ingestion worker is preserved (every ingestion source plugin writes only to the shared DB — natural extraction seam).
- *Internal code organization:* a small stable **core** + many **plugins** that conform to typed contracts and auto-register at startup.

### 3.3 Core vs plugins

**The core** (small, stable, owns invariants):

- Control plane (FastAPI app, REST + WS, auth, lifecycle controls)
- Scheduler (asyncio task supervisor)
- Clock abstraction (live vs replay)
- Plugin registry (discovers + loads plugins at startup; reads manifests)
- Persistence layer (shared + per-env DB sessions, base entities, migrations)
- Domain types / DTOs: `MarketState`, `FeatureBundle`, `Signal`, `Order`, `Fill`, `CashEvent`
- Risk & sizing engine (not pluggable — safety floor)
- Ledger & evaluation (not pluggable — single source of truth)

**Plugin types** (each is a directory under `plugins/<type>/<name>/` with a `manifest.toml`):

| Type | Contract | MVP examples |
|---|---|---|
| Ingestion source | `name; schedule; async fetch(clock) -> [RawRecord]` | `kalshi_markets`, `nws_forecast`, `gfs_ensemble`, `ecmwf_open_meteo` |
| Feature provider | `name; version; inputs; async compute(as_of, ctx) -> FeatureValue` | `ensemble_mean_temp`, `forecast_disagreement`, `kalshi_spread` |
| Rubric | YAML/JSON: `prompt, schema, model, temp, version` (loaded by the rubric-scorer feature provider) | (none in MVP) |
| Strategy | `name; markets; features_needed; evaluate(state, features) -> Signal` | `weather_ensemble_disagreement`, `weather_stale_quote` |
| Executor | `async place(order) -> Fill; async cancel(order_id)` | `paper_executor` (MVP); `kalshi_live_executor` (later) |

**Plugin manifests** declare `name`, `version`, `enabled`, `requires` (sources/features it depends on), `provides`, and `config_schema`. The dashboard renders an "Installed plugins" view where plugins can be toggled per environment without redeploying. Disabling unregisters from the next tick.

**Contract evolution discipline:** intentionally thin contracts at first. The shape is hardened by the **third** implementation, not the first. First defines the shape; second confirms or breaks it; third locks it.

### 3.4 Repo layout

```
polytryhard/
  core/
    api/                    FastAPI routes (control plane)
    scheduler.py
    clock.py
    registry.py             plugin discovery + lifecycle
    db/                     shared + per-env session factories, base entities
    domain/                 DTOs (MarketState, FeatureValue, Signal, Order, Fill, CashEvent)
    risk/                   sizing engine, exposure cap, correlation cap (NOT pluggable)
    ledger/                 paper & live ledger writers, eval metrics, reconciliation
    contracts/              abstract base classes for each plugin type
  plugins/
    sources/
      kalshi_markets/
      nws_forecast/
      gfs_ensemble/
      ecmwf_open_meteo/
    features/
      ensemble_mean_temp/
      forecast_disagreement/
      kalshi_spread/
    strategies/
      weather_ensemble_disagreement/
      weather_stale_quote/
    executors/
      paper/
    rubrics/                (empty in MVP)
  ui/                       SvelteKit + TS app
  migrations/
    shared/                 Alembic migrations for shared DB (additive only)
    per_env/                Alembic migrations for per-env DB (destructive ok)
  tests/
  docs/
  docker-compose.yml
```

---

## 4. Data flow

Three flows share the same engine.

### 4.1 Live tick

```
Scheduler wakes (cron-style, per-source schedule)
  → [Source plugin].fetch(clock=wall)
  → raw_* row written (shared DB, as_of=now)
  → Feature dirty-set: which features depend on this source?
  → For each affected [Feature provider].compute(as_of=now)
       (rubric-scored features check cache by input_hash+rubric_version first)
  → feature_value row written (shared DB, as_of=now, version=plugin_version)
  → Strategy dirty-set: which strategies subscribe to these features?
  → For each affected [Strategy].evaluate(market_state, features) → Signal
  → signal row written (per-env DB, with feature snapshot for audit)
  → Risk/sizing:
       · resolve per-strategy bankroll
       · fractional Kelly with confidence weighting
       · global exposure cap check
       · correlation cap check
       → Order  OR  Rejection(reason)
  → Executor.place(order) → Fill
  → Ledger writes: paper_fill, paper_position, cash_event (per-env DB)
  → WS broadcast → dashboard updates
```

**Reactivity, not polling.** Sources declare their own cadence in their manifests; the engine ticks only when a source produces new data. Kalshi's source plugin should use WebSocket subscription rather than polling so market-data freshness is sub-second.

**Dirty-set propagation** walks the dependency graph (sources → features → strategies) declared in plugin manifests. Without it, every source update would trigger a full system tick.

**Signals are persisted even when no order results.** Every evaluation that produces a signal is recorded with full feature snapshot, including rejections — including the rejection reason. This is essential for evaluation: knowing what the strategy *wanted* to do, separately from what risk let it do, distinguishes "strategy is good and Kelly is correctly trimming tails" from "strategy is bad and Kelly is saving us."

### 4.2 Backtest tick

Same code path as live. Differences:

- `clock` is the replay clock, not wall clock
- Source plugins are bypassed; the engine drives replay by stepping the clock and letting feature providers query `WHERE as_of <= clock.now()` against the existing shared DB
- Executor is a backtest-paper executor (same interface, deterministic fills against historical orderbook snapshots)
- Ledger writes go to a throwaway per-env DB (`polytryhard_backtest_<run_id>`)

Strategy, feature, sizing, ledger code is byte-identical between live and backtest. This is the look-ahead bias defense.

### 4.3 Control-plane action (example: deposit)

```
Dashboard click → POST /v1/strategies/{name}/deposit {amount: 1000}
  → FastAPI handler: auth check, validate
  → Atomic per-env DB transaction:
       cash_event row (kind=deposit, amount=1000, reason="manual")
       strategy_instance.bankroll_cents += 1000
       commit
  → WS broadcast: strategy bankroll changed
  → Dashboard reflects new bankroll
```

Same shape for `withdraw`, `pause_strategy`, `resume_strategy`, `pause_system`, `set_kelly_fraction`, `enable_plugin`, `disable_plugin`, `force_close_and_withdraw`.

---

## 5. Persistence schema

Two databases. **Shared** is append-only and survives the project's lifetime; **per-env** is wipeable and recomputable from shared.

### 5.1 Shared DB (`polytryhard_shared`)

```sql
-- Reference
reference_market
  ticker PK, series, title, settlement_source, settlement_ref,
  open_time, close_time, settlement_time, status, raw_jsonb

reference_location
  id PK, station_code, lat, lon, timezone, source

-- Raw ingestion (append-only, as-of stamped)
raw_market_snapshot
  id PK, ticker FK, as_of TIMESTAMPTZ, bid_yes, ask_yes, mid_yes,
  bid_size, ask_size, last_trade_price, last_trade_size,
  source_run_id, raw_jsonb
  INDEX (ticker, as_of DESC)

raw_forecast_run
  id PK, source ENUM('nws','gfs','ecmwf','open_meteo'),
  run_time TIMESTAMPTZ, ingested_at TIMESTAMPTZ,
  location_id FK, valid_window_start, valid_window_end,
  variable, value, ensemble_member NULL, raw_jsonb
  INDEX (source, location_id, variable, run_time DESC)

raw_news_article  -- arrives with news features (deferred)
  id PK, source, url UNIQUE, published_at, fetched_at,
  title, body_text, raw_jsonb

-- Derived (also append-only, also as-of stamped)
feature_value
  id PK,
  provider_name, provider_version,
  subject_kind ENUM('market','location','article'),
  subject_id,
  as_of TIMESTAMPTZ,
  value_numeric, value_jsonb,
  input_hash,
  computed_at TIMESTAMPTZ
  INDEX (provider_name, subject_kind, subject_id, as_of DESC)
  UNIQUE (provider_name, provider_version, subject_kind, subject_id, as_of)

rubric_score
  id PK,
  feature_value_id FK,
  rubric_name, rubric_version,
  input_hash,
  model, temperature,
  raw_response_jsonb,
  prompt_tokens, completion_tokens, cost_cents
  UNIQUE (rubric_name, rubric_version, input_hash)  -- cache key

-- Ground truth
contract_resolution
  ticker FK PK, resolved_at, resolution ENUM('yes','no','void'),
  settlement_value, source_evidence_jsonb
```

### 5.2 Per-environment DB (`polytryhard_main` / `polytryhard_staging` / `polytryhard_backtest_<run_id>`)

```sql
strategy_instance
  name PK,
  enabled BOOL,
  state ENUM('seeded','active','low_bankroll_paused','drawdown_paused',
             'operator_paused','graduated','graduated_under_review','decommissioned'),
  bankroll_cents BIGINT,
  initial_deposit_cents BIGINT,
  bankroll_hwm_cents BIGINT NOT NULL DEFAULT 0,
  hwm_reset_at TIMESTAMPTZ NULL,
  kelly_fraction NUMERIC,
  config_jsonb,            -- per-strategy params (thresholds, max_input_age, etc.)
  consecutive_min_position_rejections INT NOT NULL DEFAULT 0,
  graduated_at TIMESTAMPTZ NULL,
  last_state_change_at TIMESTAMPTZ NOT NULL,
  created_at, updated_at

signal
  id PK,
  strategy_name FK, ticker FK,
  evaluated_at TIMESTAMPTZ,
  prob_yes NUMERIC, confidence NUMERIC,
  features_snapshot_jsonb,
  market_state_jsonb,
  outcome ENUM('order_placed','rejected_kelly_zero','rejected_exposure_cap',
               'rejected_correlation_cap','rejected_below_threshold',
               'rejected_below_min_position','rejected_market_closed',
               'rejected_stale_inputs','rejected_system_paused'),
  rejection_reason TEXT NULL
  INDEX (strategy_name, evaluated_at DESC)
  INDEX (ticker, evaluated_at DESC)

paper_position
  id PK, strategy_name FK, ticker FK,
  side ENUM('yes','no'), opened_at, closed_at NULL,
  open_avg_price, qty,
  cost_basis_cents, realized_pnl_cents NULL,
  status ENUM('open','closed','resolved')

paper_fill
  id PK, position_id FK, signal_id FK,
  filled_at, side, qty, price, fees_cents,
  simulator_assumptions_jsonb

cash_event
  id PK, strategy_name FK, occurred_at,
  kind ENUM('deposit','withdraw','realized_pnl','fee','transfer_in','transfer_out'),
  amount_cents, balance_after_cents, reason TEXT, ref_position_id NULL

eval_metric_snapshot
  id PK, strategy_name FK, computed_at,
  window ENUM('7d','30d','all'),
  n_trades, n_wins, hit_rate, brier_score, log_loss,
  pnl_cents, sharpe_proxy, max_drawdown_cents,
  posterior_edge_mean, posterior_edge_ci_low, posterior_edge_ci_high

plugin_state
  plugin_type, plugin_name, version PK,
  enabled BOOL, config_overrides_jsonb, last_toggled_at

audit_event
  id PK, occurred_at, actor, action, target_type, target_id,
  before_state_jsonb, after_state_jsonb, reason, request_id

reconciliation_run
  id PK, env, ran_at, n_strategies_checked, n_discrepancies,
  discrepancies_jsonb, action_taken ENUM('none','kill_switch_tripped')
```

### 5.3 Key invariants

1. **`feature_value.as_of`** is the load-bearing column. Every backtest query is `WHERE as_of <= clock.now()`. The `UNIQUE (provider, version, subject, as_of)` prevents accidental duplicate writes during retries.
2. **`rubric_score`** keyed by `(rubric_name, rubric_version, input_hash)` is the cache. Same article + same rubric version = never re-scored. Bump rubric version → new scores generated lazily.
3. **Migration discipline:** shared migrations are **additive-only** (new columns nullable; new tables; never destructive renames without backfill). Per-env migrations can be destructive — drop and recompute from shared if needed.
4. **No denormalized history tables.** Positions/portfolio snapshots are derivable from `paper_fill` + `cash_event`. Resist denormalization until a real query is too slow.

### 5.4 Promotion is code-merge, never data-merge

`staging` → `main` promotion is a git merge plus an Alembic migration. **No database merging operations.** Shared data is already shared. Per-environment data (paper ledgers, signals) is environment-specific by design and is *never* merged — staging metrics are tainted by buggy in-development code by definition.

When a strategy graduates from staging to main, its track record is **re-derived** by re-running its backtest against the shared historical data in main. Same numbers, no contamination.

---

## 6. Failure modes & fail-closed semantics

| Failure | Detection | Behavior | Surfaced where |
|---|---|---|---|
| Source unreachable | Per-source health check + circuit breaker after N consecutive failures | Mark source `degraded`; dependent features freeze at last `as_of`; dependent strategies pause emissions; no orders | Dashboard source health panel; per-strategy paused badge |
| Stale data | Scheduler tracks `last_successful_fetch`; feature provider checks `as_of` age against staleness threshold in manifest | Past-TTL feature values are treated as missing, not stale-but-usable | Same |
| Feature compute error | Provider wraps compute in try/except; validates output schema; bounds-checks numeric values | Don't write the bad value; log + increment failure counter; strategy sees the feature as missing → no signal | Plugin health panel |
| Rubric drift | Background job samples recent rubric outputs; compares distribution to prior window; measures inter-rater variance | Rubric flagged `unreliable`; downstream features missing until reviewed; historical scored data not invalidated | Dashboard alert |
| Kalshi execution error | Executor returns explicit `OrderResult` enum, not exceptions | Log fill or rejection; don't blind-retry; after N consecutive errors, pause strategy | Strategy state panel |
| Risk-layer breach | Risk layer checks every order before placement | Signal recorded with `outcome=rejected_*` and reason; no order; repeated same-kind rejections → auto-pause | Signal log; strategy alert |

### 6.1 Cross-cutting

- **Circuit breakers** on every external call. Default: 3 failures in 60s → open 5 min → half-open probe → close on success. Per-source configurable in manifest.
- **`Missing` is a first-class feature value.** Features are `present(value)`, `missing(reason)`, or `stale(value, as_of)`. Strategies refuse to emit signals on missing required features by default; must opt in to tolerating missing features.
- **Order placement gated on freshness contract.** Every signal carries the `as_of` of its inputs; risk layer rejects orders whose inputs exceed strategy's declared `max_input_age`.
- **`pause_system` kill switch** is a single atomic flag. Tripped by dashboard button or automatically by: drawdown > N% in 24h (default 10%), > N executor errors across all strategies in M minutes, operational failure (disk full, DB pool exhausted). When tripped, all executors return `rejected_system_paused`. **Open positions are not auto-closed** — closing on a kill switch is itself a trading decision. Resume requires explicit operator action with logged reason.
- **Audit log is structured.** Every state change writes `audit_event` with `actor`, `action`, `target`, `before_state`, `after_state`, `reason`, `request_id`.
- **`request_id` flows through every tick** — scheduler → source → feature → strategy → sizing → executor → ledger. Grep one ID to reconstruct any tick.

---

## 7. Ledger & bankroll lifecycle

### 7.1 Invariants

1. **Bankroll never moves outside a `cash_event` write.** One module (`core/ledger`) owns all ledger writes. No `UPDATE strategy_instance SET bankroll_cents = …` exists anywhere else.
2. **`strategy.bankroll_cents == SUM(cash_event.amount_cents WHERE strategy=X)`** at all times. A nightly reconciliation job per environment asserts this; discrepancy trips the kill switch and fires operator alert.
3. **`free_cash = bankroll - SUM(open_position.cost_basis)` ≥ 0.** Withdrawals cannot exceed free cash; order sizing cannot exceed free cash. Both gates enforced independently.
4. **Negative bankroll is impossible by construction.** Sizing rejects orders whose cost basis would exceed free cash; executor rejects any fill that would cause negative balance.

### 7.2 Strategy state machine

```
                  ┌──────────┐
   deposit ────►  │  seeded  │ ──── first signal ────►  ┌──────────┐
                  └──────────┘                          │  active  │  ◄──── operator resume
                                                        └─────┬────┘             │
                                ┌───────────────────────────  │  ───────┐        │
                          bankroll                       drawdown   operator     │
                          < min_tradeable                > max_dd    pause       │
                                │                             │         │        │
                                ▼                             ▼         ▼        │
                         ┌────────────────────┐    ┌──────────────────────┐      │
                         │ low_bankroll_paused│    │   drawdown_paused    │      │
                         │   (auto)           │    │   operator_paused    │      │
                         └─────────┬──────────┘    └──────────┬───────────┘      │
                                   │                          │                  │
                          deposit raising                operator action ────────┘
                          bankroll over floor
                          (auto-resume optional)
                                   │
                                   └──────────►  active

           ─── any state ──── operator decommission ────►  ┌──────────────┐
                                                           │decommissioned│
                                                           └──────────────┘
```

### 7.3 Per-strategy config (defaults, in `config_jsonb`)

| Parameter | Default | Effect |
|---|---|---|
| `min_bankroll_cents` | equals initial deposit at seed (M6.1); 10% of initial deposit is the long-term default target | Below → auto-pause to `low_bankroll_paused` |
| `min_tradeable_bankroll_cents` | min(initial deposit, $50 paper floor) at seed (M6.1); max(min_bankroll, Kalshi min-order × 10) long-term | Below → sizing returns `rejected_below_min_position`; auto-pause after N consecutive |
| `max_drawdown_pct_from_hwm` | 30% | Trip → auto-pause to `drawdown_paused` |
| `auto_resume_on_deposit` | true | Deposit lifting bankroll above floor → auto-`active` |
| `low_bankroll_consecutive_rejections` | 5 | Auto-pause threshold for repeated min-position rejections |
| `max_input_age_seconds` | strategy-defined | Risk layer rejects orders with older input `as_of` |

### 7.4 HWM rules

- HWM = running max of bankroll
- Drawdown = `(hwm - bankroll) / hwm`
- **HWM resets only on explicit operator action.** A deposit does not silently raise HWM — otherwise topping up a bleeding strategy would mask the loss.
- On auto-pause, open positions stay open (closing is a trading decision).

### 7.5 Graduated strategies

After a strategy is promoted from paper to live (operator action; criteria TBD per strategy but generally `n_trades > 100`, posterior edge CI low > 0, calibration acceptable), it enters `graduated` state. A tighter drawdown threshold (`graduated_max_drawdown_pct_from_hwm`, default 20%) trips to `graduated_under_review`: sizing layer drops Kelly fraction to 25% of normal, dashboard alert fires, operator decides re-promote or demote.

### 7.6 Withdrawal rules

- Cannot exceed `free_cash` (open-position capital is reserved)
- `force_close_and_withdraw` is the only operator action that closes positions on intent; deliberately two-step (close, confirm, withdraw)
- Withdrawing from a `decommissioned` strategy is allowed up to free cash

### 7.7 MVP simplification

**No auto-top-up from reserve pools.** Adding capital is operator-initiated. The `cash_event` model accommodates auto-top-up trivially (`transfer_in` with `reason='auto_top_up'`) if we ever want it.

---

## 8. Testing strategy

Five layers, each answering a different question.

### 8.1 Unit tests — purity guarantees (fast, every commit)

- **Strategies**: pure functions of `(state, features) → Signal`. Fake inputs, assert exact output, including negation tests (missing feature → no signal, sub-threshold confidence → no signal).
- **Risk/sizing**: pure. Boundary cases: zero bankroll, Kelly extremes, caps exactly reached.
- **Statistical feature providers**: pure given inputs; test with synthetic raw rows.
- **Rubric-scored feature providers**: LLM is mocked; tests validate schema enforcement, caching, bounds-checking — *not* LLM output.
- **Plugin contracts**: every registered plugin conforms to its ABC (signatures, manifest fields, declared `requires`/`provides`).
- **Purity guard**: AST scan ensures strategy modules don't import `requests`, `httpx`, `datetime` directly, or anything DB-related.

### 8.2 Integration tests — engine end-to-end with fake clock (medium, every PR)

Whole engine wired against test-Postgres, driven by fake clock and recorded fixtures.

- Seed shared DB with forecast runs + Kalshi snapshots covering a known scenario
- Enable one strategy
- Step clock in 10-min increments; assert signals, orders, positions at each step
- Verify per-env DB end state

These *are* tiny backtests because backtest and live share the engine. Look-ahead bugs caught here.

### 8.3 Contract tests for external integrations (slow)

- **Recorded contract tests** (every PR): VCR-style cassettes; parses correctly.
- **Live smokes** (nightly, read-only against real endpoints): one request per source, assert structural validity. Catches breaking API changes early. Never touches any executor.

### 8.4 Backtests as continuous evaluation (scheduled)

- **Strategy regression backtests**: nightly. Every enabled strategy runs its canonical backtest config. Assert `brier_score`, `n_trades`, `pnl_cents` within tolerance of last known good. Catches silent behavior changes from refactors.
- **Look-ahead canaries**: intentionally bugged strategies that try to read features `as_of = clock.now() + 1h`. The data layer must reject them. Canary success = look-ahead protection broken = build fails hard.
- **Rubric stability backtests**: on rubric version bump, run paired backtest (old vs new) over the same window; produce diff report (mean score, distribution shift, resulting P&L). Surfaces change for review; doesn't auto-gate.

### 8.5 Manual acceptance — UI + control plane (per CLAUDE.md)

UI gets manual acceptance criteria, not automated tests. Per-PR checklist:

- Strategy roster renders enabled/disabled correctly
- Calibration plot updates when new resolutions land
- Deposit/withdraw produce expected `cash_event` rows
- Kill switch disables all executors immediately
- Source health panel reflects degraded state

### 8.6 Explicitly out of testing

- No tests asserting LLM-output equality (validate via calibration backtests instead)
- No mocked-DB unit tests for queries (testcontainers Postgres)
- No flaky network tests in PR CI (nightly only)

---

## 9. Tech stack & deployment

| Layer | Choice |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic 2 |
| Worker / scheduler | asyncio in-process tasks (MVP); extractable to a separate worker process later |
| Database | Postgres 16 (shared + per-env), testcontainers for integration tests |
| Frontend | SvelteKit + TypeScript (Vite), chart lib TBD (uPlot / Layercake / ECharts candidates) |
| LLM (future, when rubric features land) | Anthropic SDK (Claude); cached by `(input_hash, rubric_version)` |
| Containerization | Docker + docker-compose |
| Deployment | Coolify on lxc-107, two services (`polytryhard-main`, `polytryhard-staging`) per branch |
| Secrets | Coolify env vars; `.env.example` checked in, `.env*` gitignored |
| External APIs (MVP) | Kalshi REST + WebSocket; NOAA NWS API; Open-Meteo (GFS + ECMWF) |

### 9.1 Operating model

- Single user (Dave) at MVP; simple bearer-token auth on the control plane.
- One Coolify service per environment; staging and main never share a Postgres database (per-env DB enforced), only the shared Postgres.
- Branch convention: feature branches → PR to `staging` → merge to `main` after staging soak. Each merge to either branch redeploys the corresponding Coolify service.
- Repo is canonical on GitHub (`git@github.com:dweeb11/polytryhard.git`). Standard conventional commit + AI co-author line.

---

## 10. Open questions (carried into implementation)

These were intentionally deferred during design; resolve as the relevant code lands.

- **Graduation criteria specifics.** What posterior edge CI lower bound and what `n_trades` minimum gates promotion from paper to live? Likely per-strategy override, with a default policy.
- **Correlation metric for the correlation cap.** For weather: probably "same date + adjacent regions" with a hand-tuned similarity matrix at MVP. Revisit when politics/sports markets arrive.
- **Backtest data acquisition for historical Kalshi orderbooks.** Kalshi's history API has limits; we may need to start recording snapshots forward and accept that backtests have a fixed history horizon.
- **Forecast archive sourcing.** GFS/ECMWF historical runs are available via NOMADS / Open-Meteo's archive endpoint; need to verify completeness for the locations/variables we care about.
- **Auth on the dashboard for LAN-only deployment** — Coolify SSO vs simple token. Decide before merging the auth module.

---

## Glossary

- **Feature provider**: pluggable module that turns raw data into a named, versioned, time-stamped numeric feature.
- **Rubric**: a versioned `(prompt, schema, model, temperature)` artifact used by a feature provider to score unstructured input (e.g., news articles) into bounded numeric features.
- **Signal**: a strategy's belief about a market at a moment in time — `(prob_yes, confidence, features_snapshot, market_state)`.
- **Risk/sizing**: deterministic layer that turns signals into orders (fractional Kelly, exposure cap, correlation cap, freshness check).
- **Paper executor**: simulates fills against historical/live orderbook snapshots; writes to the per-env ledger; same interface as the live executor.
- **HWM**: high-water mark of a strategy's bankroll; baseline for drawdown calculation; reset only by operator action.
- **As-of timestamp**: the moment a piece of data first became knowable; every feature query is gated on `as_of <= clock.now()`.
- **Plugin manifest**: per-plugin `manifest.toml` declaring name, version, schedule/inputs/outputs, config schema, enable state.
