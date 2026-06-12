<script lang="ts">
	import { strategyStateLabel } from '$lib/utils';

	let { state }: { state: string } = $props();

	const colors: Record<string, string> = {
		active: 'bg-emerald-900/50 text-emerald-300 border-emerald-700',
		drawdown_paused: 'bg-amber-900/50 text-amber-300 border-amber-700',
		operator_paused: 'bg-amber-900/50 text-amber-300 border-amber-700',
		low_bankroll_paused: 'bg-amber-900/50 text-amber-300 border-amber-700',
		decommissioned: 'bg-slate-700/50 text-slate-400 border-slate-600',
		seeded: 'bg-slate-700/50 text-slate-400 border-slate-600'
	};
</script>

<span
	class="inline-flex rounded border px-2 py-0.5 text-xs font-medium capitalize {colors[state] ??
		'bg-slate-800 text-slate-300 border-slate-600'}"
>
	{strategyStateLabel(state)}
</span>
