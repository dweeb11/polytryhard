# PDD invariants (pinned for code review)

Excerpted verbatim from `docs/PDD.md`. Pinned so the reviewer always has these in context, even on small diffs. **Source of truth is the PDD** — if this file drifts, update it (or delete it and re-pin).

---

## §2. Core principles (non-negotiables)

Listed in priority order. Every later decision is checked against these.

1. **Fail closed.** When in doubt — degraded source, stale feature, suspicious rubric, executor error, breached cap — the system refuses to act and surfaces the reason. Inaction has bounded cost (a missed trade). Action on bad data has unbounded cost.
2. **AI is in the feature layer, never in the decision path.** LLMs produce versioned, cached, calibrated numeric features. Strategies and risk/sizing are deterministic.
3. **Strategies are pure functions** of `(market_state_at_t, features_as_of_t) → (probability, confidence)`. No I/O, no clock access, no LLM calls.
4. **Same code path for live and backtest**, separated only by a clock abstraction and a time-aware data layer. Look-ahead bias is prevented structurally, not by review.
5. **Ledger is the source of truth.** Bankroll only changes through paired `cash_event` writes. Nightly reconciliation enforces it.
6. **"Missing" is a first-class feature value.** No defaulted zeros. A missing forecast is not a forecast of zero.
7. **Risk and ledger are not pluggable.** Strategies, sources, features, rubrics, executors are. Risk and ledger are the safety floor.
8. **Recovery is operator-initiated** in MVP. The system surfaces what's wrong; the human decides what to do.

---

## §5.3 Key persistence invariants

1. **`feature_value.as_of`** is the load-bearing column. Every backtest query is `WHERE as_of <= clock.now()`. The `UNIQUE (provider, version, subject, as_of)` prevents accidental duplicate writes during retries.
2. **`rubric_score`** keyed by `(rubric_name, rubric_version, input_hash)` is the cache. Same article + same rubric version = never re-scored. Bump rubric version → new scores generated lazily.
3. **Migration discipline:** shared migrations are **additive-only** (new columns nullable; new tables; never destructive renames without backfill). Per-env migrations can be destructive — drop and recompute from shared if needed.
4. **No denormalized history tables.** Positions/portfolio snapshots are derivable from `paper_fill` + `cash_event`. Resist denormalization until a real query is too slow.

### §5.4 Promotion is code-merge, never data-merge

`staging` → `main` promotion is a git merge plus an Alembic migration. **No database merging operations.** Per-environment data (paper ledgers, signals) is never merged — staging metrics are tainted by buggy in-development code by definition. Graduated-strategy track records are *re-derived* by re-running the backtest against shared historical data in `main`.

---

## §6. Failure modes & fail-closed semantics

| Failure | Behavior |
|---|---|
| Source unreachable | Mark source `degraded`; dependent features freeze at last `as_of`; dependent strategies pause emissions; no orders. |
| Stale data | Past-TTL feature values are treated as **missing**, not stale-but-usable. |
| Feature compute error | Don't write the bad value; strategy sees the feature as missing → no signal. |
| Rubric drift | Rubric flagged `unreliable`; downstream features missing until reviewed; historical scored data not invalidated. |
| Executor error | Executor returns explicit `OrderResult` enum, not exceptions. Log; don't blind-retry; after N consecutive errors, pause strategy. |
| Risk-layer breach | Signal recorded with `outcome=rejected_*` and reason; no order; repeated same-kind rejections → auto-pause. |

### §6.1 Cross-cutting safety rules

- **Circuit breakers on every external call.** Default: 3 failures in 60s → open 5 min → half-open probe → close on success.
- **`Missing` is a first-class feature value.** Features are `present(value)`, `missing(reason)`, or `stale(value, as_of)`. Strategies refuse to emit on missing required features by default.
- **Order placement gated on freshness contract.** Every signal carries the `as_of` of its inputs; risk layer rejects orders whose inputs exceed strategy's declared `max_input_age`.
- **`pause_system` kill switch** is a single atomic flag. When tripped, all executors return `rejected_system_paused`. **Open positions are NOT auto-closed** — closing on a kill switch is itself a trading decision. Resume requires explicit operator action with logged reason.
- **Audit log is structured.** Every state change writes `audit_event` with `actor`, `action`, `target`, `before_state`, `after_state`, `reason`, `request_id`.
- **`request_id` flows through every tick** — scheduler → source → feature → strategy → sizing → executor → ledger. One ID reconstructs any tick.

---

## §7.1 Ledger invariants

1. **Bankroll never moves outside a `cash_event` write.** One module (`core/ledger`) owns all ledger writes. No `UPDATE strategy_instance SET bankroll_cents = …` exists anywhere else.
2. **`strategy.bankroll_cents == SUM(cash_event.amount_cents WHERE strategy=X)`** at all times. Nightly reconciliation asserts this; discrepancy trips the kill switch.
3. **`free_cash = bankroll - SUM(open_position.cost_basis)` ≥ 0.** Withdrawals cannot exceed free cash; order sizing cannot exceed free cash. Both gates enforced independently.
4. **Negative bankroll is impossible by construction.** Sizing rejects orders whose cost basis would exceed free cash; executor rejects any fill that would cause negative balance.

### §7.4 HWM rules

- HWM = running max of bankroll.
- Drawdown = `(hwm - bankroll) / hwm`.
- **HWM resets only on explicit operator action.** A deposit does NOT silently raise HWM — otherwise topping up a bleeding strategy would mask the loss.
- On auto-pause, open positions stay open (closing is a trading decision).

### §7.6 Withdrawal rules

- Cannot exceed `free_cash` (open-position capital is reserved).
- `force_close_and_withdraw` is the only operator action that closes positions on intent; deliberately two-step (close, confirm, withdraw).
- Withdrawing from a `decommissioned` strategy is allowed up to free cash.
