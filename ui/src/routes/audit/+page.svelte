<script lang="ts">
	import { audit } from '$lib/stores';

	const pageSize = 15;
	let page = $state(0);
	let expanded = $state<Set<string>>(new Set());

	const sorted = $derived([...$audit].sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime()));
	const totalPages = $derived(Math.max(1, Math.ceil(sorted.length / pageSize)));
	const slice = $derived(sorted.slice(page * pageSize, page * pageSize + pageSize));

	function toggle(id: string) {
		const next = new Set(expanded);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		expanded = next;
	}
</script>

<h1 class="mb-4 text-lg font-semibold text-slate-100">Audit log</h1>

<div class="overflow-x-auto rounded border border-[var(--color-border)] text-sm">
	<table class="w-full text-left">
		<thead class="bg-slate-800/80 text-xs text-slate-400">
			<tr>
				<th class="px-3 py-2">Time</th>
				<th class="px-3 py-2">Actor</th>
				<th class="px-3 py-2">Action</th>
				<th class="px-3 py-2">Target</th>
				<th class="px-3 py-2">Reason</th>
				<th class="px-3 py-2"></th>
			</tr>
		</thead>
		<tbody>
			{#each slice as ev}
				<tr class="border-t border-[var(--color-border)] align-top">
					<td class="px-3 py-2 text-xs text-slate-400 whitespace-nowrap"
						>{new Date(ev.occurredAt).toLocaleString()}</td
					>
					<td class="px-3 py-2">{ev.actor}</td>
					<td class="px-3 py-2 font-mono text-xs">{ev.action}</td>
					<td class="px-3 py-2 text-xs">{ev.targetType}/{ev.targetId}</td>
					<td class="px-3 py-2 max-w-xs truncate text-slate-400" title={ev.reason}>{ev.reason}</td>
					<td class="px-3 py-2">
						<button
							type="button"
							class="text-xs text-blue-400 hover:underline"
							onclick={() => toggle(ev.id)}
						>
							{expanded.has(ev.id) ? 'Hide' : 'Diff'}
						</button>
					</td>
				</tr>
				{#if expanded.has(ev.id)}
					<tr class="border-t border-slate-800 bg-slate-900/50">
						<td colspan="6" class="px-3 py-2">
							<div class="grid gap-2 text-xs font-mono md:grid-cols-2">
								<div>
									<p class="mb-1 text-slate-500">before</p>
									<pre class="overflow-x-auto rounded bg-slate-950 p-2 text-slate-300">{JSON.stringify(
											ev.beforeState,
											null,
											2
										)}</pre>
								</div>
								<div>
									<p class="mb-1 text-slate-500">after</p>
									<pre class="overflow-x-auto rounded bg-slate-950 p-2 text-slate-300">{JSON.stringify(
											ev.afterState,
											null,
											2
										)}</pre>
								</div>
							</div>
							<p class="mt-1 text-[10px] text-slate-500">request_id: {ev.requestId}</p>
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
	</table>
</div>

<div class="mt-3 flex items-center gap-2 text-sm text-slate-400">
	<button
		type="button"
		class="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40"
		disabled={page === 0}
		onclick={() => page--}
	>
		Prev
	</button>
	<span>Page {page + 1} / {totalPages}</span>
	<button
		type="button"
		class="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40"
		disabled={page >= totalPages - 1}
		onclick={() => page++}
	>
		Next
	</button>
</div>
