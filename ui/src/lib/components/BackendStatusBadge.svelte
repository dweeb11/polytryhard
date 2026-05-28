<script lang="ts">
	import { onMount } from 'svelte';
	import { env } from '$env/dynamic/public';
	import { backendHealth } from '$lib/api/mode';
	import { isBackendConfigured } from '$lib/api/client';
	import { hydrateLedgerFromApi } from '$lib/api/hydrate';

	const backendUrl = env.PUBLIC_BACKEND_URL;

	let label = $state(
		isBackendConfigured() ? 'Backend: checking' : 'Backend: mock (no URL)'
	);

	async function checkBackend(): Promise<void> {
		if (!isBackendConfigured() || !backendUrl) {
			backendHealth.set('unconfigured');
			label = 'Backend: mock (no URL)';
			return;
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
				await hydrateLedgerFromApi();
				return;
			}
			backendHealth.set('down');
			label = 'Backend: down';
		} catch {
			backendHealth.set('down');
			label = 'Backend: down';
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
