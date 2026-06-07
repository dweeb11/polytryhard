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
		drawdownPct,
		formatCents,
		freeCashCents,
		outcomeColor,
		PAUSABLE_STATES,
		RESUMABLE_STATES
	} from '$lib/utils';
	import {
		strategyBaselineConfigRows,
		strategySoakConfigRows
	} from '$lib/strategyConfigDisplay';
	import { evalByStrategy } from '$lib/stores';
	import { hydrateStrategyEval, mapCalibrationBins } from '$lib/api/hydrate';
	import { apiMode } from '$lib/api/mode';

	const name = $derived($page.params.name ?? '');
	const strat = $derived($strategies.find((s) => s.name === name));
	const stratSignals = $derived($signals.filter((s) => s.strategyName === name));
	const history = $derived($bankrollHistoryByStrategy[name] ?? []);
	const stratCash = $derived($cashEvents.filter((c) => c.strategyName === name).slice(0, 10));

	let selectedWindow: string = $state('30d');

	$effect(() => {
		if (name && $apiMode === 'live') hydrateStrategyEval(name).catch(() => {});
	});

	const evalWindows = $derived($evalByStrategy[name]?.windows ?? []);
	const activeSnapshot = $derived(
		evalWindows.find((w) => w.window === selectedWindow) ?? evalWindows[0]
	);

	const calibration = $derived(
		activeSnapshot
			? mapCalibrationBins(activeSnapshot.calibrationBins)
			: ($calibrationByStrategy[name] ?? [])
	);
	const freeCash = $derived(strat ? freeCashCents(strat, $positions) : 0);

	let depositModal = $state(false);
	let withdrawModal = $state(false);
	let forceModal = $state(false);
	let decomModal = $state(false);
	let amountDollars = $state('100');
	let amountError = $state('');
	let reason = $state('');
	let kellyPct = $state(25);
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

	const baselineConfigRows = $derived(strat ? strategyBaselineConfigRows(strat.config) : []);
	const soakConfigRows = $derived(
		strat ? strategySoakConfigRows(strat.name, strat.config) : []
	);

	$effect(() => {
		if (strat) kellyPct = Math.round(strat.kellyFraction * 100);
	});
</script>

{#if !strat}
	<p class="text-slate-400">Strategy not found.</p>
{:else}
	<div class="mb-4 flex flex-wrap items-center gap-3">
		<h1 class="text-lg font-semibold text-slate-100">{strat.name}</h1>
		<StateBadge state={strat.state} />
		<span class="text-sm text-slate-400"
			>Bankroll {formatCents(strat.bankrollCents)} · Free {formatCents(freeCash)} · DD {drawdownPct(
				strat
			).toFixed(1)}%</span
		>
	</div>

	<div class="mb-6 grid gap-4 lg:grid-cols-2">
		<div class="rounded border border-[var(--color-border)] p-3">
			<h2 class="mb-2 text-xs uppercase text-slate-500">Bankroll (14d)</h2>
			<BankrollChart points={history} width={480} height={140} />
		</div>
		<div class="rounded border border-[var(--color-border)] p-3">
			<h2 class="mb-2 text-xs uppercase text-slate-500">Calibration (10 buckets)</h2>
			<div class="mb-2 flex items-center gap-2 text-xs">
				<span class="uppercase text-slate-500">Window</span>
				<select class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-0.5" bind:value={selectedWindow}>
					<option value="7d">7d</option>
					<option value="30d">30d</option>
					<option value="all">all</option>
				</select>
			</div>
			<CalibrationChart buckets={calibration} legendId="strategy-calibration-legend" />
			{#if activeSnapshot}
				<table class="mt-3 w-full text-xs">
					<tbody class="[&_td]:py-0.5">
						<tr><td class="text-slate-500">Trades</td><td class="tabular-nums">{activeSnapshot.nTrades} ({activeSnapshot.nWins} won)</td></tr>
						<tr><td class="text-slate-500">Hit rate</td><td class="tabular-nums">{activeSnapshot.hitRate == null ? '—' : (activeSnapshot.hitRate * 100).toFixed(1) + '%'}</td></tr>
						<tr><td class="text-slate-500">Brier</td><td class="tabular-nums">{activeSnapshot.brierScore == null ? '—' : activeSnapshot.brierScore.toFixed(3)}</td></tr>
						<tr><td class="text-slate-500">Log loss</td><td class="tabular-nums">{activeSnapshot.logLoss == null ? '—' : activeSnapshot.logLoss.toFixed(3)}</td></tr>
						<tr><td class="text-slate-500">P&amp;L</td><td class="tabular-nums">{formatCents(activeSnapshot.pnlCents)}</td></tr>
						<tr><td class="text-slate-500">Max drawdown</td><td class="tabular-nums">{formatCents(activeSnapshot.maxDrawdownCents)}</td></tr>
						<tr><td class="text-slate-500">Sharpe proxy</td><td class="tabular-nums">{activeSnapshot.sharpeProxy == null ? '—' : activeSnapshot.sharpeProxy.toFixed(2)}</td></tr>
						<tr><td class="text-slate-500">Posterior edge</td><td class="tabular-nums">{(activeSnapshot.posteriorEdgeMean * 100).toFixed(1)}% [{(activeSnapshot.posteriorEdgeCiLow * 100).toFixed(1)}, {(activeSnapshot.posteriorEdgeCiHigh * 100).toFixed(1)}]</td></tr>
					</tbody>
				</table>
			{:else}
				<p class="mt-3 text-xs text-slate-500">No eval data yet — needs resolved trades.</p>
			{/if}
			<details id="strategy-calibration-legend-desc" class="group mt-2 text-xs text-slate-500">
				<summary
					class="cursor-pointer list-none font-medium text-slate-400 marker:content-none hover:text-slate-300 [&::-webkit-details-marker]:hidden"
				>
					<span class="inline-flex items-center gap-1">
						<span
							class="inline-block text-[10px] text-slate-500 transition group-open:rotate-90"
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
							<span class="text-slate-400">On the dashed line</span> — well calibrated (predicted
							matches outcomes).
						</li>
						<li>
							<span class="text-slate-400">Above the line</span> — more yes than predicted
							(under-confident).
						</li>
						<li>
							<span class="text-slate-400">Below the line</span> — fewer yes than predicted
							(over-confident).
						</li>
					</ul>
					{#if $isDeveloperMode && $apiMode === 'mock'}
						<p class="text-[10px] text-slate-600">
							Prototype: buckets are simulated fixture data, not computed from live Kalshi
							resolutions.
						</p>
					{/if}
				</div>
			</details>
		</div>
	</div>

	<div class="mb-6 grid gap-4 lg:grid-cols-3">
		<div class="rounded border border-[var(--color-border)] p-3 lg:col-span-1">
			<h2 class="mb-3 text-xs uppercase text-slate-500">Controls</h2>
			<div class="flex flex-col gap-2">
				<button
					type="button"
					class="rounded bg-blue-700 px-3 py-1.5 text-sm disabled:opacity-40"
					disabled={$systemPaused || strat.state === 'decommissioned'}
					title={$systemPaused ? 'Kill switch active' : ''}
					onclick={() => (depositModal = true)}
				>
					Deposit
				</button>
				<button
					type="button"
					class="rounded border border-[var(--color-border)] px-3 py-1.5 text-sm disabled:opacity-40"
					disabled={$systemPaused}
					onclick={() => (withdrawModal = true)}
				>
					Withdraw
				</button>
				{#if PAUSABLE_STATES.includes(strat.state as typeof PAUSABLE_STATES[number])}
					<button
						type="button"
						class="rounded border border-amber-700 px-3 py-1.5 text-sm text-amber-300 disabled:opacity-40"
						disabled={$systemPaused}
						onclick={() => void pauseStrategy(strat.name, reason || 'operator pause')}
					>
						Pause
					</button>
				{/if}
				{#if RESUMABLE_STATES.includes(strat.state as typeof RESUMABLE_STATES[number])}
					<button
						type="button"
						class="rounded border border-emerald-700 px-3 py-1.5 text-sm text-emerald-300 disabled:opacity-40"
						disabled={$systemPaused}
						onclick={() => void resumeStrategy(strat.name, reason || 'operator resume')}
					>
						Resume
					</button>
				{/if}
				<label class="mt-2 text-xs text-slate-400">
					Kelly % (0–100)
					<input
						type="range"
						min="0"
						max="100"
						bind:value={kellyPct}
						class="w-full"
						disabled={$systemPaused || strat.state === 'decommissioned'}
					/>
					<button
						type="button"
						class="mt-1 w-full rounded border border-[var(--color-border)] py-1 text-xs disabled:opacity-40"
						disabled={$systemPaused || strat.state === 'decommissioned'}
						onclick={() => void setKellyFraction(strat.name, kellyPct / 100, 'dashboard slider')}
					>
						Apply Kelly {kellyPct}%
					</button>
				</label>
				<button
					type="button"
					class="rounded border border-orange-700 px-3 py-1.5 text-sm text-orange-300 disabled:opacity-40"
					disabled={$systemPaused || strat.state === 'decommissioned'}
					onclick={() => (forceModal = true)}
				>
					Force close positions
				</button>
				<button
					type="button"
					class="rounded border border-red-800 px-3 py-1.5 text-sm text-red-400"
					onclick={() => (decomModal = true)}
				>
					Decommission
				</button>
				<input
					class="mt-2 rounded border border-[var(--color-border)] bg-slate-900 px-2 py-1 text-xs"
					placeholder="Reason for pause/resume"
					bind:value={reason}
				/>
				<div class="mt-3 border-t border-[var(--color-border)] pt-3">
					<h3 class="mb-2 text-xs uppercase text-slate-500">Baseline config</h3>
					<dl class="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-xs">
						{#each baselineConfigRows as row}
							<dt class="truncate text-slate-500">{row[0]}</dt>
							<dd class="text-right tabular-nums text-slate-300">{row[1]}</dd>
						{/each}
					</dl>
					<h3 class="mb-2 mt-3 text-xs uppercase text-slate-500">Soak knobs</h3>
					<dl class="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 text-xs">
						{#each soakConfigRows as row}
							<dt class="truncate text-slate-500">{row[0]}</dt>
							<dd class="text-right tabular-nums text-slate-300">{row[1]}</dd>
						{/each}
					</dl>
				</div>
			</div>
		</div>

		<div class="rounded border border-[var(--color-border)] p-3 lg:col-span-2">
			<div class="mb-2 flex items-center justify-between">
				<h2 class="text-xs uppercase text-slate-500">Signals</h2>
				<select
					class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-0.5 text-xs"
					bind:value={outcomeFilter}
				>
					<option value="all">All outcomes</option>
					<option value="order_placed">order placed</option>
					<option value="rejected_system_paused">system paused</option>
					<option value="rejected_below_threshold">below threshold</option>
				</select>
			</div>
			<div class="max-h-80 overflow-y-auto text-xs">
				<table class="w-full">
					<thead class="text-slate-500">
						<tr>
							<th class="py-1 text-left">Time</th>
							<th class="py-1 text-left">Ticker</th>
							<th class="py-1 text-left">p(Y)</th>
							<th class="py-1 text-left">Outcome</th>
						</tr>
					</thead>
					<tbody>
						{#each filteredSignals.slice(0, 40) as sig (sig.id)}
							<tr class="border-t border-slate-800">
								<td class="py-1 text-slate-400">{new Date(sig.evaluatedAt).toLocaleString()}</td>
								<td>{sig.ticker}</td>
								<td>{sig.probYes.toFixed(2)}</td>
								<td class={outcomeColor(sig.outcome)}>{sig.outcome}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<div class="rounded border border-[var(--color-border)] p-3">
		<h2 class="mb-2 text-xs uppercase text-slate-500">Recent cash events</h2>
		<ul class="text-xs text-slate-300">
			{#each stratCash as c (c.id)}
				<li class="py-0.5">
					{c.kind} {formatCents(c.amountCents)} → balance {formatCents(c.balanceAfterCents)} — {c.reason}
				</li>
			{:else}
				<li class="text-slate-500">No cash events</li>
			{/each}
		</ul>
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
		class="mb-2 w-full rounded border border-[var(--color-border)] bg-slate-900 p-2 text-sm"
		type="number"
		bind:value={amountDollars}
		min="1"
	/>
	{#if amountError}
		<p class="mb-2 text-xs text-red-400">{amountError}</p>
	{/if}
	<input
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-slate-900 p-2 text-sm"
		placeholder="Reason"
		bind:value={reason}
	/>
	<button
		type="button"
		class="w-full rounded bg-blue-700 py-2 text-sm text-white"
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
	<p class="mb-2 text-xs text-slate-400">Free cash: {formatCents(freeCash)}</p>
	<input class="mb-2 w-full rounded border bg-slate-900 p-2 text-sm" type="number" bind:value={amountDollars} />
	{#if amountError}
		<p class="mb-2 text-xs text-red-400">{amountError}</p>
	{/if}
	<input class="mb-3 w-full rounded border bg-slate-900 p-2 text-sm" placeholder="Reason" bind:value={reason} />
	<button
		type="button"
		class="w-full rounded bg-slate-600 py-2 text-sm text-white"
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
	<p class="mb-3 text-sm text-slate-400">Closes all open positions at simulated mid; then you may withdraw.</p>
	<button
		type="button"
		class="w-full rounded bg-orange-700 py-2 text-sm text-white"
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
		class="w-full rounded bg-red-800 py-2 text-sm text-white"
		onclick={() => {
			void decommission(name, reason || 'decommission');
			decomModal = false;
		}}
	>
		Confirm decommission
	</button>
</Modal>
