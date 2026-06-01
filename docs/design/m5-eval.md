# M5 design — Resolution & Evaluation

> Close the loop: resolve paper positions into realized P&L and honest calibration metrics, so strategies become measurable and graduation-eligible. Same code path a backtest will later drive via a replay clock.

**Status:** Approved design, pre-implementation.
**Depends on:** M4 (engine spine: features → strategy → risk/sizing → paper executor → ledger), merged to `staging`.
**PDD references:** §1.4 (edge thesis — calibration-first), §2 (#1 fail closed, #5 ledger is source of truth), §3.3 (plugin types — Source), §4.1 (live tick), §5.1 (`contract_resolution`), §5.2 (`eval_metric_snapshot`), §6 (fail-closed), §7.4–§7.5 (HWM, graduation gate), §8.1–§8.4 (tests), §10 (resolution sourcing open question).

---

## 1. Goal & rationale

M4 closed the engine spine **through paper fills**: the system opens paper positions and records every signal. But it cannot yet answer the only question that justifies the product (PDD §1.4): *does this strategy have edge?* Positions open and never resolve; there is no realized P&L, no Brier score, no calibration.

M5 closes that feedback loop. It turns open paper positions into resolved P&L against Kalshi ground truth, then computes honest, small-sample-aware evaluation metrics — making strategies measurable and feeding the graduation gate (PDD §7.5, which needs `posterior_edge_ci_low > 0`).

Rationale for this cut over the other M4-deferred candidates:
- A live executor (PDD §1.3) would graduate strategies we have **no measured edge for** — it depends on this milestone, not parallel to it.
- A backtest replay clock generates *more* paper trades we still couldn't evaluate. Evaluation is the prerequisite.
- More inputs (NWS, plugin discovery) add breadth to a loop whose outputs aren't yet measured.

## 2. Scope

### In scope

- **Shared schema `004`:** `contract_resolution` table (append-only ground truth) + `ContractResolution` enum.
- **`kalshi_resolution` Source plugin:** conforms to the existing `Source` ABC; writes **only** to shared DB. Detects settled markets, writes idempotent `contract_resolution` rows, updates `reference_market.status`/`settlement_time`.
- **Resolution tick + ledger writers:** implement the existing `record_realized_pnl` stub (`core/ledger/writer.py:246`) plus a new `resolve_position`; a scheduled resolution tick applies new resolutions to open positions through `core/ledger` only.
- **`core/eval` pure metrics:** hit_rate, Brier, log-loss, pnl, max_drawdown, sharpe_proxy, and posterior edge (Normal-Normal on per-trade ROI); plus calibration binning.
- **`eval_metric_snapshot` writer + recompute:** per strategy × window (`7d`/`30d`/`all`), computed post-resolution and on a nightly schedule.
- **Read API:** `GET /v1/eval/{strategy}` (snapshots + calibration bins) and a roster summary; Pydantic schemas; OpenAPI → TS regen.
- **Read-only UI panel:** calibration plot + P&L + metrics table; live + mock; `regen-api-types`. Mirrors M4's read-only Signals/Positions slice.
- **Tests:** pure unit (source parse, eval functions — test-first); per-env (resolution writers); integration (seed → open → resolve → eval); UI manual acceptance.

### Out of scope (M6+)

- **Live (real-money) Kalshi executor.** Graduation criteria are *informed* by M5 metrics but promotion stays a later milestone.
- **Backtest replay clock / dirty-set propagation / WebSocket push.** M5 metrics are computed on live-tick resolutions and a schedule; no replay engine yet.
- **NWS source, manifest/filesystem plugin discovery.**
- **Drawdown auto-pause wiring** beyond a documented hook — resolution updates HWM; auto-pause on a resolution-driven drawdown breach reuses existing state logic and is verified but not extended.
- **Rubric / news features**, auto-top-up, reconciliation extensions.

## 3. Resolution ingestion — `kalshi_resolution` Source

**Decision (resolves PDD §10 sourcing question):** Kalshi's settlement API, surfaced through a dedicated **Source plugin**, not a standalone job and not folded into `kalshi_markets`. Rationale: every market we hold a position on is one we ingest, so Kalshi's per-market settlement covers 100% of our positions; and the architecture (PDD §3.3) says all shared-DB ingestion goes through `Source` plugins. Keeping resolution-ingestion (shared DB) separate from position-resolution (per-env ledger) preserves the clean DB boundary. "Record-forward only" is automatically satisfied — we never hold a position on a market we haven't been ingesting.

Behaviour:
- Targets markets with a `reference_market` row not yet resolved whose `close_time` has passed (and/or markets with open `paper_position` rows — see §10 open knob).
- Calls Kalshi market status; on `settled`/`finalized`, parses the result into `yes` / `no` / `void` and a `settlement_value`, captures the raw payload as `source_evidence_jsonb`.
- Writes a `contract_resolution` row, **idempotent on `ticker` PK** (one resolution per market). Updates `reference_market.status` and `settlement_time`.
- Reports health and last-fetch like other sources.
- **Fail closed:** unreachable, non-settled, or ambiguous/unparseable result → write nothing, log, surface degraded health. Never guess a settlement.

Parse logic is pure and unit-tested alongside `core/sources/kalshi/parse.py` (yes / no / void / not-yet-settled fixtures).

## 4. Position resolution & realized P&L (per-env ledger)

**Accounting model.** Cost basis is *reserved* at open, not spent: `free_cash = bankroll − Σ(open cost_basis)`, and `open_paper_position` only decrements bankroll for fees. So on resolution the position closes, its reservation releases, and **bankroll moves by net P&L only**.

For a position of `qty` contracts with `cost_basis_cents`:

| Resolution | Payout (cents) | `realized_pnl_cents` |
|---|---|---|
| YES position, market `yes` | `100 × qty` | `payout − cost_basis` |
| YES position, market `no` | `0` | `−cost_basis` |
| NO position, market `no` | `100 × qty` | `payout − cost_basis` |
| NO position, market `yes` | `0` | `−cost_basis` |
| any position, `void` | `cost_basis` (refund) | `0` |

(Kalshi binary contracts settle at 100¢ or 0¢; `settlement_value` from the resolution row is authoritative if Kalshi ever reports partial settlement.)

`resolve_position` (new in `core/ledger/writer.py`, the sole bankroll mutator), per open position on the resolved ticker, in **one transaction**:
1. Compute payout & `realized_pnl_cents` from the table above.
2. Write one `cash_event(kind=realized_pnl, amount=realized_pnl_cents, balance_after=bankroll+realized_pnl)` + paired `audit_event`, with `ref_position_id` and `request_id`. Void → `realized_pnl = 0`: write a zero-amount `realized_pnl` event (per §10) so every resolved position has a uniform cash-event trail.
3. Set `paper_position.status = resolved`, `closed_at`, `realized_pnl_cents`, `unrealized_pnl_cents = 0`.
4. Raise `bankroll_hwm_cents` if the new bankroll exceeds it (HWM is the running max; realized gains raise it, per §7.4 — this is **not** a deposit, so it legitimately moves HWM).

`record_realized_pnl` (the existing stub) is implemented as the cash-event primitive `resolve_position` calls.

**Resolution tick** (scheduled, `core/` — mirrors the engine tick): reads `contract_resolution` rows not yet applied (a resolution is "applied" when no `OPEN` position remains on its ticker — the position-status guard is the idempotency key, no extra bookkeeping table needed), and calls `resolve_position` for each. Generates one `request_id` per tick. Re-running is a no-op once positions are `RESOLVED`.

**Drawdown hook.** After resolution, a realized loss may push a strategy past `max_drawdown_pct_from_hwm`. M5 documents and tests this hook by reusing the existing pause/state logic; it does not build new auto-pause machinery.

## 5. Evaluation metrics — `core/eval` (pure)

New `core/eval/` module of pure functions over resolved trades (a trade = a resolved position joined to its originating signal's `prob_yes`, with binary outcome `y ∈ {0,1}` from the resolution). All test-first per CLAUDE.md (pure logic):

- `n_trades`, `n_wins`, `hit_rate = n_wins / n_trades`
- **Brier** `= mean((p − y)²)`
- **log_loss** `= −mean(y·ln(p) + (1−y)·ln(1−p))`, with `p` clamped to `[ε, 1−ε]` to avoid infinities
- `pnl_cents = Σ realized_pnl_cents`
- `max_drawdown_cents` — max peak-to-trough of the bankroll series (from `cash_event` running balance)
- `sharpe_proxy = mean(roi) / std(roi)` over per-trade ROI — labelled a proxy (not annualized)
- **posterior_edge** — see §6
- **calibration bins** — partition signals by predicted `prob_yes` into deciles; per bin emit `(predicted_mean, observed_freq, count)` for the calibration plot

Edge cases the tests pin: `n = 0` (all metrics `None`/empty, no division), all-wins / all-losses, single trade (posterior CI must be wide, not degenerate).

## 6. Posterior edge — Normal-Normal on per-trade ROI

**Decision:** edge is P&L-denominated, not win-rate-denominated, so a high win rate at bad prices correctly reads as negative edge. Per resolved trade, `roi_i = realized_pnl_i / cost_basis_i`.

Model `roi_i ~ N(μ, σ²)` with a **skeptical prior** `μ ~ N(0, τ²)` centered at zero (fail-closed ethos: assume no edge until data proves it). With sample mean `r̄`, sample variance `s²`, and `n` trades, the posterior mean shrinks the sample mean toward 0 and the credible interval widens at small `n`:

```
posterior precision:  1/τ²  +  n/s²
posterior mean  μ̂   =  (r̄ · n/s²) / (1/τ² + n/s²)
posterior var   σ̂²  =  1 / (1/τ²  +  n/s²)
ci_low / ci_high     =  μ̂  ∓  1.96 · σ̂
```

- `posterior_edge_mean = μ̂`, `posterior_edge_ci_low/high` as above.
- **Graduation gate** (PDD §7.5): `ci_low > 0` is the edge-demonstrated signal (combined with `n_trades` and calibration thresholds — gate policy itself stays out of M5).
- Prior strength **`τ = 0.5`** by default (weak: ~±50% ROI before data dominates), configurable per strategy in `config_jsonb`.
- Degenerate guards: `n = 0` → return prior (mean 0, CI from `τ`); `s² = 0` (all identical ROI, e.g. single trade) → floor `s²` at a small epsilon so the interval stays finite and wide.

## 7. Snapshots & API

- **`eval_metric_snapshot` writer** persists one row per strategy × window (`7d`/`30d`/`all`) with all §5/§6 fields. Triggered (a) after each resolution tick for affected strategies, and (b) nightly for all strategies (PDD §8.4).
- **`GET /v1/eval/{strategy}`** → latest snapshot per window + calibration bins. **`GET /v1/eval`** → roster summary (one line per strategy). Bearer-auth, read-only. Pydantic schemas in `core/api/v1/schemas.py`; OpenAPI export → `ui/src/lib/api/types.ts` regen.

## 8. UI panel (read-only)

A Calibration & P&L panel mirroring M4's read-only Signals/Positions slice: per-strategy metrics table (Brier, log-loss, hit rate, P&L, posterior edge with CI), a calibration plot (predicted vs observed with the y=x reference and per-bin counts), and a P&L-over-time view. Live + mock modes; unknowns render `—`. `npm run regen-api-types` after schema export. Manual acceptance per PDD §8.5.

## 9. Fail-closed & invariants

- Resolution source down / ambiguous → no `contract_resolution`, positions stay `OPEN`. Never guess settlement.
- `bankroll_cents == Σ cash_event.amount_cents` preserved — the `realized_pnl` event is the only balance move on resolution; nightly reconciliation (PDD §7.1) still holds.
- Idempotency: `contract_resolution` ticker PK (one per market) + position status guard (`OPEN → RESOLVED` only).
- Void refunds cost basis, never penalizes.
- All writes carry a `request_id`; resolution tick generates one per tick.
- All timestamps UTC.

## 10. Open knobs (set defaults; revisit if needed)

- **Resolution polling target set** — markets past `close_time` with unresolved `reference_market` rows, intersected with markets we hold open positions on (avoids polling the entire universe). Default: union of "open position tickers" and "unresolved closed reference_market" — start narrow (open positions only) if the universe is large.
- **`τ` prior strength** — default `0.5`, per-strategy override.
- **Calibration bin count** — default deciles (10); revisit if trade counts are too small to populate bins.
- **Void cash_event** — write a zero-amount `realized_pnl` event vs audit-only. Default: zero-amount event, for a uniform per-position resolution trail.

## 11. PR slices (ordered)

- **M5.1** Shared migration `004` — `contract_resolution` table + `ContractResolution` enum + model.
- **M5.2** `kalshi_resolution` Source plugin + pure parse unit tests.
- **M5.3** Resolution tick + `resolve_position` / `record_realized_pnl` ledger writers + per-env tests.
- **M5.4** `core/eval` pure metrics (hit rate, Brier, log-loss, drawdown, sharpe proxy, posterior edge, calibration bins) + unit tests (test-first).
- **M5.5** `eval_metric_snapshot` writer + post-resolution & nightly recompute + integration test (seed → open → resolve → eval).
- **M5.6** `/v1/eval` endpoints + schemas + OpenAPI/TS regen.
- **M5.7** Read-only Calibration & P&L UI panel + `regen-api-types`.

## 12. Verification

- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- Ledger AST purity guard stays green; strategies remain pure.
- Per-env resolution tests: YES/NO × win/loss + void assert `cash_event`, bankroll, free-cash recovery, `status=resolved`, HWM, audit pairing.
- Eval unit tests: Brier/log-loss/hit-rate/posterior against hand-computed fixtures incl. `n=0`, all-wins, single-trade.
- Integration: seeded shared snapshots/forecasts + one strategy + fake clock → open position → write `contract_resolution` → resolution tick → expected `realized_pnl` `cash_event` + `eval_metric_snapshot` rows.
- `cd ui && npm run check && npm run lint && npm run test && npm run build`.
