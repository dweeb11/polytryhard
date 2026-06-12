<script lang="ts">
	import type { BankrollPoint } from '$lib/types';

	let {
		points,
		tone = 'muted'
	}: { points: BankrollPoint[]; tone?: 'ok' | 'danger' | 'muted' } = $props();

	const W = 120;
	const H = 36;
	const PAD = 2;

	const stroke = $derived(
		tone === 'ok' ? 'var(--color-ok)' : tone === 'danger' ? 'var(--color-danger)' : 'var(--color-faint)'
	);

	const polyline = $derived.by(() => {
		if (points.length < 2) return '';
		const values = points.map((p) => p.bankrollCents);
		const min = Math.min(...values);
		const max = Math.max(...values);
		const span = max - min || 1;
		return points
			.map((p, i) => {
				const x = PAD + (i / (points.length - 1)) * (W - PAD * 2);
				const y = PAD + (1 - (p.bankrollCents - min) / span) * (H - PAD * 2);
				return `${x.toFixed(1)},${y.toFixed(1)}`;
			})
			.join(' ');
	});
</script>

{#if polyline}
	<svg viewBox="0 0 {W} {H}" width={W} height={H} aria-hidden="true">
		<polyline fill="none" {stroke} stroke-width="1.5" points={polyline} />
	</svg>
{/if}
