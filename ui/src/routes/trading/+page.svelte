<script lang="ts">
	import { signals, positions, strategies } from '$lib/stores';
	import { formatCents, outcomeColor } from '$lib/utils';

	let strategyFilter = $state('all');
	let outcomeFilter = $state('all');
	let statusFilter = $state('all');

	const strategyNames = $derived(['all', ...$strategies.map((s) => s.name)]);

	const filteredSignals = $derived(
		$signals.filter((sig) => {
			if (strategyFilter !== 'all' && sig.strategyName !== strategyFilter) return false;
			if (outcomeFilter !== 'all' && sig.outcome !== outcomeFilter) return false;
			return true;
		})
	);

	const filteredPositions = $derived(
		$positions.filter((pos) => {
			if (strategyFilter !== 'all' && pos.strategyName !== strategyFilter) return false;
			if (statusFilter !== 'all' && pos.status !== statusFilter) return false;
			return true;
		})
	);

	const signalOutcomes = $derived([
		'all',
		...Array.from(new Set($signals.map((s) => s.outcome))).sort()
	]);

	function formatUnrealized(cents: number | null): string {
		return cents == null ? '—' : formatCents(cents);
	}

	function unrealizedClass(cents: number | null): string {
		if (cents == null) return 'text-slate-500';
		if (cents > 0) return 'text-emerald-400';
		if (cents < 0) return 'text-red-400';
		return 'text-slate-300';
	}
</script>

<h1 class="mb-4 text-lg font-semibold text-slate-100">Trading</h1>
<p class="mb-6 text-sm text-slate-400">
	Read-only view of engine signals and paper positions. Data hydrates from the backend when live.
</p>

<div class="mb-4 flex flex-wrap items-end gap-3 text-sm">
	<label class="flex flex-col gap-1 text-xs text-slate-400">
		Strategy
		<select
			class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-1 text-sm text-slate-200"
			bind:value={strategyFilter}
		>
			{#each strategyNames as name (name)}
				<option value={name}>{name === 'all' ? 'All strategies' : name}</option>
			{/each}
		</select>
	</label>
</div>

<div class="grid gap-6 xl:grid-cols-2">
	<section class="rounded border border-[var(--color-border)] p-3">
		<div class="mb-3 flex items-center justify-between gap-2">
			<h2 class="text-xs font-medium uppercase tracking-wide text-slate-500">Signals</h2>
			<select
				class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-0.5 text-xs"
				bind:value={outcomeFilter}
			>
				{#each signalOutcomes as outcome (outcome)}
					<option value={outcome}>
						{outcome === 'all' ? 'All outcomes' : outcome.replace(/_/g, ' ')}
					</option>
				{/each}
			</select>
		</div>
		<div class="max-h-[28rem] overflow-y-auto text-xs">
			<table class="w-full">
				<thead class="sticky top-0 bg-[var(--color-panel)] text-slate-500">
					<tr>
						<th class="py-1 text-left">Time</th>
						<th class="py-1 text-left">Strategy</th>
						<th class="py-1 text-left">Ticker</th>
						<th class="py-1 text-right">p(Y)</th>
						<th class="py-1 text-left">Outcome</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredSignals as sig (sig.id)}
						<tr class="border-t border-slate-800">
							<td class="py-1 text-slate-400">{new Date(sig.evaluatedAt).toLocaleString()}</td>
							<td class="py-1">{sig.strategyName}</td>
							<td class="py-1 font-mono">{sig.ticker}</td>
							<td class="py-1 text-right tabular-nums">{sig.probYes.toFixed(2)}</td>
							<td class="py-1">
								<span class={outcomeColor(sig.outcome)} title={sig.rejectionReason ?? undefined}>
									{sig.outcome.replace(/_/g, ' ')}
								</span>
							</td>
						</tr>
					{:else}
						<tr>
							<td colspan="5" class="py-4 text-center text-slate-500">No signals</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>

	<section class="rounded border border-[var(--color-border)] p-3">
		<div class="mb-3 flex items-center justify-between gap-2">
			<h2 class="text-xs font-medium uppercase tracking-wide text-slate-500">Positions</h2>
			<select
				class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-0.5 text-xs"
				bind:value={statusFilter}
			>
				<option value="all">All statuses</option>
				<option value="open">open</option>
				<option value="closed">closed</option>
				<option value="resolved">resolved</option>
			</select>
		</div>
		<div class="max-h-[28rem] overflow-y-auto text-xs">
			<table class="w-full">
				<thead class="sticky top-0 bg-[var(--color-panel)] text-slate-500">
					<tr>
						<th class="py-1 text-left">Strategy</th>
						<th class="py-1 text-left">Ticker</th>
						<th class="py-1 text-left">Side</th>
						<th class="py-1 text-right">Qty</th>
						<th class="py-1 text-right">Cost</th>
						<th class="py-1 text-right">Unrealized</th>
						<th class="py-1 text-left">Status</th>
					</tr>
				</thead>
				<tbody>
					{#each filteredPositions as pos (pos.id)}
						<tr class="border-t border-slate-800">
							<td class="py-1">{pos.strategyName}</td>
							<td class="py-1 font-mono">{pos.ticker}</td>
							<td class="py-1 uppercase">{pos.side}</td>
							<td class="py-1 text-right tabular-nums">{pos.qty}</td>
							<td class="py-1 text-right tabular-nums">{formatCents(pos.costBasisCents)}</td>
							<td class="py-1 text-right tabular-nums {unrealizedClass(pos.unrealizedPnlCents)}">
								{formatUnrealized(pos.unrealizedPnlCents)}
							</td>
							<td class="py-1 capitalize">{pos.status}</td>
						</tr>
					{:else}
						<tr>
							<td colspan="7" class="py-4 text-center text-slate-500">No positions</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</section>
</div>
