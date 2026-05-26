<script lang="ts">
	import { plugins } from '$lib/stores';
	import { togglePlugin } from '$lib/actions';
	import { formatAge } from '$lib/utils';
	import type { PluginType } from '$lib/types';

	const order: PluginType[] = [
		'source',
		'feature_provider',
		'strategy',
		'executor',
		'rubric'
	];

	const grouped = $derived(
		order
			.map((type) => ({
				type,
				items: $plugins.filter((p) => p.type === type)
			}))
			.filter((g) => g.items.length > 0)
	);
</script>

<h1 class="mb-4 text-xl font-semibold">Plugins</h1>

{#each grouped as group}
	<section class="mb-6">
		<h2 class="mb-2 text-sm font-medium uppercase tracking-wide text-[var(--color-muted)]">
			{group.type.replace(/_/g, ' ')}
		</h2>
		<ul class="space-y-2">
			{#each group.items as plugin}
				<li class="rounded border border-[var(--color-border)] bg-[var(--color-panel)] p-3">
					<div class="flex items-start justify-between gap-2">
						<div>
							<span class="font-medium">{plugin.name}</span>
							<span class="ml-2 text-xs text-[var(--color-muted)]">v{plugin.version}</span>
							<p class="mt-1 text-xs text-[var(--color-muted)]">
								requires: {plugin.requires.length ? plugin.requires.join(', ') : '—'} · provides:
								{plugin.provides.join(', ')}
							</p>
							<p class="text-xs text-[var(--color-muted)]">
								last toggled {formatAge(plugin.lastToggledAt)}
							</p>
						</div>
						<label class="flex items-center gap-2 text-sm">
							<input
								type="checkbox"
								checked={plugin.enabled}
								onchange={(e) =>
									togglePlugin(plugin.id, (e.currentTarget as HTMLInputElement).checked)}
							/>
							{plugin.enabled ? 'on' : 'off'}
						</label>
					</div>
					{#if !plugin.enabled}
						{#each $plugins.filter((p) => p.type === 'strategy') as sp}
							{#if sp.requires.includes(plugin.name) || sp.requires.some((r) => plugin.provides.includes(r))}
								<p class="mt-2 text-xs text-amber-400">
									Would block: {sp.name} (missing {plugin.name})
								</p>
							{/if}
						{/each}
					{/if}
				</li>
			{/each}
		</ul>
	</section>
{/each}
