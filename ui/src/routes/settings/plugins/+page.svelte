<script lang="ts">
	import { plugins } from '$lib/stores';
	import { togglePlugin } from '$lib/actions';

	const grouped = $derived.by(() => {
		const map = new Map<string, (typeof $plugins)>();
		for (const p of $plugins) {
			const list = map.get(p.type) ?? [];
			list.push(p);
			map.set(p.type, list);
		}
		return map;
	});
</script>

<h2 class="mb-4 text-sm font-medium text-slate-300">Plugins</h2>

{#each [...grouped.entries()] as [type, list] (type)}
	<section class="mb-6">
		<h3 class="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{type}</h3>
		<ul class="space-y-2">
			{#each list as plugin (plugin.id)}
				<li class="rounded border border-[var(--color-border)] p-3 text-sm">
					<div class="flex items-center justify-between gap-4">
						<div>
							<span class="font-medium text-slate-200">{plugin.name}</span>
							<span class="ml-2 text-xs text-slate-500">v{plugin.version}</span>
						</div>
						<label class="flex items-center gap-2 text-xs text-slate-400">
							<input
								type="checkbox"
								checked={plugin.enabled}
								onchange={(e) => {
									const on = (e.target as HTMLInputElement).checked;
									togglePlugin(plugin.id, on);
								}}
							/>
							{plugin.enabled ? 'enabled' : 'disabled'}
						</label>
					</div>
				</li>
			{/each}
		</ul>
	</section>
{/each}
