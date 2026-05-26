<script lang="ts">
	import type { CalibrationBucket } from '$lib/types';

	let { buckets, size = 220 }: { buckets: CalibrationBucket[]; size?: number } = $props();

	const pad = 28;
	const inner = $derived(size - pad * 2);
</script>

<svg width={size} height={size} class="text-slate-400" role="img" aria-label="Calibration plot">
	<!-- perfect calibration diagonal -->
	<line
		x1={pad}
		y1={pad + inner}
		x2={pad + inner}
		y2={pad}
		stroke="#475569"
		stroke-dasharray="4 3"
	/>
	{#each buckets as b}
		{@const px = pad + b.predicted * inner}
		{@const py = pad + inner - b.actual * inner}
		<circle cx={px} cy={py} r={Math.min(8, 3 + b.count / 4)} fill="#3b82f6" fill-opacity="0.7" />
	{/each}
	<text x={pad} y={size - 6} class="fill-slate-500 text-[9px]">0</text>
	<text x={pad + inner - 8} y={pad + 10} class="fill-slate-500 text-[9px]">1</text>
</svg>
