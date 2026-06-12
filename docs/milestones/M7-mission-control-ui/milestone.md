# M7: Mission Control UI

> Redesign the UI to the approved "Mission Control" direction (Tokyo Night theme): an overview that answers the four operator questions at a glance, and a strategy page that reads in plain language.

## Process
- [x] Vision — surfacing what matters at a glance; human-readable strategy data
- [x] Design — docs/design/ui-redesign/option-a-mission-control.html (approved mockup, Tokyo Night)
- [x] Milestone — this doc
- [x] Implement
- [ ] **Verify** <- current stage (local gates + dev-mode verify done; staging spot-check after merges)
- [ ] Ship

## Tasks

PRs merge in order; each is one concern. The soak on staging survives deploys (state in Postgres, ticks idempotent), but merging back-to-back minimizes api restarts.

### PR 1 — `feat/ui-tokyo-theme` (shell + theme)
- [x] Tokyo Night `@theme` palette in `ui/src/app.css` + self-hosted fonts (@fontsource JetBrains Mono, Archivo)
- [x] Layout shell restyle (`+layout.svelte`): topbar wordmark, env chip, kill-switch button, tab-style nav
- [x] Commit design mockups + this milestone doc

### PR 2 — `feat/ui-overview-redesign` (overview page)
- [x] Pure helpers + tests FIRST: `humanizeTicker`, `outcomeLabel`, `strategyVerdict`, `attentionItems`
- [x] `Sparkline.svelte` component (bankroll history)
- [x] Overview page: status strip, attention queue, strategy verdict cards, signal tape, sources panel

### PR 3 — `feat/ui-strategy-redesign` (strategy detail page)
- [x] Config rows in plain English (`strategyConfigDisplay.ts` rewrite) + tests
- [x] Detail page: verdict paragraph, vitals strip, controls row, day-grouped signals, humanized cash ledger

## Notes
Implementation plan: docs/design/ui-redesign/implementation-plan.md. Visual source of truth: the option-a mockup. No API/schema changes — UI consumes existing stores/eval endpoints only. Mock fixtures unchanged.
