<script lang="ts">
	import { strategies, signals, sources, systemPaused } from '$lib/stores';
	import StateBadge from '$lib/components/StateBadge.svelte';
	import {
		drawdownPct,
		formatCents,
		outcomeColor,
		PAUSABLE_STATES,
		RESUMABLE_STATES,
		formatAge
	} from '$lib/utils';
	import { isDeveloperMode } from '$lib/stores/uiMode';
	import { pauseStrategy, resumeStrategy, probeSource } from '$lib/actions';

	const recentSignals = $derived($signals.slice(0, 12));
</script>

<h1 class="mb-4 text-lg font-semibold text-slate-100">Dashboard</h1>

<section class="mb-6">
	<h2 class="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Strategy roster</h2>
	<div class="overflow-x-auto rounded border border-[var(--color-border)]">
		<table class="w-full text-left text-sm">
			<thead class="bg-slate-800/80 text-xs text-slate-400">
				<tr>
					<th class="px-3 py-2">Name</th>
					<th class="px-3 py-2">State</th>
					<th class="px-3 py-2">Bankroll</th>
					<th class="px-3 py-2">Drawdown</th>
					<th class="px-3 py-2">Today P&L</th>
					<th class="px-3 py-2"></th>
				</tr>
			</thead>
			<tbody>
				{#each $strategies as s (s.name)}
					<tr class="border-t border-[var(--color-border)] hover:bg-slate-800/40">
						<td class="px-3 py-2">
							<a href="/strategies/{s.name}" class="font-medium text-blue-400 hover:underline">{s.name}</a>
						</td>
						<td class="px-3 py-2"><StateBadge state={s.state} /></td>
						<td class="px-3 py-2 tabular-nums">{formatCents(s.bankrollCents)}</td>
						<td class="px-3 py-2 tabular-nums">{drawdownPct(s).toFixed(1)}%</td>
						<td
							class="px-3 py-2 tabular-nums {s.todayPnlCents >= 0
								? 'text-emerald-400'
								: 'text-red-400'}"
						>
							{formatCents(s.todayPnlCents)}
						</td>
						<td class="px-3 py-2">
							{#if PAUSABLE_STATES.includes(s.state as typeof PAUSABLE_STATES[number])}
								<button
									type="button"
									class="text-xs text-amber-400 hover:underline disabled:opacity-40"
									disabled={$systemPaused}
									title={$systemPaused ? 'Kill switch active' : 'Pause strategy'}
									onclick={() => void pauseStrategy(s.name, 'operator pause from roster')}
								>
									Pause
								</button>
							{:else if RESUMABLE_STATES.includes(s.state as typeof RESUMABLE_STATES[number])}
								<button
									type="button"
									class="text-xs text-emerald-400 hover:underline disabled:opacity-40"
									disabled={$systemPaused}
									onclick={() => void resumeStrategy(s.name, 'operator resume from roster')}
								>
									Resume
								</button>
							{/if}
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
</section>

<section class="mb-6 grid gap-4 md:grid-cols-2">
	<div>
		<h2 class="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Source health</h2>
		<ul class="space-y-2 rounded border border-[var(--color-border)] p-3 text-sm">
			{#each $sources as src (src.name)}
				<li class="flex items-center justify-between gap-2">
					<div>
						<span class="font-medium text-slate-200">{src.displayName}</span>
						<span
							class="ml-2 text-xs capitalize {src.state === 'healthy'
								? 'text-emerald-400'
								: src.state === 'degraded'
									? 'text-amber-400'
									: 'text-red-400'}"
						>
							{src.state}
						</span>
						<span class="ml-2 text-xs text-slate-500">{formatAge(src.lastSuccessfulFetch)}</span>
					</div>
					{#if $isDeveloperMode}
						<button
							type="button"
							class="shrink-0 rounded border border-[var(--color-border)] px-2 py-0.5 text-xs hover:bg-slate-800"
							onclick={() => probeSource(src.name)}
						>
							Probe
						</button>
					{/if}
				</li>
			{/each}
		</ul>
	</div>

	<div>
		<h2 class="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Recent signals</h2>
		<ul class="max-h-64 space-y-1 overflow-y-auto rounded border border-[var(--color-border)] p-2 text-xs">
			{#each recentSignals as sig (sig.id)}
				<li class="flex justify-between gap-2 border-b border-slate-800/80 py-1 last:border-0">
					<span class="text-slate-300">{sig.strategyName} · {sig.ticker}</span>
					<span class={outcomeColor(sig.outcome)}>{sig.outcome.replace(/_/g, ' ')}</span>
				</li>
			{/each}
		</ul>
	</div>
</section>
