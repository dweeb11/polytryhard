# Greptile review instructions — polytryhard

polytryhard is a self-hosted strategy research platform for prediction markets (Kalshi). The repo today is a frontend prototype (`ui/`, SvelteKit + Svelte 5 + TS), but the PDD (`docs/PDD.md`) defines invariants the backend will inherit. Reviews should enforce those invariants now so the prototype doesn't drift away from them.

Read `docs/PDD.md` §2 (non-negotiables), §5.3 (key invariants), and §6 (safety) before reviewing logic changes.

---

## Non-negotiables — flag as blocking

1. **Fail closed.** Degraded / missing / stale inputs MUST result in inaction with a surfaced reason, never a silent default or a guessed value. In the UI: show `—` for unknowns, never `0` or `"n/a"` as a placeholder for a missing number.
2. **AI is never in the decision path.** LLM calls are allowed only as feature extractors that emit versioned, cached, numeric features. Any PR that routes an LLM response into sizing, signal generation, risk, or order placement is rejected.
3. **Strategies are pure functions** of `(market_state_at_t, features_as_of_t) → (probability, confidence)`. No I/O, no `Date.now()`/`new Date()` inside strategy code, no network, no LLM calls. Flag any strategy code that imports a clock, fetch, or DB module.
4. **No automated broker execution against real money in this PR.** Live executors stay behind the same interface but disabled. PRs that wire a real-money executor into the default path are rejected unless the PR title explicitly says "enable live execution" and the PDD has been updated.
5. **Look-ahead bias in backtests is a structural bug, not a review nit.** Every historical query must be gated by `as_of <= clock.now()` (see PDD §5.3). Flag any backtest path that reads "current" data without an `as_of` filter.

## Ledger & money invariants

6. **Bankroll only moves through a cash-event write.** In the UI prototype the single mutation surface is `ui/src/lib/actions.ts` and the helper `appendCashEvent`. Flag any direct `strategies.update(... bankrollCents ...)` outside `actions.ts`, and any bankroll mutation that does not also write a `CashEvent`.
7. **`free_cash = bankroll - SUM(open_position.cost_basis)` ≥ 0.** Withdrawals and order sizing must independently enforce this. Flag any withdraw / sizing path that skips the free-cash gate.
8. **Money is stored as integer cents.** No floats for monetary state. Floats are only acceptable at the display boundary (`(cents / 100).toFixed(2)`). Flag `parseFloat`, `Number(...)` on money, or `* 100` rounding without `Math.round`.
9. **Negative bankroll must be impossible by construction.** A check that *logs* a negative balance is not sufficient; the operation must be refused.
10. **Timestamps are UTC ISO strings** produced via `nowIso()` (or the backend equivalent). Display layers add the timezone label (PT). Flag `new Date().toString()`, naive locale strings, or storage of non-UTC timestamps.

## State machine & control plane

11. **Strategy state transitions only via the declared `PAUSABLE_STATES` / `RESUMABLE_STATES` lists** in `ui/src/lib/utils.ts`. Flag ad-hoc transitions that bypass the gates (e.g., `state: 'active'` assignments from arbitrary prior states).
12. **Kill switch is load-bearing.** Every mutator that could place a paper or live order must call `isSystemPaused()` (or the backend equivalent) and return `rejected_system_paused`. **Open positions are not auto-closed when the kill switch trips** — closing is itself a trading decision. Flag any auto-close on kill-switch trip.
13. **Resume / kill-switch trip / decommission require an operator-provided reason.** Empty / whitespace-only reasons must be rejected, not defaulted.
14. **Plugin dependency blocking:** disabling a plugin that another enabled plugin `requires` must be refused with a clear reason.

## Audit log

15. **Every state-changing action writes an `audit_event`** with `actor`, `action`, `targetType`, `targetId`, `beforeState`, `afterState`, `reason`, `requestId`. Flag any mutator that updates a store / row without a corresponding `appendAudit` (UI) or `audit_event` insert (backend).
16. **`request_id` propagates through a tick** scheduler → source → feature → strategy → sizing → executor → ledger. When backend code lands, flag new code that drops or regenerates `request_id` mid-tick.
17. **Audit events are append-only.** No code path may update or delete an audit row. Migrations that drop audit columns require an explicit PDD update.

## UI conventions (`ui/`)

18. **Single mutation surface.** `ui/src/lib/actions.ts` is the only place that mutates `stores`. Components and routes call exported actions; they do not call `strategies.update(...)`, `positions.update(...)`, etc. directly. Flag direct store mutation in `.svelte` files or in `+page.ts` loaders.
19. **Explicit states.** Every panel must render loading / empty / error states explicitly. Flag UI that assumes data is present.
20. **No invented values.** `—` for unknowns; never `0`, `"n/a"`, `"loading"` as a stand-in for missing data.
21. **Destructive actions require confirmation.** Kill switch trip, decommission, force-close-and-withdraw, env reset — each must require explicit user confirmation in the UI (not just a button click).
22. **Svelte 5 runes / TS discipline.** `npm run check` and `npm run lint` must pass; flag PRs that disable rules instead of fixing them. No `any`; prefer the discriminated unions already in `types.ts` (`ActionResult`, `FeatureValue`).

## Git workflow (`.cursor/rules/git-workflow.mdc`)

23. **Feature PRs base on `staging`, not `main`.** Flag any feature PR opened against `main` (only `staging → main` promotion PRs target `main`).
24. **Conventional commit prefixes** (`feat/`, `fix/`, `docs/`, `refactor/`). AI-assisted commits include a co-author line.
25. **No cherry-picks onto `main`.** Promotion is the full `staging → main` PR.

## Schema & migrations (when backend lands)

26. **Shared-DB migrations are additive-only** (new nullable columns, new tables). Destructive changes require a written migration + backfill plan in the PR.
27. **Per-env DBs may be destructive,** but the PR must say so explicitly.
28. **`UNIQUE (provider, version, subject, as_of)`** on `feature_value` is load-bearing — flag any migration that weakens it.

## Documentation hygiene

29. **Docs live under `docs/`.** Do not introduce `docs/superpowers/`, `docs/plans/`, or `docs/worklogs/` (see root `CLAUDE.md`). Feature designs in `docs/design/<feature>.md`; milestones under `docs/milestones/M#-name/`.
30. **No date-prefixed filenames.** Use `M#-` for milestones, descriptive names elsewhere.
31. **PDD is the source of truth.** A code change that contradicts `docs/PDD.md` must update the PDD in the same PR or be rejected.

## What NOT to flag

- Missing tests in `ui/` while the project is still a prototype (PDD §1.2). Do flag missing tests when backend (`tradebrain-style` `app/` modules) lands and the change touches strategy / ledger / risk code.
- Mock data in `ui/src/lib/mocks/`. The UI is intentionally a live mock until the backend is wired.
- Stylistic preferences not encoded above. Prefer fewer, higher-signal comments.

## Severity guidance

- **Blocking:** anything in §Non-negotiables, §Ledger & money, §State machine, §Audit log.
- **Strong suggestion:** UI conventions, git workflow, docs hygiene.
- **Nit:** style / naming where rules don't already encode a preference.
