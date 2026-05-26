<script lang="ts">
	import type { CalibrationBucket } from '$lib/types';

	let {
		buckets,
		size = 220,
		legendId = 'calibration-chart-legend'
	}: { buckets: CalibrationBucket[]; size?: number; legendId?: string } = $props();

	const pad = { top: 20, right: 12, bottom: 36, left: 44 };
	const inner = $derived({
		w: size - pad.left - pad.right,
		h: size - pad.top - pad.bottom
	});
	const midY = $derived(pad.top + inner.h / 2);
</script>

<figure class="inline-block">
	<svg
		width={size}
		height={size}
		class="text-slate-400"
		role="img"
		aria-labelledby={legendId}
		aria-describedby="{legendId}-desc"
	>
		<title id={legendId}>Calibration plot: predicted vs actual yes rate by probability bucket</title>

		<!-- perfect calibration diagonal -->
		<line
			x1={pad.left}
			y1={pad.top + inner.h}
			x2={pad.left + inner.w}
			y2={pad.top}
			stroke="#475569"
			stroke-dasharray="4 3"
		/>
		{#each buckets as b}
			{@const px = pad.left + b.predicted * inner.w}
			{@const py = pad.top + inner.h - b.actual * inner.h}
			<circle
				cx={px}
				cy={py}
				r={Math.min(8, 3 + b.count / 4)}
				fill="#3b82f6"
				fill-opacity="0.7"
			/>
		{/each}

		<!-- axis tick labels -->
		<text x={pad.left} y={size - 8} class="fill-slate-500 text-[9px]">0</text>
		<text x={pad.left + inner.w - 6} y={size - 8} class="fill-slate-500 text-[9px]">1</text>
		<text x={6} y={pad.top + inner.h} class="fill-slate-500 text-[9px]">0</text>
		<text x={6} y={pad.top + 8} class="fill-slate-500 text-[9px]">1</text>

		<!-- axis titles -->
		<text
			x={pad.left + inner.w / 2}
			y={size - 2}
			text-anchor="middle"
			class="fill-slate-400 text-[10px]"
		>
			Predicted P(yes)
		</text>
		<text
			x={14}
			y={midY}
			text-anchor="middle"
			transform="rotate(-90 14 {midY})"
			class="fill-slate-400 text-[10px]"
		>
			Actual yes rate
		</text>
	</svg>

	<ul class="mt-1.5 flex flex-wrap gap-x-3 gap-y-0.5 text-[10px] text-slate-500" aria-hidden="true">
		<li class="flex items-center gap-1">
			<span class="inline-block h-0 w-4 border-t border-dashed border-slate-500"></span>
			Perfect calibration
		</li>
		<li class="flex items-center gap-1">
			<span class="inline-block h-2 w-2 rounded-full bg-blue-500 opacity-70"></span>
			Larger dot = more trades
		</li>
	</ul>
</figure>
