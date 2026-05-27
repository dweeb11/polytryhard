<script lang="ts">
	import { onMount } from 'svelte';
	import { env } from '$env/dynamic/public';

	type BackendStatus = 'mock' | 'checking' | 'ok' | 'down';

	const backendUrl = env.PUBLIC_BACKEND_URL;

	let status = $state<BackendStatus>(backendUrl ? 'checking' : 'mock');
	let label = $state(backendUrl ? 'Backend: checking' : 'Backend: mock');

	async function checkBackend(): Promise<void> {
		if (!backendUrl) return;
		status = 'checking';
		try {
			const response = await fetch(`${backendUrl.replace(/\/$/, '')}/healthz`);
			if (!response.ok) throw new Error(`healthz returned ${response.status}`);
			const body = await response.json();
			status = body.status === 'ok' ? 'ok' : 'down';
			label = `Backend: ${status}`;
		} catch {
			status = 'down';
			label = 'Backend: down';
		}
	}

	onMount(() => {
		if (!backendUrl) return;
		void checkBackend();
		const interval = window.setInterval(() => void checkBackend(), 30_000);
		return () => window.clearInterval(interval);
	});
</script>

<span
	class="rounded px-2 py-0.5 text-xs font-medium {status === 'ok'
		? 'bg-emerald-900/40 text-emerald-300'
		: status === 'down'
			? 'bg-red-900/40 text-red-300'
			: 'bg-slate-800 text-slate-400'}"
	title={backendUrl || 'No PUBLIC_BACKEND_URL configured; UI remains on mocks'}
>
	{label}
</span>
