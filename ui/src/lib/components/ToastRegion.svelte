<script lang="ts">
	import { toasts } from '$lib/stores';
</script>

<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
	{#each $toasts as t (t.id)}
		<div
			class="max-w-sm rounded border px-3 py-2 text-sm shadow-lg {t.type === 'success'
				? 'border-emerald-700 bg-emerald-950 text-emerald-200'
				: t.type === 'error'
					? 'border-red-800 bg-red-950 text-red-200'
					: 'border-[var(--color-border)] bg-[var(--color-panel)] text-slate-200'}"
		>
			{t.message}
		</div>
	{/each}
</div>
