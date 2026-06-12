<script lang="ts">
	import '../app.css';
	import { get } from 'svelte/store';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { strategies, system, systemPaused } from '$lib/stores';
	import { toasts, dismissToast } from '$lib/stores/toasts';
	import { apiModeLabel } from '$lib/api/mode';
	import { isDeveloperMode, uiMode } from '$lib/stores/uiMode';
	import { tickSimulatorEnabled } from '$lib/stores/tick';
	import { initTickFromStore, setTickEnabled } from '$lib/mocks/tick';
	import { tripKillSwitch, resumeKillSwitch, resetPrototype } from '$lib/actions';
	import Modal from '$lib/components/Modal.svelte';
	import BackendStatusBadge from '$lib/components/BackendStatusBadge.svelte';

	let { children } = $props();

	let killModal = $state(false);
	let resumeModal = $state(false);
	let resetModal = $state(false);
	let killReason = $state('');
	let resumeReason = $state('');

	const overviewNav = [
		{ href: '/', label: 'Overview' },
		{ href: '/trading', label: 'Trading' }
	];

	onMount(() => {
		if (get(uiMode) === 'release') {
			setTickEnabled(false);
		}
		initTickFromStore();
	});

	function confirmKill() {
		void tripKillSwitch(killReason);
		killModal = false;
		killReason = '';
	}

	function confirmResume() {
		void resumeKillSwitch(resumeReason);
		resumeModal = false;
		resumeReason = '';
	}

	function confirmReset() {
		resetPrototype('reset to fixtures');
		resetModal = false;
	}
</script>

<div class="flex h-dvh flex-col overflow-hidden">
	<header
		class="flex shrink-0 flex-wrap items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-panel)] px-4 py-2.5 text-sm"
	>
		<span class="font-sans text-[15px] font-bold tracking-tight text-[var(--color-heading)]"
			>poly<span class="text-[var(--color-accent)]">tryhard</span></span
		>
		<BackendStatusBadge />
		<span
			class="rounded border border-[var(--color-border-bright)] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-[var(--color-muted)]"
			>{$apiModeLabel}</span
		>
		{#if $isDeveloperMode}
			<span
				class="rounded border border-[var(--color-border)] px-2 py-0.5 text-[10px] uppercase tracking-[0.12em] text-[var(--color-faint)]"
				>prototype</span
			>
		{/if}

		{#if $system.state === 'active'}
			<span class="text-xs font-medium text-[var(--color-accent)]">
				<span class="mr-1 inline-block h-2 w-2 animate-pulse rounded-full bg-[var(--color-accent)]"
				></span>System: trading
			</span>
		{:else}
			<span class="text-xs font-medium text-[var(--color-danger)]">
				<span class="mr-1 inline-block h-2 w-2 rounded-full bg-[var(--color-danger)]"></span>System:
				paused
			</span>
		{/if}

		{#if $systemPaused}
			<button
				type="button"
				class="rounded border border-[color-mix(in_srgb,var(--color-ok)_45%,transparent)] px-2.5 py-1 text-[11px] uppercase tracking-[0.1em] text-[var(--color-ok)] hover:bg-[color-mix(in_srgb,var(--color-ok)_12%,transparent)]"
				onclick={() => (resumeModal = true)}
			>
				Resume kill switch
			</button>
		{:else}
			<button
				type="button"
				class="rounded border border-[color-mix(in_srgb,var(--color-danger)_45%,transparent)] px-2.5 py-1 text-[11px] uppercase tracking-[0.1em] text-[var(--color-danger)] hover:bg-[color-mix(in_srgb,var(--color-danger)_12%,transparent)]"
				onclick={() => (killModal = true)}
			>
				⏻ Kill switch
			</button>
		{/if}

		{#if $isDeveloperMode}
			<label class="ml-auto flex items-center gap-2 text-xs text-[var(--color-muted)]">
				<input
					type="checkbox"
					checked={$tickSimulatorEnabled}
					onchange={(e) => setTickEnabled((e.target as HTMLInputElement).checked)}
				/>
				Tick sim (~3s)
			</label>

			<button
				type="button"
				class="rounded border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-muted)] hover:text-[var(--color-bright)]"
				onclick={() => (resetModal = true)}
			>
				Reset to fixtures
			</button>
		{/if}
	</header>

	<div class="flex min-h-0 flex-1 overflow-hidden">
		<nav
			class="flex h-full w-44 shrink-0 flex-col overflow-hidden border-r border-[var(--color-border)] bg-[var(--color-panel)] p-3 text-sm"
		>
			<ul class="space-y-1">
				{#each overviewNav as item (item.href)}
					<li>
						<a
							href={item.href}
							class="block rounded px-2 py-1.5 {$page.url.pathname === item.href ||
							(item.href !== '/' && $page.url.pathname.startsWith(item.href))
								? 'bg-[var(--color-panel-2)] font-medium text-[var(--color-accent)]'
								: 'text-[var(--color-muted)] hover:bg-[var(--color-panel-2)] hover:text-[var(--color-bright)]'}"
						>
							{item.label}
						</a>
					</li>
				{/each}
			</ul>
			<p class="mt-4 px-2 text-[10px] uppercase tracking-[0.18em] text-[var(--color-faint)]">
				Strategies
			</p>
			<ul class="mt-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
				{#each $strategies as s (s.name)}
					<li>
						<a
							href="/strategies/{s.name}"
							class="block truncate rounded px-2 py-1 text-xs {$page.url.pathname ===
							`/strategies/${s.name}`
								? 'bg-[var(--color-panel-2)] text-[var(--color-accent)]'
								: 'text-[var(--color-muted)] hover:bg-[var(--color-panel-2)]'}"
						>
							{s.name}
						</a>
					</li>
				{/each}
			</ul>
			<div class="mt-auto border-t border-[var(--color-border)] pt-3">
				<a
					href="/settings/sources"
					class="block rounded px-2 py-1.5 {$page.url.pathname.startsWith('/settings')
						? 'bg-[var(--color-panel-2)] text-[var(--color-accent)]'
						: 'text-[var(--color-muted)] hover:bg-[var(--color-panel-2)] hover:text-[var(--color-bright)]'}"
				>
					Settings
				</a>
			</div>
		</nav>
		<main class="min-h-0 flex-1 overflow-y-auto p-4">
			{@render children()}
		</main>
	</div>

	<div class="pointer-events-none fixed bottom-4 right-4 z-40 flex max-w-sm flex-col gap-2">
		{#each $toasts as t (t.id)}
			<div
				class="pointer-events-auto rounded border bg-[var(--color-panel-2)] px-3 py-2 text-sm shadow-lg {t.type ===
				'success'
					? 'border-[color-mix(in_srgb,var(--color-ok)_50%,transparent)] text-[var(--color-ok)]'
					: t.type === 'error'
						? 'border-[color-mix(in_srgb,var(--color-danger)_50%,transparent)] text-[var(--color-danger)]'
						: 'border-[var(--color-border-bright)] text-[var(--color-bright)]'}"
			>
				<button
					type="button"
					class="float-right ml-2 text-[var(--color-muted)]"
					onclick={() => dismissToast(t.id)}>×</button
				>
				{t.message}
			</div>
		{/each}
	</div>
</div>

<Modal open={killModal} title="Trip kill switch" onclose={() => (killModal = false)}>
	<p class="mb-2 text-xs text-[var(--color-muted)]">
		All executor actions will be blocked until resumed.
	</p>
	<textarea
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		placeholder="Reason (required)"
		bind:value={killReason}
		rows="3"
	></textarea>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-danger)] py-2 text-sm font-medium text-[var(--color-surface)] hover:opacity-90"
		onclick={confirmKill}
	>
		Confirm trip
	</button>
</Modal>

<Modal open={resumeModal} title="Resume kill switch" onclose={() => (resumeModal = false)}>
	<textarea
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-[var(--color-surface)] p-2 text-sm"
		placeholder="Reason (required)"
		bind:value={resumeReason}
		rows="3"
	></textarea>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-ok)] py-2 text-sm font-medium text-[var(--color-surface)] hover:opacity-90"
		onclick={confirmResume}
	>
		Resume system
	</button>
</Modal>

<Modal open={resetModal} title="Reset prototype" onclose={() => (resetModal = false)}>
	<p class="mb-3 text-sm text-[var(--color-muted)]">
		Wipe localStorage and reload fixture seed data. This cannot be undone.
	</p>
	<button
		type="button"
		class="w-full rounded bg-[var(--color-panel-2)] py-2 text-sm text-[var(--color-bright)] hover:bg-[var(--color-border)]"
		onclick={confirmReset}
	>
		Reset to fixtures
	</button>
</Modal>
