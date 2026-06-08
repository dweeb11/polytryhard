<script lang="ts">
	import { onMount } from 'svelte';
	import { env } from '$env/dynamic/public';
	import { backendHealth } from '$lib/api/mode';
	import {
		dataRefreshLabel,
		dataRefreshTitle,
		liveDataRefresh
	} from '$lib/api/liveDataRefresh';
	import { isBackendConfigured } from '$lib/api/client';
	import { hydrateLedgerFromApi } from '$lib/api/hydrate';

	const backendUrl = env.PUBLIC_BACKEND_URL;

	let label = $state(
		isBackendConfigured() ? 'Backend: checking' : 'Backend: mock (no URL)'
	);

	async function checkBackendHealth(): Promise<boolean> {
		if (!isBackendConfigured() || !backendUrl) {
			backendHealth.set('unconfigured');
			label = 'Backend: mock (no URL)';
			return false;
		}

		backendHealth.set('checking');
		label = 'Backend: checking';
		try {
			const response = await fetch(`${backendUrl.replace(/\/$/, '')}/healthz`);
			if (!response.ok) throw new Error(`healthz returned ${response.status}`);
			const body = await response.json();
			if (body.status === 'ok') {
				backendHealth.set('ok');
				label = 'Backend: ok';
				return true;
			}
			backendHealth.set('down');
			label = 'Backend: down';
			return false;
		} catch {
			backendHealth.set('down');
			label = 'Backend: down';
			return false;
		}
	}

	async function refreshLiveData(): Promise<void> {
		const { failedEndpoints } = await hydrateLedgerFromApi();
		if (failedEndpoints.length > 0) {
			console.warn('Live data refresh incomplete:', failedEndpoints.join(', '));
		}
	}

	async function checkBackend(): Promise<void> {
		const healthy = await checkBackendHealth();
		if (healthy) {
			await refreshLiveData();
		} else {
			liveDataRefresh.set({ status: 'idle', failedEndpoints: [] });
		}
	}

	onMount(() => {
		if (!isBackendConfigured()) return;
		void checkBackend();
		const interval = window.setInterval(() => void checkBackend(), 30_000);
		return () => window.clearInterval(interval);
	});
</script>

<span
	class="rounded px-2 py-0.5 text-xs font-medium {$backendHealth === 'ok'
		? 'bg-emerald-900/40 text-emerald-300'
		: $backendHealth === 'down'
			? 'bg-red-900/40 text-red-300'
			: 'bg-slate-800 text-slate-400'}"
	title={backendUrl || 'No PUBLIC_BACKEND_URL configured; UI uses mock prototype'}
>
	{label}
</span>

{#if isBackendConfigured()}
	<span
		class="rounded px-2 py-0.5 text-xs font-medium {$liveDataRefresh.status === 'fresh'
			? 'bg-emerald-900/40 text-emerald-300'
			: $liveDataRefresh.status === 'stale'
				? 'bg-amber-900/40 text-amber-300'
				: 'bg-slate-800 text-slate-400'}"
		title={dataRefreshTitle($liveDataRefresh)}
	>
		{$dataRefreshLabel}
	</span>
{/if}
