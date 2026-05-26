# Greptile custom context

Pinned excerpts to paste into Greptile's **custom context** slot (dashboard). Distinct from `.greptile/instructions.md`, which is the rulebook.

| File | What it gives the reviewer |
|---|---|
| `pdd-invariants.md` | PDD §2 non-negotiables, §5.3 persistence invariants, §6 fail-closed semantics, §7.1 ledger invariants. The "why" behind the blocking rules in `.greptile/instructions.md`. |
| `glossary.md` | Domain vocabulary (signal, HWM, free cash, as-of, kill switch, etc.) so the reviewer doesn't misread contract-compliant code as a bug. |
| `state-machine.md` | Strategy `StrategyState` union + `PAUSABLE_STATES` / `RESUMABLE_STATES` + transition rules. Used to flag illegal transitions. |

## How to wire it

Greptile (dashboard) supports a single "custom context" payload. Two options:

1. **Concatenate** these three files and paste the result into Greptile. Simplest; one place to update.
2. **Add separately** if Greptile's UI accepts multiple context entries. Lets you toggle pieces.

Either way, **keep the source of truth here in the repo** — edit these files in PRs, then re-paste into Greptile when invariants meaningfully change. Don't edit straight in the dashboard; it diverges silently.

## Update cadence

- `pdd-invariants.md` — when `docs/PDD.md` §2, §5.3, §5.4, §6, or §7 changes.
- `glossary.md` — when a new domain term shows up in code review and the reviewer would have to guess.
- `state-machine.md` — when `StrategyState`, `PAUSABLE_STATES`, or `RESUMABLE_STATES` change.

If anything in the PDD or `types.ts` outpaces these files, the rules in `.greptile/instructions.md` start firing on the wrong premise — fix here first.
