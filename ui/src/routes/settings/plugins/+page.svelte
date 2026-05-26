<script lang="ts">
	import { plugins, strategies, strategyBlockedBy } from '$lib/stores';
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

	function strategiesWouldBlock(pluginId: string, enabling: boolean): string[] {
		if (enabling) return [];
		const plugin = $plugins.find((p) => p.id === pluginId);
		if (!plugin) return [];
		const provides = new Set(
			$plugins.filter((p) => p.enabled && p.id !== pluginId).flatMap((p) => p.provides)
		);
		const blocked: string[] = [];
		for (const s of $strategies) {
			const sp = $plugins.find((p) => p.type === 'strategy' && p.name === s.name);
			if (!sp) continue;
			const missing = sp.requires.filter((r) => !provides.has(r) && plugin.provides.includes(r));
			if (missing.length) blocked.push(s.name);
		}
		return blocked;
	}
</script>

<h2 class="mb-4 text-sm font-medium text-slate-300">Plugins</h2>

{#each [...grouped.entries()] as [type, list] (type)}
	<section class="mb-6">
		<h3 class="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">{type}</h3>
		<ul class="space-y-2">
			{#each list as plugin (plugin.id)}
				{@const blocked = $strategyBlockedBy}
				<li class="rounded border border-[var(--color-border)] p-3 text-sm">
					<div class="flex items-center justify-between gap-4">
						<div>
							<span class="font-medium text-slate-200">{plugin.name}</span>
							<span class="ml-2 text-xs text-slate-500">v{plugin.version}</span>
							<p class="mt-1 text-xs text-slate-500">
								requires: {plugin.requires.length ? plugin.requires.join(', ') : '—'} · provides:
								{plugin.provides.join(', ')}
							</p>
						</div>
						<label class="flex items-center gap-2 text-xs text-slate-400">
							<input
								type="checkbox"
								checked={plugin.enabled}
								onchange={(e) => {
									const on = (e.target as HTMLInputElement).checked;
									const would = strategiesWouldBlock(plugin.id, on);
									togglePlugin(plugin.id, on);
									if (!on && would.length) {
										// blocked store updates reactively
									}
								}}
							/>
							{plugin.enabled ? 'enabled' : 'disabled'}
						</label>
					</div>
					{#if !plugin.enabled}
						{@const affected = [...blocked.entries()].filter(([, reqs]) =>
							reqs.some((r) => plugin.provides.includes(r) || plugin.requires.includes(r))
						)}
						{#if affected.length}
							<p class="mt-2 text-xs text-amber-400">
								Would block: {affected.map(([n]) => n).join(', ')} (missing requirements)
							</p>
						{/if}
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/each}
