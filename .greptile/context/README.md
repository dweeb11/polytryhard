# Greptile custom context

Pinned excerpts for code review. Distinct from `.greptile/instructions.md`, which is the rulebook.

**Automatic reviews are off** for this repo (`skipReview: "AUTOMATIC"` in `.greptile/config.json`). Greptile runs only when you trigger it (Cursor Greptile MCP `trigger_code_review`, `@greptileai` on the PR, or dashboard).

These files are wired into every review via `.greptile/files.json` — you do **not** need to paste them into the Greptile dashboard unless you are testing without repo config.

| File | What it gives the reviewer |
|---|---|
| `pdd-invariants.md` | PDD §2 non-negotiables, §5.3 persistence invariants, §6 fail-closed semantics, §7.1 ledger invariants. The "why" behind the blocking rules in `.greptile/instructions.md`. |
| `glossary.md` | Domain vocabulary (signal, HWM, free cash, as-of, kill switch, etc.) so the reviewer doesn't misread contract-compliant code as a bug. |
| `state-machine.md` | Strategy `StrategyState` union + `PAUSABLE_STATES` / `RESUMABLE_STATES` + transition rules. Used to flag illegal transitions. |

## How to wire it

**In-repo (preferred):** `.greptile/files.json` lists `instructions.md` plus these three files. Edit here in PRs; no dashboard paste.

**Dashboard fallback:** If org settings ignore repo config, concatenate these three files into Greptile's custom context slot. Don't edit only in the dashboard — it diverges silently.

## Update cadence

- `pdd-invariants.md` — when `docs/PDD.md` §2, §5.3, §5.4, §6, or §7 changes.
- `glossary.md` — when a new domain term shows up in code review and the reviewer would have to guess.
- `state-machine.md` — when `StrategyState`, `PAUSABLE_STATES`, or `RESUMABLE_STATES` change.

If anything in the PDD or `types.ts` outpaces these files, the rules in `.greptile/instructions.md` start firing on the wrong premise — fix here first.
