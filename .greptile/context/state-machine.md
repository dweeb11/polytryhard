# Strategy state machine (pinned for code review)

The full set of `StrategyState` values and the legal transitions between them. The reviewer should flag any code that bypasses these.

---

## States (from `ui/src/lib/types.ts`)

```ts
type StrategyState =
  | 'seeded'                  // funded but no signal yet
  | 'active'                  // emitting + trading
  | 'low_bankroll_paused'     // auto-pause: bankroll < min_bankroll_cents
  | 'drawdown_paused'         // auto-pause: drawdown > max_drawdown_pct_from_hwm
  | 'operator_paused'         // manual pause
  | 'graduated'               // promoted to live
  | 'graduated_under_review'  // graduated + tighter drawdown trip; Kelly down to 25%
  | 'decommissioned';         // terminal
```

## Transition gates (from `ui/src/lib/utils.ts`)

```ts
PAUSABLE_STATES  = ['active', 'graduated', 'graduated_under_review']
RESUMABLE_STATES = ['low_bankroll_paused', 'drawdown_paused', 'operator_paused']
```

A strategy can only be operator-paused **from** a state in `PAUSABLE_STATES`.
A strategy can only be resumed **from** a state in `RESUMABLE_STATES`.
Any direct write of `state` that bypasses these gates is a bug.

## Transition rules

```
                  ┌──────────┐
   deposit ────►  │  seeded  │ ── first signal ──►  ┌──────────┐
                  └──────────┘                      │  active  │
                                                    └─────┬────┘
                          ┌─────────────────────────────  │  ──────────────┐
                    bankroll                       drawdown               operator
                    < min_bankroll                 > max_dd                pause
                          │                             │                    │
                          ▼                             ▼                    ▼
                ┌─────────────────────┐    ┌──────────────────────┐  ┌──────────────┐
                │ low_bankroll_paused │    │   drawdown_paused    │  │operator_paused│
                └──────────┬──────────┘    └──────────┬───────────┘  └──────┬───────┘
                           │                          │                     │
              deposit raising bankroll          operator action       operator resume
              over floor (auto-resume optional)
                           │                          │                     │
                           └──────────► active ◄──────┴─────────────────────┘

   ─── any state ──── operator decommission ────►  ┌──────────────┐
                                                   │decommissioned│ (terminal)
                                                   └──────────────┘
```

## Resume target rules

When resuming from `RESUMABLE_STATES`:
- If `prePauseState` was `'graduated'` or `'graduated_under_review'` → resume to that state.
- Otherwise → resume to `'active'`.
- Always clear `prePauseState = null`.

## Auto-resume on deposit

If `strategy.config.autoResumeOnDeposit && newBankroll >= min_bankroll_cents && state ∈ RESUMABLE_STATES`:
- Resume by the rule above.

## Terminal & blocked states

- `decommissioned` is **terminal**. No transitions out. Deposit / set-kelly / pause / resume are all rejected.
- Withdrawal **from** `decommissioned` is allowed (up to free cash) — only state changes are blocked.

## Kill switch

`pause_system` is a global flag, independent of strategy state. While tripped:
- Every order-placing mutator returns `rejected_system_paused`.
- Strategy state machine is unaffected (kill switch is not a state).
- Open positions are NOT auto-closed.
- Resume requires an operator-provided non-empty reason.

## What to flag in review

- Direct assignment to `state` from a state not in the legal source set for the target.
- Resume code that doesn't honor `prePauseState`.
- Code that closes open positions when the kill switch is tripped.
- Auto-resume that doesn't re-check `min_bankroll_cents`.
- Any deposit / withdraw / Kelly-change handler that doesn't first check `isSystemPaused()`.
- Code that mutates `bankrollHwmCents` outside an explicit operator HWM-reset action.
