<script lang="ts">
	import { sources } from '$lib/stores';
	import { isDeveloperMode } from '$lib/stores/uiMode';
	import { probeSource, resetCircuitBreaker } from '$lib/actions';
	import { formatAge } from '$lib/utils';
</script>

<h2 class="mb-4 text-sm font-medium text-slate-300">Sources</h2>

<div class="grid gap-4 md:grid-cols-2">
	{#each $sources as src}
		<article class="rounded border border-[var(--color-border)] p-4 text-sm">
			<div class="mb-2 flex items-start justify-between">
				<h3 class="font-medium text-slate-100">{src.displayName}</h3>
				<span
					class="rounded px-2 py-0.5 text-xs capitalize {src.state === 'healthy'
						? 'bg-emerald-900/40 text-emerald-300'
						: src.state === 'degraded'
							? 'bg-amber-900/40 text-amber-300'
							: 'bg-red-900/40 text-red-300'}"
				>
					{src.state}
				</span>
			</div>
			<dl class="space-y-1 text-xs text-slate-400">
				<div class="flex justify-between">
					<dt>Last fetch</dt>
					<dd class="text-slate-300">{formatAge(src.lastSuccessfulFetch)}</dd>
				</div>
				<div class="flex justify-between">
					<dt>Circuit breaker</dt>
					<dd class="capitalize text-slate-300">{src.circuitBreaker}</dd>
				</div>
				<div class="flex justify-between">
					<dt>Consecutive failures</dt>
					<dd class="text-slate-300">{src.consecutiveFailures}</dd>
				</div>
				{#if src.lastError}
					<div>
						<dt class="text-red-400">Last error</dt>
						<dd class="mt-0.5 font-mono text-[11px] text-red-300/90">{src.lastError}</dd>
					</div>
				{/if}
			</dl>
			{#if $isDeveloperMode}
				<div class="mt-4 flex gap-2">
					<button
						type="button"
						class="rounded bg-blue-800 px-3 py-1 text-xs text-white hover:bg-blue-700"
						onclick={() => probeSource(src.name)}
					>
						Probe now
					</button>
					<button
						type="button"
						class="rounded border border-[var(--color-border)] px-3 py-1 text-xs disabled:opacity-40"
						disabled={src.circuitBreaker === 'closed'}
						title={src.circuitBreaker === 'closed' ? 'Breaker already closed' : 'Reset breaker'}
						onclick={() => resetCircuitBreaker(src.name)}
					>
						Reset breaker
					</button>
				</div>
			{/if}
		</article>
	{/each}
</div>
