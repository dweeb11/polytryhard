import { derived, writable } from 'svelte/store';
import { env } from '$env/dynamic/public';
import { isBackendConfigured } from './client';

export type ApiMode = 'live' | 'mock';

function hasBackendUrl(): boolean {
	return Boolean((env.PUBLIC_BACKEND_URL ?? '').trim());
}

/** Set by BackendStatusBadge after health checks. */
export const backendHealth = writable<'checking' | 'ok' | 'down' | 'unconfigured'>(
	isBackendConfigured() ? 'checking' : 'unconfigured'
);

export const apiMode = derived(
	[backendHealth],
	([$health]): ApiMode => {
		if (!hasBackendUrl()) return 'mock';
		return $health === 'ok' ? 'live' : 'mock';
	}
);

export const apiModeLabel = derived(apiMode, ($mode) =>
	$mode === 'live' ? 'Live backend' : 'Mock prototype'
);
