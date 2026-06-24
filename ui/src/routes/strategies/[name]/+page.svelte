<script lang="ts">
	import { page } from '$app/stores';
	import {
		strategies,
		signals,
		cashEvents,
		positions,
		calibrationByStrategy,
		bankrollHistoryByStrategy,
		systemPaused
	} from '$lib/stores';
	import BankrollChart from '$lib/components/BankrollChart.svelte';
	import CalibrationChart from '$lib/components/CalibrationChart.svelte';
	import StateBadge from '$lib/components/StateBadge.svelte';
	import Modal from '$lib/components/Modal.svelte';
	import {
		deposit,
		withdraw,
		pauseStrategy,
		resumeStrategy,
		setKellyFraction,
		forceCloseAndWithdraw,
		decommission
	} from '$lib/actions';
	import { isDeveloperMode } from '$lib/stores/uiMode';
	import {
		compareIsoDesc,
		compactIsoTime,
		drawdownPct,
		formatCents,
		freeCashCents,
		groupItemsByDayLabel,
		PAUSABLE_STATES,
		RESUMABLE_STATES
	} from '$lib/utils';
	import { pushToast } from '$lib/stores/toasts';
	import { humanizeTicker, outcomeLabel, outcomeTone, strategyVerdict } from '$lib/humanize';
	import {
		strategyBaselineConfigRows,
		strategySoakConfigRows
	} from '$lib/strategyConfigDisplay';
	import { evalByStrategy, evalRoster } from '$lib/stores';
	import { hydrateStrategyEval } from '$lib/api/hydrate';
	import { apiMode } from '$lib/api/mode';
	import {
		activeEvalSnapshot,
		calibrationBucketsForSnapshot,
		evalWindowOptions,
		findOverconfidentHighBin,
		isBrierTight,
		isEdgeProven,
		resolveSelectedEvalWindow
	} from '$lib/evalAnalytics';
	import type { CashEvent } from '$lib/types';

	const name = $derived($page.params.name ?? '');
	const strat = $derived($strategies.find((s) => s.name === name));
	const stratSignals = $derived(
		$signals
			.filter((s) => s.strategyName === name)
			.sort((a, b) => compareIsoDesc(a.evaluatedAt, b.evaluatedAt))
	);
	const history = $derived($bankrollHistoryByStrategy[name] ?? []);
	const stratCash = $derived(
		$cashEvents
			.filter((c) => c.strategyName === name)
			.sort((a, b) => compareIsoDesc(a.occurredAt, b.occurredAt))
			.slice(0, 10)
	);

	let selectedWindow: string = $state('30d');

	$effect(() => {
		if (name && $apiMode === 'live') {
			hydrateStrategyEval(name).catch((err) => {
				console.error(`Failed to load eval for ${name}`, err);
				pushToast('error', `Could not refresh eval data for ${name}`);
			});
		}
	});

	const evalWindows = $derived($evalByStrategy[name]?.windows ?? []);
	const windowOptions = $derived(evalWindowOptions(evalWindows));

	$effect(() => {
		if (evalWindows.length === 0) return;
		const resolved = resolveSelectedEvalWindow(evalWindows, selectedWindow);
		if (resolved !== selectedWindow) selectedWindow = resolved;
	});
	const activeSnapshot = $derived(activeEvalSnapshot(evalWindows, selectedWindow));

	const calibration = $derived(
		calibrationBucketsForSnapshot(activeSnapshot, $calibrationByStrategy[name] ?? [])
	);
	const freeCash = $derived(strat ? freeCashCents(strat, $positions) : 0);
	const inPositions = $derived(strat ? strat.bankrollCents - freeCash : 0);

	const overconfidentHigh = $derived(
		activeSnapshot ? findOverconfidentHighBin(activeSnapshot.calibrationBins) : null
	);
	const edgeProven = $derived(
		activeSnapshot != null && isEdgeProven(activeSnapshot.posteriorEdgeCiLow)
	);

	let depositModal = $state(false);
	let withdrawModal = $state(false);
	let forceModal = $state(false);
	let decomModal = $state(false);
	let amountDollars = $state('100');
	let amountError = $state('');
	let reason = $state('');
	let kellyPct = $state(25);
	let kellyOwner = $state('');
	let outcomeFilter = $state('all');

	function parseAmountCents(): number | null {
		const parsed = Math.round(Number(amountDollars) * 100);
		if (!Number.isFinite(parsed) || parsed <= 0) {
			amountError = 'Enter a positive dollar amount';
			return null;
		}
		amountError = '';
		return parsed;
	}

	const filteredSignals = $derived(
		outcomeFilter === 'all'
			? stratSignals
			: stratSignals.filter((s) => s.outcome === outcomeFilter)
	);

	const signalsByDay = $derived(
		groupItemsByDayLabel(filteredSignals.slice(0, 40), (sig) => sig.evaluatedAt)
	);

	const cashByDay = $derived(groupItemsByDayLabel(stratCash, (c) => c.occurredAt));

	function cashKind(c: CashEvent): { label: string; cls: string } {
		if (c.kind === 'realized_pnl') {
			return c.amountCents >= 0
				? { label: 'won trade', cls: 'text-[var(--color-ok)]' }
				: { label: 'lost trade', cls: 'text-[var(--color-danger)]' };
		}
		if (c.kind === 'deposit' || c.kind === 'transfer_in')
			return { label: c.kind === 'deposit' ? 'deposit' : 'transfer in', cls: 'text-[var(--color-cyan)]' };
		if (c.kind === 'withdraw' || c.kind === 'transfer_out')
			return { label: c.kind === 'withdraw' ? 'withdraw' : 'transfer out', cls: 'text-[var(--color-warn)]' };
		return { label: 'fee', cls: 'text-[var(--color-faint)]' };
	}

	const toneClass: Record<string, string> = {
		placed: 'text-[var(--color-ok)]',
		skip: 'text-[var(--color-muted)]',
		block: 'text-[var(--color-warn)]'
	};

	const baselineConfigRows = $derived(strat ? strategyBaselineConfigRows(strat.config) : []);
	const soakConfigRows = $derived(
		strat ? strategySoakConfigRows(strat.name, strat.config) : []
	);

	$effect(() => {
		const owner = name;
		if (!strat || !owner) return;
		if (owner !== kellyOwner) {
			kellyOwner = owner;
			kellyPct = Math.round(strat.kellyFraction * 100);
		}
	});
</script>

{#if !strat}
	<p class="text-[var(--color-muted)]">Strategy not found.</p>
{:else}
	<div class="mb-1.5 text-[11px] text-[var(--color-faint)]">
		<a href="/" class="text-[var(--color-muted)] hover:underline">Overview</a> / strategies / {strat.name}
	</div>
	<div class="mb-2 flex flex-wrap items-center gap-3">
		<h1 class="font-sans text-xl font-bold text-[var(--color-heading)]">{strat.name}</h1>
		<StateBadge state={strat.state} />
	</div>

	<!-- Verdict -->
	<p class="mb-5 max-w-3xl text-[12.5px] leading-relaxed text-[var(--color-muted)]">
		{#if activeSnapshot}
			Over the last {activeSnapshot.window === 'all' ? 'full run' : activeSnapshot.window}:
			<b class="font-medium text-[var(--color-bright)]"
				>{activeSnapshot.nTrades} trades, {activeSnapshot.nWins} won, {activeSnapshot.pnlCents >= 0
					? '+'
					: ''}{formatCents(activeSnapshot.pnlCents)}</b
			>.
			{#if activeSnapshot.brierScore != null}
				Calibration {isBrierTight(activeSnapshot.brierScore) ? 'is tight' : 'is loose'} (Brier {activeSnapshot.brierScore.toFixed(3)}){#if overconfidentHigh}
					with <span class="text-[var(--color-warn)]"
						>overconfidence in the high buckets (says {overconfidentHigh.predicted}%, reality
						{overconfidentHigh.observed}%)</span
					>{/if}.
			{/if}
			The posterior edge is {(activeSnapshot.posteriorEdgeMean * 100).toFixed(1)}% and the
			<b class="font-medium {edgeProven ? 'text-[var(--color-ok)]' : 'text-[var(--color-bright)]'}"
				>worst-case bound is {(activeSnapshot.posteriorEdgeCiLow * 100).toFixed(1)}%</b
			>
			— {edgeProven ? 'this edge is statistically real' : 'not yet statistically proven'}. Drawdown
			is {drawdownPct(strat).toFixed(1)}% of the {strat.config.maxDrawdownPctFromHwm.toFixed(0)}%
			stop.
		{:else}
			{strategyVerdict(strat, $evalRoster[strat.name])}
		{/if}
	</p>

	<!-- Vitals strip -->
	<section
		class="mb-5 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-[var(--color-border)] bg-[var(--color-border)] md:grid-cols-3 xl:grid-cols-5"
	>
		<div class="bg-[var(--color-panel)] px-4 py-3">
			<div class="mb-1 text-[9.5px] uppercase tracking-[0.13em] text-[var(--color-faint)]">Bankroll</div>
			<div class="font-sans text-lg font-bold tabular-nums text-[var(--color-heading)]">
				{formatCents(strat.bankrollCents)}
			</div>
			<div class="mt-0.5 text-[10.5px] tabular-nums text-[var(--color-muted)]">
				{formatCents(freeCash)} free · {formatCents(inPositions)} in positions
			</div>
		</div>
		<div class="bg-[var(--color-panel)] px-4 py-3">
			<div class="mb-1 text-[9.5px] uppercase tracking-[0.13em] text-[var(--color-faint)]">
				P&amp;L · {activeSnapshot?.window ?? '—'}
			</div>
			<div
				class="font-sans text-lg font-bold tabular-nums {(activeSnapshot?.pnlCents ?? 0) >= 0
					? 'text-[var(--color-ok)]'
					: 'text-[var(--color-danger)]'}"
			>
				{activeSnapshot ? `${activeSnapshot.pnlCents >= 0 ? '+' : ''}${formatCents(activeSnapshot.pnlCents)}` : '—'}
			</div>
			<div class="mt-0.5 text-[10.5px] tabular-nums text-[var(--color-muted)]">
				today {strat.todayPnlCents >= 0 ? '+' : ''}{formatCents(strat.todayPnlCents)}
			</div>
		</div>
		<div class="bg-[var(--color-panel)] px-4 py-3">
			<div class="mb-1 text-[9.5px] uppercase tracking-[0.13em] text-[var(--color-faint)]">
				Edge (worst case)
			</div>
			<div
				class="font-sans text-lg font-bold tabular-nums {edgeProven
					? 'text-[var(--color-ok)]'
					: 'text-[var(--color-heading)]'}"
			>
				{activeSnapshot ? `${(activeSnapshot.posteriorEdgeCiLow * 100).toFixed(1)}%` : '—'}
			</div>
			<div class="mt-0.5 text-[10.5px] tabular-nums text-[var(--color-muted)]">
				{activeSnapshot
					? `mean ${(activeSnapshot.posteriorEdgeMean * 100).toFixed(1)}%, best ${(activeSnapshot.posteriorEdgeCiHigh * 100).toFixed(1)}%`
					: 'needs resolved trades'}
			</div>
		</div>
		<div class="bg-[var(--color-panel)] px-4 py-3">
			<div class="mb-1 text-[9.5px] uppercase tracking-[0.13em] text-[var(--color-faint)]">Hit rate</div>
			<div class="font-sans text-lg font-bold tabular-nums text-[var(--color-heading)]">
				{activeSnapshot?.hitRate == null ? '—' : `${(activeSnapshot.hitRate * 100).toFixed(0)}%`}
			</div>
			<div class="mt-0.5 text-[10.5px] tabular-nums text-[var(--color-muted)]">
				{activeSnapshot
					? `${activeSnapshot.nWins} of ${activeSnapshot.nTrades} · Brier ${activeSnapshot.brierScore?.toFixed(3) ?? '—'}`
					: '—'}
			</div>
		</div>
		<div class="bg-[var(--color-panel)] px-4 py-3 md:col-span-2 xl:col-span-1">
			<div class="mb-1 text-[9.5px] uppercase tracking-[0.13em] text-[var(--color-faint)]">Drawdown</div>
			<div
				class="font-sans text-lg font-bold tabular-nums {drawdownPct(strat) >=
				strat.config.maxDrawdownPctFromHwm
					? 'text-[var(--color-danger)]'
					: 'text-[var(--color-heading)]'}"
			>
				{drawdownPct(strat).toFixed(1)}%
			</div>
			<div class="mt-0.5 text-[10.5px] tabular-nums text-[var(--color-muted)]">
				stops at {strat.config.maxDrawdownPctFromHwm.toFixed(0)}% · HWM {formatCents(strat.bankrollHwmCents)}
			</div>
		</div>
	</section>

	<!-- Controls -->
	<div class="mb-5 flex flex-wrap items-center gap-2">
		<button
			type="button"
			class="rounded border border-[color-mix(in_srgb,var(--color-accent)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-accent)_12%,transparent)] px-4 py-1.5 text-xs text-[var(--color-accent)] disabled:opacity-40"
			disabled={$systemPaused || strat.state === 'decommissioned'}
			title={$systemPaused ? 'Kill switch active' : ''}
			onclick={() => (depositModal = true)}
		>
			Deposit
		</button>
		<button
			type="button"
			class="rounded border border-[var(--color-border-bright)] bg-[var(--color-panel-2)] px-4 py-1.5 text-xs disabled:opacity-40"
			disabled={$systemPaused}
			onclick={() => (withdrawModal = true)}
		>
			Withdraw
		</button>
		{#if PAUSABLE_STATES.includes(strat.state as (typeof PAUSABLE_STATES)[number])}
			<button
				type="button"
				class="rounded border border-[color-mix(in_srgb,var(--color-warn)_45%,transparent)] px-4 py-1.5 text-xs text-[var(--color-warn)] disabled:opacity-40"
				disabled={$systemPaused}
				onclick={() => void pauseStrategy(strat.name, reason || 'operator pause')}
			>
				Pause
			</button>
		{/if}
		{#if RESUMABLE_STATES.includes(strat.state as (typeof RESUMABLE_STATES)[number])}
			<button
				type="button"
				class="rounded border border-[color-mix(in_srgb,var(--color-ok)_45%,transparent)] px-4 py-1.5 text-xs text-[var(--color-ok)] disabled:opacity-40"
				disabled={$systemPaused}
				onclick={() => void resumeStrategy(strat.name, reason || 'operator resume')}
			>
				Resume
			</button>
		{/if}
		<button
			type="button"
			class="rounded border border-[color-mix(in_srgb,var(--color-warn)_45%,transparent)] px-4 py-1.5 text-xs text-[var(--color-warn)] disabled:opacity-40"
			disabled={$systemPaused || strat.state === 'decommissioned'}
			onclick={() => (forceModal = true)}
		>
			Force close positions
		</button>
		<button
			type="button"
			class="ml-auto rounded border border-[color-mix(in_srgb,var(--color-danger)_45%,transparent)] px-4 py-1.5 text-xs text-[var(--color-danger)]"
			onclick={() => (decomModal = true)}
		>
			Decommission…
		</button>
	</div>

	<div class="mb-5 grid gap-3.5 lg:grid-cols-2">
		<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
			<h2
				class="mb-2 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
			>
				Bankroll — 14 days
			</h2>
			<BankrollChart points={history} width={480} height={140} />
		</div>
		<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
			<div class="mb-2 flex items-center justify-between">
				<h2 class="text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)]">Calibration</h2>
				<div class="flex gap-1.5">
					{#each windowOptions as w (w)}
						<button
							type="button"
							class="rounded border px-2.5 py-0.5 text-[10.5px] {selectedWindow === w
								? 'border-[var(--color-accent)] text-[var(--color-accent)]'
								: 'border-[var(--color-border)] text-[var(--color-muted)] hover:text-[var(--color-bright)]'}"
							onclick={() => (selectedWindow = w)}
						>
							{w}
						</button>
					{/each}
				</div>
			</div>
			<CalibrationChart buckets={calibration} legendId="strategy-calibration-legend" />
			{#if overconfidentHigh}
				<p
					class="mt-2.5 border-t border-[var(--color-border)] pt-2.5 text-[11.5px] leading-relaxed text-[var(--color-muted)]"
				>
					<b class="font-medium text-[var(--color-bright)]">Reading:</b> the high buckets run
					<span class="text-[var(--color-warn)]">a touch too sure</span> — when this strategy says
					"{overconfidentHigh.predicted}% likely," reality has delivered about {overconfidentHigh.observed}%.
				</p>
			{/if}
			{#if !activeSnapshot}
				<p class="mt-3 text-xs text-[var(--color-faint)]">No eval data yet — needs resolved trades.</p>
			{/if}
			<details id="strategy-calibration-legend-desc" class="group mt-2 text-xs text-[var(--color-faint)]">
				<summary
					class="cursor-pointer list-none font-medium text-[var(--color-muted)] marker:content-none hover:text-[var(--color-bright)] [&::-webkit-details-marker]:hidden"
				>
					<span class="inline-flex items-center gap-1">
						<span
							class="inline-block text-[10px] transition group-open:rotate-90"
							aria-hidden="true">▶</span
						>
						How to read
					</span>
				</summary>
				<div class="mt-1.5 space-y-1.5 pl-3">
					<p>
						Each dot groups past signals by predicted probability (10 bins). Horizontal position
						is what the strategy predicted; vertical position is how often the contract actually
						resolved yes.
					</p>
					<ul class="list-inside list-disc space-y-0.5 pl-0.5">
						<li>
							<span class="text-[var(--color-muted)]">On the dashed line</span> — well calibrated (predicted
							matches outcomes).
						</li>
						<li>
							<span class="text-[var(--color-muted)]">Above the line</span> — more yes than predicted
							(under-confident).
						</li>
						<li>
							<span class="text-[var(--color-muted)]">Below the line</span> — fewer yes than predicted
							(over-confident).
						</li>
					</ul>
					{#if $isDeveloperMode && $apiMode === 'mock'}
						<p class="text-[10px] text-[var(--color-faint)]">
							Prototype: buckets are simulated fixture data, not computed from live Kalshi
							resolutions.
						</p>
					{/if}
				</div>
			</details>
		</div>
	</div>

	<div class="mb-5 grid gap-3.5 lg:grid-cols-[1.5fr_1fr]">
		<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
			<div class="mb-1 flex items-center justify-between">
				<h2 class="text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)]">Signals</h2>
				<select
					class="rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-0.5 text-[11px]"
					bind:value={outcomeFilter}
				>
					<option value="all">All outcomes</option>
					<option value="order_placed">{outcomeLabel('order_placed')}</option>
					<option value="rejected_below_threshold">{outcomeLabel('rejected_below_threshold')}</option>
					<option value="rejected_kelly_zero">{outcomeLabel('rejected_kelly_zero')}</option>
					<option value="rejected_stale_inputs">{outcomeLabel('rejected_stale_inputs')}</option>
					<option value="rejected_system_paused">{outcomeLabel('rejected_system_paused')}</option>
				</select>
			</div>
			<div class="max-h-96 overflow-y-auto">
				{#each signalsByDay as group (group.day)}
					<div
						class="pb-1.5 pt-3 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]"
					>
						{group.day}
					</div>
					{#each group.items as sig (sig.id)}
						<div
							class="grid grid-cols-[40px_1fr_56px_auto] items-baseline gap-3 border-b border-[var(--color-border)] py-1.5 text-xs last:border-0"
						>
							<span class="text-[11px] tabular-nums text-[var(--color-faint)]"
								>{compactIsoTime(sig.evaluatedAt)}</span
							>
							<span class="min-w-0">
								<span class="text-[var(--color-bright)]">{humanizeTicker(sig.ticker)}</span>
								{#if humanizeTicker(sig.ticker) !== sig.ticker}
									<span class="block truncate text-[10px] text-[var(--color-faint)]">{sig.ticker}</span>
								{/if}
							</span>
							<span class="text-right tabular-nums text-[var(--color-muted)]"
								>saw <b class="font-medium text-[var(--color-bright)]">{(sig.probYes * 100).toFixed(0)}%</b></span
							>
							<span class="text-[11px] {toneClass[outcomeTone(sig.outcome)]}"
								>{outcomeLabel(sig.outcome)}</span
							>
						</div>
					{/each}
				{:else}
					<p class="py-2 text-xs text-[var(--color-faint)]">No signals match this filter.</p>
				{/each}
			</div>
		</div>

		<div class="flex flex-col gap-3.5">
			<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
				<h2
					class="mb-1 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
				>
					Money ledger
				</h2>
				{#each cashByDay as group (group.day)}
					<div
						class="pb-1.5 pt-3 text-[10px] uppercase tracking-[0.14em] text-[var(--color-faint)]"
					>
						{group.day}
					</div>
					{#each group.items as c (c.id)}
						{@const kind = cashKind(c)}
						<div
							class="grid grid-cols-[40px_72px_1fr_auto_auto] items-baseline gap-3 border-b border-[var(--color-border)] py-1.5 text-xs last:border-0"
							title={c.occurredAt ? new Date(c.occurredAt).toLocaleString() : undefined}
						>
							<span class="text-[11px] tabular-nums text-[var(--color-faint)]"
								>{compactIsoTime(c.occurredAt)}</span
							>
							<span class="text-[10px] uppercase tracking-[0.08em] {kind.cls}">{kind.label}</span>
							<span class="min-w-0 truncate text-[var(--color-muted)]" title={c.reason}>{c.reason}</span>
							<span
								class="tabular-nums {c.amountCents >= 0
									? 'text-[var(--color-ok)]'
									: 'text-[var(--color-danger)]'}"
								>{c.amountCents >= 0 ? '+' : ''}{formatCents(c.amountCents)}</span
							>
							<span class="w-16 text-right tabular-nums text-[var(--color-faint)]"
								>{formatCents(c.balanceAfterCents)}</span
							>
						</div>
					{/each}
				{:else}
					<p class="py-2 text-xs text-[var(--color-faint)]">No cash events.</p>
				{/each}
			</div>

			<div class="rounded-md border border-[var(--color-border)] bg-[var(--color-panel)] p-4">
				<h2
					class="mb-1 flex items-center gap-2.5 text-[11px] uppercase tracking-[0.18em] text-[var(--color-faint)] after:h-px after:flex-1 after:bg-[var(--color-border)]"
				>
					Rules this strategy runs under
				</h2>
				{#each [...baselineConfigRows, ...soakConfigRows] as row (row[0])}
					<div
						class="flex items-baseline justify-between gap-3 border-b border-[var(--color-border)] py-1.5 text-xs last:border-0"
					>
						<span class="text-[var(--color-muted)]">{row[0]}</span>
						<span class="tabular-nums text-[var(--color-bright)]">{row[1]}</span>
					</div>
				{/each}
				<div class="mt-3 border-t border-[var(--color-border)] pt-3">
					<label class="text-xs text-[var(--color-muted)]">
						Bet sizing — Kelly {kellyPct}%
						<input
							type="range"
							min="0"
							max="100"
							bind:value={kellyPct}
							class="w-full accent-[var(--color-accent)]"
							disabled={$systemPaused || strat.state === 'decommissioned'}
						/>
					</label>
					<button
						type="button"
						class="mt-1 w-full rounded border border-[var(--color-border-bright)] py-1 text-xs disabled:opacity-40"
						disabled={$systemPaused || strat.state === 'decommissioned'}
						onclick={() => void setKellyFraction(strat.name, kellyPct / 100, 'strategy page slider')}
					>
						Apply Kelly {kellyPct}%
					</button>
					<input
						class="mt-2 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-xs"
						placeholder="Reason for pause/resume"
						bind:value={reason}
					/>
				</div>
			</div>
		</div>
	</div>
{/if}

<Modal
	open={depositModal}
	title="Deposit"
	onclose={() => {
		depositModal = false;
		amountError = '';
	}}
>
	<input
		class="mb-2 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		type="number"
		bind:value={amountDollars}
		min="1"
	/>
	{#if amountError}
		<p class="mb-2 text-xs text-[var(--color-danger)]">{amountError}</p>
	{/if}
	<input
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		placeholder="Reason"
		bind:value={reason}
	/>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-accent)] py-2 text-sm font-medium text-[var(--color-surface)]"
		onclick={() => {
			const cents = parseAmountCents();
			if (cents === null) return;
			void deposit(name, cents, reason || 'deposit');
			depositModal = false;
			amountError = '';
		}}
	>
		Confirm deposit
	</button>
</Modal>

<Modal
	open={withdrawModal}
	title="Withdraw"
	onclose={() => {
		withdrawModal = false;
		amountError = '';
	}}
>
	<p class="mb-2 text-xs text-[var(--color-muted)]">Free cash: {formatCents(freeCash)}</p>
	<input
		class="mb-2 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		type="number"
		bind:value={amountDollars}
	/>
	{#if amountError}
		<p class="mb-2 text-xs text-[var(--color-danger)]">{amountError}</p>
	{/if}
	<input
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		placeholder="Reason"
		bind:value={reason}
	/>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-panel-2)] py-2 text-sm text-[var(--color-bright)]"
		onclick={() => {
			const cents = parseAmountCents();
			if (cents === null) return;
			void withdraw(name, cents, reason || 'withdraw');
			withdrawModal = false;
			amountError = '';
		}}
	>
		Confirm withdraw
	</button>
</Modal>

<Modal open={forceModal} title="Force close & realize P&L" onclose={() => (forceModal = false)}>
	<p class="mb-3 text-sm text-[var(--color-muted)]">
		Closes all open positions at simulated mid; then you may withdraw.
	</p>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-warn)] py-2 text-sm font-medium text-[var(--color-surface)]"
		onclick={() => {
			void forceCloseAndWithdraw(name, reason || 'force close');
			forceModal = false;
		}}
	>
		Close all open positions
	</button>
</Modal>

<Modal open={decomModal} title="Decommission strategy" onclose={() => (decomModal = false)}>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-danger)] py-2 text-sm font-medium text-[var(--color-surface)]"
		onclick={() => {
			void decommission(name, reason || 'decommission');
			decomModal = false;
		}}
	>
		Confirm decommission
	</button>
</Modal>
