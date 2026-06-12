# Mission Control UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved Mission Control redesign (Tokyo Night theme) in the SvelteKit UI — at-a-glance overview, human-readable strategy pages — with zero backend changes.

**Architecture:** Three stacked PRs (theme/shell → overview → strategy detail), all confined to `ui/`. New presentation logic lives in pure, tested helpers (`ui/src/lib/humanize.ts`); pages consume existing stores (`strategies`, `signals`, `sources`, `evalRoster`, `bankrollHistoryByStrategy`). Visual source of truth: `docs/design/ui-redesign/option-a-mission-control.html`.

**Tech Stack:** Svelte 5 (runes), Tailwind 4 (`@theme` vars), vitest, @fontsource (self-hosted JetBrains Mono + Archivo).

**Deploy safety:** Coolify redeploys the whole compose app on staging push (api gets a new `SOURCE_COMMIT`), so the api container restarts for a few seconds per merge. Soak state (ledger, signals, eval windows) lives in the Postgres volume and engine ticks are idempotent — the soak run is not disrupted. Merge PRs back-to-back to collapse restarts.

---

## Task 1: Tokyo Night theme + fonts (PR 1)

**Files:**
- Modify: `ui/src/app.css`
- Modify: `ui/package.json` (add `@fontsource-variable/jetbrains-mono`, `@fontsource-variable/archivo`)

- [ ] **Step 1:** `npm install --cache .npm-cache @fontsource-variable/jetbrains-mono @fontsource-variable/archivo` in `ui/`
- [ ] **Step 2:** Replace `ui/src/app.css` theme block:

```css
@import 'tailwindcss';
@import '@fontsource-variable/jetbrains-mono';
@import '@fontsource-variable/archivo';

@theme {
	--font-sans: 'Archivo Variable', ui-sans-serif, system-ui, sans-serif;
	--font-mono: 'JetBrains Mono Variable', ui-monospace, monospace;
	/* Tokyo Night */
	--color-surface: #16161e;
	--color-panel: #1a1b26;
	--color-panel-2: #1f2335;
	--color-border: #292e42;
	--color-border-bright: #3b4261;
	--color-muted: #787c99;
	--color-faint: #565f89;
	--color-bright: #c0caf5;
	--color-heading: #dde3ff;
	--color-accent: #7aa2f7;
	--color-purple: #bb9af7;
	--color-cyan: #7dcfff;
	--color-ok: #9ece6a;
	--color-warn: #e0af68;
	--color-danger: #f7768e;
}

html, body {
	@apply h-full overflow-hidden bg-[var(--color-surface)] text-[var(--color-bright)] antialiased;
	font-family: var(--font-mono);
}
```

- [ ] **Step 3:** `npm run check && npm run lint && npm run test && npm run build` — all pass
- [ ] **Step 4:** Commit `feat: tokyo night theme palette + self-hosted fonts`

## Task 2: Layout shell (PR 1)

**Files:**
- Modify: `ui/src/routes/+layout.svelte`

- [ ] **Step 1:** Restyle per mockup, keeping ALL existing behavior (kill/resume modals, tick sim, reset, dev-mode gates, nav structure incl. strategies list + settings link):
  - Topbar: `poly<span class=accent>tryhard</span>` wordmark (Archivo 700), env chip (`$apiModeLabel`), `System: …` pill → blue `● TRADING` / red `■ PAUSED` treatment, kill-switch button styled like mockup `.kill-btn` (red outline, uppercase mono).
  - Replace slate-* utility colors with the new theme vars (`--color-panel`, `--color-border`, `--color-muted`, accent for active nav item).
  - Toasts: success → ok-green border, error → danger border on `--color-panel-2`.
- [ ] **Step 2:** `npm run check && npm run lint && npm run build`; verify in `npm run dev` (mock mode) that nav, kill switch modal, and settings pages still render legibly.
- [ ] **Step 3:** Commit `feat: mission control layout shell`; add mockups + milestone doc in a `docs:` commit; push; open PR 1 → base `staging`, body notes "1 of 3".

## Task 3: Pure humanize helpers, tests FIRST (PR 2)

**Files:**
- Create: `ui/src/lib/humanize.ts`
- Test: `ui/src/lib/__tests__/humanize.spec.ts`

- [ ] **Step 1:** Write failing tests:

```ts
import { describe, expect, it } from 'vitest';
import { humanizeTicker, outcomeLabel, strategyVerdict } from '../humanize';

describe('humanizeTicker', () => {
	it('decodes KXHIGH city/date/threshold tickers', () => {
		expect(humanizeTicker('KXHIGHNY-25MAY26-T72')).toBe('NYC high ≥ 72°F · May 26');
		expect(humanizeTicker('KXHIGHCHI-25MAY26-T68')).toBe('Chicago high ≥ 68°F · May 26');
	});
	it('falls back to the raw ticker for unknown patterns', () => {
		expect(humanizeTicker('KXBTC-25MAY26-B105')).toBe('KXBTC-25MAY26-B105');
	});
});

describe('outcomeLabel', () => {
	it('maps known outcomes to plain language', () => {
		expect(outcomeLabel('order_placed')).toBe('order placed');
		expect(outcomeLabel('rejected_below_threshold')).toBe('skipped · edge below threshold');
		expect(outcomeLabel('rejected_kelly_zero')).toBe('skipped · Kelly sized to zero');
		expect(outcomeLabel('rejected_stale_inputs')).toBe('blocked · stale inputs');
		expect(outcomeLabel('rejected_system_paused')).toBe('blocked · kill switch');
	});
	it('falls back to de-underscored text', () => {
		expect(outcomeLabel('unknown_outcome')).toBe('unknown outcome');
	});
});

describe('strategyVerdict', () => {
	it('calls a proven edge', () => {
		expect(strategyVerdict(active(), { nTrades: 142, brierScore: 0.214, posteriorEdgeCiLow: 0.008, hitRate: 0.62, pnlCents: 1127, strategyName: 's' }))
			.toMatch(/proven/i);
	});
	it('calls out a drawdown pause', () => {
		expect(strategyVerdict({ ...active(), state: 'drawdown_paused' }, null)).toMatch(/drawdown/i);
	});
	it('says needs-more-data when CI straddles zero', () => {
		expect(strategyVerdict(active(), { nTrades: 87, brierScore: 0.241, posteriorEdgeCiLow: -0.011, hitRate: 0.5, pnlCents: -10, strategyName: 's' }))
			.toMatch(/not (yet )?proven|more data/i);
	});
});
```

(`active()` is a local fixture factory returning a minimal `StrategyInstance`.)

- [ ] **Step 2:** Run `npm run test -- humanize` — FAIL (module not found)
- [ ] **Step 3:** Implement `humanize.ts`:
  - `humanizeTicker(ticker)` — regex `^KXHIGH([A-Z]+)-(\d{2})([A-Z]{3})(\d{2})-T(\d+)$`, city map `{ NY: 'NYC', CHI: 'Chicago', AUS: 'Austin', MIA: 'Miami', DEN: 'Denver', PHIL: 'Philadelphia', LAX: 'LA' }`, month map; unknown → raw.
  - `outcomeLabel(outcome)` — explicit map for the 9 `KNOWN_SIGNAL_OUTCOMES`; default de-underscore.
  - `outcomeTone(outcome)` — `'placed' | 'skip' | 'block'` for styling (placed / rejected-informational / rejected-protective).
  - `strategyVerdict(strategy, evalEntry)` — one sentence: paused states first ("Hit its N% drawdown stop — decide: refund or retire"), then edge CI-low > 0 → "Profitable & calibrated over N trades — proven edge", CI-low ≤ 0 → "Edge not yet proven over N trades — needs more data", no eval → "No resolved trades yet".
- [ ] **Step 4:** `npm run test -- humanize` — PASS
- [ ] **Step 5:** Commit `feat: humanize helpers for tickers, outcomes, verdicts`

## Task 4: Sparkline component (PR 2)

**Files:**
- Create: `ui/src/lib/components/Sparkline.svelte`

- [ ] **Step 1:** Props `{ points: BankrollPoint[]; tone: 'ok' | 'danger' | 'muted' }`; render 120×36 SVG polyline normalized to min/max; empty points → render nothing. Pure presentational; no tests (UI per testing table).
- [ ] **Step 2:** Commit `feat: sparkline component`

## Task 5: Overview page (PR 2)

**Files:**
- Modify: `ui/src/routes/+page.svelte`

- [ ] **Step 1:** Rebuild per mockup, all data from existing stores:
  - **Status strip:** total bankroll (Σ `bankrollCents`), today (Σ `todayPnlCents` + order/skip/block counts from today's `signals`), proven edge count (`evalRoster` CI-low > 0), system state (pulse dot).
  - **Attention queue:** derived list — strategies in `RESUMABLE_STATES` (with reason from state), sources not `healthy` or last fetch > 1h, kill switch active. Empty → render "all clear" line.
  - **Strategy cards:** name, `StateBadge`, `strategyVerdict(...)`, today P&L large, `Sparkline` from `bankrollHistoryByStrategy`, footer bank/edge/brier/dd; keep Pause/Resume buttons + existing action handlers; card links to detail page.
  - **Signal tape:** today's signals (all strategies), `humanizeTicker`, `p(yes)` %, `outcomeLabel` colored by `outcomeTone`.
  - **Sources panel:** dot tone by state, `formatAge`, keep dev-mode Probe button.
- [ ] **Step 2:** Full gate `npm run check && npm run lint && npm run test && npm run build`; verify in dev (mock fixtures) overview matches mockup structure; empty/loading states show `—`.
- [ ] **Step 3:** Commit `feat: mission control overview`; push; open PR 2 → base = PR 1 branch, "2 of 3".

## Task 6: Config rows in plain English, tests first (PR 3)

**Files:**
- Modify: `ui/src/lib/strategyConfigDisplay.ts`
- Test: `ui/src/lib/__tests__/strategyConfigDisplay.spec.ts` (extend)

- [ ] **Step 1:** Add failing tests: `strategyBaselineConfigRows` labels become sentences — `['Pause if bankroll drops below', '$50.00']`, `['Stop trading at drawdown', '12.0% from HWM']`, `['Ignore inputs older than', '45 min']` (seconds → min when ≥ 120s); soak rows keep per-strategy knobs with English labels (`'Only trade when confidence ≥'`, etc.).
- [ ] **Step 2:** Run — FAIL on labels
- [ ] **Step 3:** Update label strings + `maxInputAgeSeconds` formatting; PASS
- [ ] **Step 4:** Commit `feat: strategy config rows in plain english`

## Task 7: Strategy detail page (PR 3)

**Files:**
- Modify: `ui/src/routes/strategies/[name]/+page.svelte`

- [ ] **Step 1:** Rebuild per mockup, preserving every action (deposit/withdraw/pause/resume/kelly/force-close/decommission modals, window selector, live `hydrateStrategyEval`):
  - Verdict paragraph under the title from `activeSnapshot` (trades/wins/P&L, Brier, calibration note from worst high-bucket deviation, edge CI in "worst-case bound" language). No snapshot → "No eval data yet — needs resolved trades."
  - Vitals strip: bankroll (+free/in-positions via `freeCashCents`), P&L window, edge worst-case, hit rate, drawdown vs stop.
  - Controls as a horizontal row above the fold (existing handlers unchanged).
  - Charts: keep `BankrollChart`/`CalibrationChart` (restyle props/colors only), keep "How to read" details block, add amber-bucket insight line.
  - Signals: group by day (`Today`, `Yesterday`, else date), `humanizeTicker` + raw ticker small, `p(yes)`, `outcomeLabel`; keep outcome filter (options labeled via `outcomeLabel`).
  - Cash events: kind chip (won trade / lost trade / fee / deposit / withdraw via map on `CashEventKind` + sign), reason in quotes, amount + running balance columns.
  - Config: baseline + soak rows from Task 6 under "Rules this strategy runs under".
- [ ] **Step 2:** Full gate + dev-mode verify both a healthy strategy and the paused fixture; `Strategy not found` path intact.
- [ ] **Step 3:** Commit `feat: mission control strategy page`; push; open PR 3 → base = PR 2 branch, "3 of 3".

## Task 8: Verify + ship
- [ ] Full gate green on PR 3 head: `npm run check && npm run lint && npm run test && npm run build`
- [ ] Update M7 milestone checkboxes; PRs reviewed/merged in order; after staging deploy, spot-check `https://staging-event-market.critterhaus.net` (live mode, soak data renders, header shows Live backend)
- [ ] Confirm soak continuity post-deploy: `/healthz` ok and latest engine tick + eval windows still advancing
