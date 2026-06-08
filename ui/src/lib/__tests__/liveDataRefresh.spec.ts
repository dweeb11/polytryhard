import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import { dataRefreshLabel, dataRefreshTitle, liveDataRefresh } from '$lib/api/liveDataRefresh';

describe('liveDataRefresh', () => {
	it('labels stale refresh with endpoint details in title', () => {
		liveDataRefresh.set({
			status: 'stale',
			failedEndpoints: ['/v1/signals', '/v1/positions']
		});
		expect(get(dataRefreshLabel)).toBe('Data: stale');
		expect(
			dataRefreshTitle({
				status: 'stale',
				failedEndpoints: ['/v1/signals', '/v1/positions']
			})
		).toBe('Failed endpoints: /v1/signals, /v1/positions');
	});
});
