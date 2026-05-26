<script lang="ts">
	let {
		open = false,
		title,
		children,
		onclose
	}: {
		open?: boolean;
		title: string;
		children: import('svelte').Snippet;
		onclose: () => void;
	} = $props();
</script>

{#if open}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
		role="dialog"
		aria-modal="true"
	>
		<div class="w-full max-w-md rounded-lg border border-[var(--color-border)] bg-[var(--color-panel)] p-4 shadow-xl">
			<div class="mb-3 flex items-center justify-between">
				<h2 class="text-sm font-semibold text-slate-100">{title}</h2>
				<button
					type="button"
					class="text-slate-400 hover:text-slate-200"
					onclick={onclose}
					aria-label="Close"
				>
					×
				</button>
			</div>
			{@render children()}
		</div>
	</div>
{/if}
