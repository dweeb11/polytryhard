import { derived, writable } from 'svelte/store';

export type LiveDataRefreshStatus = 'idle' | 'refreshing' | 'fresh' | 'stale';

export interface LiveDataRefreshState {
	status: LiveDataRefreshStatus;
	failedEndpoints: string[];
}

/** Updated by hydrateLedgerFromApi on each live data refresh attempt. */
export const liveDataRefresh = writable<LiveDataRefreshState>({
	status: 'idle',
	failedEndpoints: []
});

export const dataRefreshLabel = derived(liveDataRefresh, ($state) => {
	switch ($state.status) {
		case 'idle':
			return 'Data: —';
		case 'refreshing':
			return 'Data: refreshing';
		case 'fresh':
			return 'Data: fresh';
		case 'stale':
			return 'Data: stale';
	}
});

export function dataRefreshTitle(state: LiveDataRefreshState): string {
	if (state.status !== 'stale' || state.failedEndpoints.length === 0) {
		return 'Live data refresh status';
	}
	return `Failed endpoints: ${state.failedEndpoints.join(', ')}`;
}
