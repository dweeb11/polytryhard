<script lang="ts">
	import { audit } from '$lib/stores';
	import { formatAge } from '$lib/utils';

	let page = $state(0);
	const pageSize = 10;

	const sorted = $derived([...$audit].sort(
		(a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime()
	));
	const totalPages = $derived(Math.max(1, Math.ceil(sorted.length / pageSize)));
	const slice = $derived(sorted.slice(page * pageSize, page * pageSize + pageSize));

	let expanded = $state<Record<string, boolean>>({});
</script>

<h1 class="mb-4 text-xl font-semibold">Audit log</h1>

<div class="overflow-x-auto rounded border border-[var(--color-border)]">
	<table class="w-full text-left text-sm">
		<thead class="bg-[var(--color-panel)] text-[var(--color-muted)]">
			<tr>
				<th class="px-3 py-2">When</th>
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
					<td class="px-3 py-2 text-xs">{formatAge(ev.occurredAt)}</td>
					<td class="px-3 py-2">{ev.actor}</td>
					<td class="px-3 py-2 font-mono text-xs">{ev.action}</td>
					<td class="px-3 py-2 text-xs">{ev.targetType}/{ev.targetId}</td>
					<td class="px-3 py-2 max-w-xs truncate text-xs text-[var(--color-muted)]">
						{ev.reason}
					</td>
					<td class="px-3 py-2">
						<button
							type="button"
							class="text-xs text-[var(--color-accent)] hover:underline"
							onclick={() => (expanded[ev.id] = !expanded[ev.id])}
						>
							{expanded[ev.id] ? 'Hide' : 'Diff'}
						</button>
					</td>
				</tr>
				{#if expanded[ev.id]}
					<tr class="border-t border-[var(--color-border)] bg-slate-900/50">
						<td colspan="6" class="px-3 py-2">
							<pre class="overflow-x-auto text-xs text-slate-300">{JSON.stringify(
									{ before: ev.beforeState, after: ev.afterState },
									null,
									2
								)}</pre>
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
	</table>
</div>

<div class="mt-3 flex items-center gap-2 text-sm">
	<button
		type="button"
		class="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40"
		disabled={page === 0}
		onclick={() => page--}
	>
		Prev
	</button>
	<span class="text-[var(--color-muted)]">Page {page + 1} / {totalPages}</span>
	<button
		type="button"
		class="rounded border border-[var(--color-border)] px-2 py-1 disabled:opacity-40"
		disabled={page >= totalPages - 1}
		onclick={() => page++}
	>
		Next
	</button>
</div>
