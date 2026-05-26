<script lang="ts">
	import '../app.css';
	import { get } from 'svelte/store';
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import {
		currentEnv,
		strategies,
		system,
		systemPaused,
		subscribePersistence
	} from '$lib/stores';
	import { toasts, dismissToast } from '$lib/stores/toasts';
	import { isDeveloperMode, uiMode } from '$lib/stores/uiMode';
	import { tickSimulatorEnabled } from '$lib/stores/tick';
	import { initTickFromStore, setTickEnabled } from '$lib/mocks/tick';
	import {
		tripKillSwitch,
		resumeKillSwitch,
		switchEnv,
		resetEnv
	} from '$lib/actions';
	import type { EnvName } from '$lib/types';
	import Modal from '$lib/components/Modal.svelte';
	import BackendStatusBadge from '$lib/components/BackendStatusBadge.svelte';

	let { children } = $props();

	let killModal = $state(false);
	let resumeModal = $state(false);
	let resetModal = $state(false);
	let killReason = $state('');
	let resumeReason = $state('');

	const overviewNav = [{ href: '/', label: 'Overview' }];

	onMount(() => {
		const unsub = subscribePersistence();
		if (get(uiMode) === 'release') {
			setTickEnabled(false);
		}
		initTickFromStore();
		return unsub;
	});

	function handleEnvChange(e: Event) {
		const v = (e.target as HTMLSelectElement).value as EnvName;
		switchEnv(v);
	}

	function confirmKill() {
		tripKillSwitch(killReason);
		killModal = false;
		killReason = '';
	}

	function confirmResume() {
		resumeKillSwitch(resumeReason);
		resumeModal = false;
		resumeReason = '';
	}

	function confirmReset() {
		resetEnv($currentEnv);
		resetModal = false;
	}
</script>

<div class="flex h-dvh flex-col overflow-hidden">
	<header
		class="flex shrink-0 flex-wrap items-center gap-3 border-b border-[var(--color-border)] bg-[var(--color-panel)] px-4 py-2 text-sm"
	>
		<span class="font-semibold tracking-tight text-slate-100">polytryhard</span>
		<BackendStatusBadge />
		{#if $isDeveloperMode}
			<span class="rounded bg-slate-800 px-2 py-0.5 text-xs text-slate-400">prototype</span>

			<label class="flex items-center gap-1 text-slate-400">
				Env
				<select
					class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-1 text-slate-200"
					value={$currentEnv}
					onchange={handleEnvChange}
				>
					<option value="main">main</option>
					<option value="staging">staging</option>
				</select>
			</label>
		{/if}

		<span
			class="rounded px-2 py-0.5 text-xs font-medium {$system.state === 'active'
				? 'bg-emerald-900/40 text-emerald-300'
				: 'bg-red-900/40 text-red-300'}"
		>
			System: {$system.state}
		</span>

		{#if $systemPaused}
			<button
				type="button"
				class="rounded border border-emerald-700 px-2 py-1 text-emerald-300 hover:bg-emerald-900/30"
				onclick={() => (resumeModal = true)}
			>
				Resume kill switch
			</button>
		{:else}
			<button
				type="button"
				class="rounded border border-red-700 px-2 py-1 text-red-300 hover:bg-red-900/30"
				onclick={() => (killModal = true)}
			>
				Trip kill switch
			</button>
		{/if}

		{#if $isDeveloperMode}
			<label class="ml-auto flex items-center gap-2 text-slate-400">
				<input
					type="checkbox"
					checked={$tickSimulatorEnabled}
					onchange={(e) => setTickEnabled((e.target as HTMLInputElement).checked)}
				/>
				Tick sim (~3s)
			</label>

			<button
				type="button"
				class="rounded border border-[var(--color-border)] px-2 py-1 text-slate-400 hover:text-slate-200"
				onclick={() => (resetModal = true)}
			>
				Reset env
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
							class="block rounded px-2 py-1.5 {$page.url.pathname === item.href
								? 'bg-slate-700 text-white'
								: 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
						>
							{item.label}
						</a>
					</li>
				{/each}
			</ul>
			<p class="mt-4 px-2 text-xs uppercase tracking-wide text-slate-500">Strategies</p>
			<ul class="mt-1 min-h-0 flex-1 space-y-0.5 overflow-y-auto">
				{#each $strategies as s (s.name)}
					<li>
						<a
							href="/strategies/{s.name}"
							class="block truncate rounded px-2 py-1 text-xs {$page.url.pathname ===
							`/strategies/${s.name}`
								? 'bg-slate-700 text-white'
								: 'text-slate-400 hover:bg-slate-800'}"
						>
							{s.name}
						</a>
					</li>
				{/each}
			</ul>
			<div class="mt-auto border-t border-[var(--color-border)] pt-3">
				<a
					href="/settings"
					class="block rounded px-2 py-1.5 {$page.url.pathname.startsWith('/settings')
						? 'bg-slate-700 text-white'
						: 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'}"
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
				class="pointer-events-auto rounded border px-3 py-2 text-sm shadow-lg {t.type === 'success'
					? 'border-emerald-700 bg-emerald-950 text-emerald-100'
					: t.type === 'error'
						? 'border-red-700 bg-red-950 text-red-100'
						: 'border-slate-600 bg-slate-900 text-slate-200'}"
			>
				<button
					type="button"
					class="float-right ml-2 text-slate-400"
					onclick={() => dismissToast(t.id)}>×</button
				>
				{t.message}
			</div>
		{/each}
	</div>
</div>

<Modal open={killModal} title="Trip kill switch" onclose={() => (killModal = false)}>
	<p class="mb-2 text-xs text-slate-400">All executor actions will be blocked until resumed.</p>
	<textarea
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-slate-900 p-2 text-sm"
		placeholder="Reason (required)"
		bind:value={killReason}
		rows="3"
	></textarea>
	<button
		type="button"
		class="w-full rounded bg-red-700 py-2 text-sm font-medium text-white hover:bg-red-600"
		onclick={confirmKill}
	>
		Confirm trip
	</button>
</Modal>

<Modal open={resumeModal} title="Resume kill switch" onclose={() => (resumeModal = false)}>
	<textarea
		class="mb-3 w-full rounded border border-[var(--color-border)] bg-slate-900 p-2 text-sm"
		placeholder="Reason (required)"
		bind:value={resumeReason}
		rows="3"
	></textarea>
	<button
		type="button"
		class="w-full rounded bg-emerald-700 py-2 text-sm font-medium text-white hover:bg-emerald-600"
		onclick={confirmResume}
	>
		Resume system
	</button>
</Modal>

<Modal open={resetModal} title="Reset environment" onclose={() => (resetModal = false)}>
	<p class="mb-3 text-sm text-slate-400">
		Wipe localStorage for <strong>{$currentEnv}</strong> and reload fixture seed data.
	</p>
	<button
		type="button"
		class="w-full rounded bg-slate-600 py-2 text-sm text-white hover:bg-slate-500"
		onclick={confirmReset}
	>
		Reset {$currentEnv}
	</button>
</Modal>
