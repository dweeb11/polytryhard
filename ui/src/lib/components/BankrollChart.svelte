<script lang="ts">
	import type { BankrollPoint } from '$lib/types';
	import { formatCents } from '$lib/utils';

	let { points, width = 400, height = 120 }: { points: BankrollPoint[]; width?: number; height?: number } =
		$props();

	const pad = { t: 8, r: 8, b: 24, l: 48 };
	const innerW = $derived(width - pad.l - pad.r);
	const innerH = $derived(height - pad.t - pad.b);

	const sorted = $derived([...points].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime()));
	const minY = $derived(Math.min(...sorted.map((p) => p.bankrollCents)) * 0.98);
	const maxY = $derived(Math.max(...sorted.map((p) => p.bankrollCents)) * 1.02);

	function x(i: number): number {
		if (sorted.length <= 1) return pad.l;
		return pad.l + (i / (sorted.length - 1)) * innerW;
	}
	function y(v: number): number {
		const range = maxY - minY || 1;
		return pad.t + innerH - ((v - minY) / range) * innerH;
	}

	const pathD = $derived(
		sorted.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p.bankrollCents).toFixed(1)}`).join(' ')
	);
</script>

<svg {width} {height} class="w-full max-w-full text-slate-400" role="img" aria-label="Bankroll history">
	<line x1={pad.l} y1={pad.t + innerH} x2={pad.l + innerW} y2={pad.t + innerH} stroke="#2d3a4f" />
	{#if sorted.length}
		<path d={pathD} fill="none" stroke="#3b82f6" stroke-width="2" />
		{#each sorted as p, i}
			<circle cx={x(i)} cy={y(p.bankrollCents)} r="2.5" fill="#60a5fa" />
		{/each}
		<text x={pad.l} y={height - 4} class="fill-slate-500 text-[10px]">
			{formatCents(sorted[0]?.bankrollCents ?? 0)}
		</text>
		<text x={pad.l + innerW - 40} y={height - 4} class="fill-slate-500 text-[10px]">
			{formatCents(sorted[sorted.length - 1]?.bankrollCents ?? 0)}
		</text>
	{/if}
</svg>
