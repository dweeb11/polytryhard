# M5.6 + M5.7 — Eval read API & UI panel

> Expose the `eval_metric_snapshot` data (written in M5.5) over a read-only API and surface it in the UI: a per-strategy Calibration & P&L panel and roster-level eval columns. Closes out M5.

**Status:** Approved design, pre-implementation.
**Depends on:** M5.5 (`eval_metric_snapshot` writer + recompute), merged to `staging`.
**Parent design:** `docs/design/m5-eval.md` §7 (Snapshots & API), §8 (UI panel).
**PDD references:** §5.2 (`eval_metric_snapshot`), §7.5 (graduation gate — `posterior_edge_ci_low > 0`), §8.5 (UI manual acceptance).

---

## 1. Goal & rationale

M5.4/M5.5 compute and persist honest eval metrics per strategy × window. Nothing reads them out yet — there are no `/v1/eval` routes (`core/api/v1/routes.py` has no eval references) and the UI's calibration/bankroll panels render *simulated fixture data* (the strategy detail page even shows a dev-mode disclaimer saying so).

M5.6 + M5.7 close that gap: a read-only API over the snapshots, then the UI wiring that turns the existing prototype panels into live, honest displays — making strategy edge visible to the operator and feeding the (later) graduation decision.

## 2. Scope

**In scope:**
- **M5.6** — `GET /v1/eval` (roster summary) and `GET /v1/eval/{strategy}` (latest snapshot per window + calibration bins); Pydantic read models; latest-per-window read query; OpenAPI export → TS type regen; API tests.
- **M5.7a** — per-strategy eval panel: window selector (7d/30d/all), metrics table, live calibration plot, P&L-over-time chart derived from live cash-events.
- **M5.7b** — roster eval columns on the strategies list / dashboard.

**Out of scope:**
- Any new metric computation (M5.4 owns metrics; this is read + display only).
- Writing/recompute changes (M5.5 owns that).
- Backtest replay, WebSocket push, graduation-gate policy.
- A dedicated standalone `/eval` route — eval lives on the existing strategy detail + list pages.

## 3. M5.6 — Read API

### 3.1 Read models (`core/domain/eval.py`)

Pydantic models using the existing `ApiModel`/camel-alias convention (mirrors `core/domain/trading.py`):

- `CalibrationBin` — `lower`, `upper`, `predicted_mean`, `observed_freq`, `count` (pass-through of the stored JSON).
- `EvalSnapshot` — `window`, `computed_at`, `n_trades`, `n_wins`, `hit_rate`, `brier_score`, `log_loss`, `pnl_cents`, `sharpe_proxy`, `max_drawdown_cents`, `posterior_edge_mean`, `posterior_edge_ci_low`, `posterior_edge_ci_high`, `calibration_bins: list[CalibrationBin]`. Nullable fields (`hit_rate`, `brier_score`, `log_loss`, `sharpe_proxy`) stay `float | None`.
- `StrategyEval` — `strategy_name`, `windows: list[EvalSnapshot]` (one per available window).
- `EvalRosterEntry` — `strategy_name`, `n_trades`, `hit_rate`, `brier_score`, `pnl_cents`, `posterior_edge_ci_low` (one-line summary for the `all` window). Metrics nullable for strategies with no snapshot.

### 3.2 Read query (`core/eval/read.py`)

Snapshots are append-only, so "latest" = max `computed_at` per `strategy × window`.

- `latest_snapshots(session, strategy_name) -> list[EvalMetricSnapshotRow]` — one row per window, each the most recent for that window. Implemented with a `row_number()` window function partitioned by `window` ordered by `computed_at DESC` (or correlated `max(computed_at)` subquery), not fetch-all-then-dedup.
- `roster_summary(session) -> list[...]` — latest `all`-window row per strategy, joined against `strategy_instance` so strategies with zero snapshots still appear (left join → null metrics).

Both query `per_env_db` only — the snapshot table lives in the per-env DB.

### 3.3 Routes (`core/api/v1/routes.py`)

- `GET /v1/eval` → `list[EvalRosterEntry]`. Roster summary, `all` window.
- `GET /v1/eval/{strategy}` → `StrategyEval`. All available windows + bins. `404` if the strategy does not exist; a known strategy with no snapshots returns `windows: []`.

Read-only, bearer-auth via the existing router-level `verify_bearer_token` dependency. `session: Session = Depends(per_env_db)`.

### 3.4 Contract decisions

- Roster summarizes the **`all`** window (best for cross-strategy comparison). Detail returns **all three** windows the writer produces (7d/30d/all).
- **Missing is first-class:** no snapshots → detail `windows: []`; roster entry with `null` metrics. Never fabricate zeros.
- Don't remove response fields (API contract rule). `calibration_bins` passed through verbatim from the stored JSON.

### 3.5 Type regen

`REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export python scripts/export_openapi.py` → `cd ui && npm run regen-api-types` to update `ui/src/lib/api/types.ts`.

## 4. M5.7 — UI

### 4.1 Hydration (`ui/src/lib/api/hydrate.ts` + stores)

Extend the live hydration path; mock mode keeps fixtures (`$lib/mocks`).

- Add a roster eval store (e.g. `evalRosterByStrategy` keyed by name) hydrated from `GET /v1/eval` in `hydrateLedgerFromApi`, following the existing try/`tradingHydration`-stale pattern.
- On the strategy detail page, hydrate `GET /v1/eval/{name}` (per-window snapshots) and `GET /v1/strategies/{name}/cash-events` for that strategy.
- **Calibration mapping:** map each API `CalibrationBin` → the existing `CalibrationBucket` shape (`predicted = predicted_mean`, `actual = observed_freq`, `count`). `CalibrationChart.svelte` stays untouched.
- **Bankroll mapping:** build the `BankrollPoint[]` timeline from cash-events ordered by `occurredAt`, using `balanceAfterCents`. Feeds the existing `BankrollChart.svelte`.

### 4.2 Strategy detail panel (`ui/src/routes/strategies/[name]/+page.svelte`)

- **Window selector** (7d/30d/all) controlling which `EvalSnapshot` the metrics table + calibration plot show. Default `30d`.
- **Metrics table** — hit rate, Brier, log-loss, P&L, posterior edge (mean + CI low/high), n_trades, max drawdown, sharpe proxy. Nulls render `—` (never invent values).
- **Calibration plot** — wired to the selected window's live bins (replaces simulated buckets).
- **P&L-over-time** — `BankrollChart` wired to the live cash-event balance timeline.
- Remove the "simulated fixture data" disclaimer when in **live** mode; keep it in **mock** mode (gate on `apiMode`).

### 4.3 Strategies list / dashboard (`ui/src/routes/+page.svelte`)

Add roster eval columns from the roster store — Brier, posterior edge CI-low, P&L (`all` window) — to the strategy table. `—` for strategies with no snapshot. Lets the operator compare edge at a glance.

### 4.4 UI verification

`cd ui && npm run check && npm run lint && npm run test && npm run build`. Manual acceptance per PDD §8.5: live mode shows real metrics; mock mode unchanged; unknowns render `—`; window selector switches the displayed snapshot.

## 5. PR slices (ordered, target ≤ ~300 lines each)

1. **M5.6** — `core/domain/eval.py`, `core/eval/read.py`, `/v1/eval` + `/v1/eval/{strategy}` routes, API tests, OpenAPI export, `regen-api-types` committing the `types.ts` diff.
2. **M5.7a** — per-strategy eval panel: hydration for detail eval + cash-events, calibration/bankroll mappers, window selector, metrics table, live calibration + bankroll, live-mode disclaimer removal.
3. **M5.7b** — roster store hydration + eval columns on the strategies list / dashboard.

Each branches from `staging`, PRs target `staging`. Branch naming `feat/<linear-id>-<slug>`.

## 6. Testing

| Layer | Approach |
|-------|----------|
| Read query (`latest_snapshots`, `roster_summary`) | Test alongside — per-env SQLite: latest-wins-over-older, one row per window, empty strategy, multi-strategy roster |
| API routes | `api_client` fixture — roster happy path, detail all-windows + bins, empty strategy (`windows: []` / null roster metrics), `404` unknown strategy |
| UI mappers (bins → buckets, cash-events → bankroll timeline) | Vitest unit, mirroring `hydrate.spec.ts` |
| UI panel / columns | Manual acceptance (visual/interaction) per PDD §8.5 |

## 7. Invariants honored

- **Missing is first-class** — null metrics / empty windows surface as `—`, never defaulted zeros.
- **Read-only** — no ledger or snapshot mutation; bearer-auth on all `/v1/eval` routes.
- **API contract** — Pydantic schemas in the domain/`schemas` layer; no response fields removed; `types.ts` regenerated, not hand-edited.
- **UTC** — `computed_at` / `occurred_at` are UTC; the UI labels timezone on display.

## 8. Open items / defaults chosen

- **Roster window = `all`.** If a shorter recency view is wanted on the list later, add a `?window=` query param (not in this scope).
- **Detail default window = `30d`** in the selector.
- **Calibration mapping is lossy on purpose** — the chart only needs `(predicted, actual, count)`; bin edges (`lower`/`upper`) are carried in the API for future use but not plotted in M5.7.
