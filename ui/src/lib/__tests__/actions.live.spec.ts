import { beforeEach, describe, expect, it, vi } from 'vitest';

import { env } from '$env/dynamic/public';
env.PUBLIC_BACKEND_URL = 'http://test.local';
env.PUBLIC_BACKEND_TOKEN = 'test-token';
import { get } from 'svelte/store';
import { deposit, pauseStrategy, tripKillSwitch } from '$lib/actions';
import { backendHealth } from '$lib/api/mode';
import { strategies, system } from '$lib/stores';
import { resetToFixtures } from '$lib/stores';

const STRATEGY = 'weather_ensemble_disagreement';

const SOURCES_MOCK = [
	{
		name: 'kalshi_markets',
		enabled: false,
		status: 'degraded',
		lastRunAt: null,
		lastSuccessAt: null,
		rowsLastRun: null,
		lastError: 'Kalshi credentials not configured'
	},
	{
		name: 'open_meteo',
		enabled: true,
		status: 'ok',
		lastRunAt: '2026-05-28T12:00:00.000Z',
		lastSuccessAt: '2026-05-28T12:00:00.000Z',
		rowsLastRun: 48,
		lastError: null
	}
];

function setupLive(): void {
	localStorage.clear();
	resetToFixtures();
	backendHealth.set('ok');
}

describe('live API branch', () => {
	beforeEach(() => {
		vi.restoreAllMocks();
		setupLive();
	});

	it('deposit hydrates strategies from API response', async () => {
		const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url.endsWith('/healthz')) {
				return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
			}
			if (url.endsWith('/v1/strategies') && (!init || init.method === undefined)) {
				return new Response(
					JSON.stringify([
						{
							...get(strategies).find((s) => s.name === STRATEGY),
							bankrollCents: 999_999
						}
					]),
					{ status: 200 }
				);
			}
			if (url.includes('/deposit')) {
				return new Response(JSON.stringify({ id: 'evt', amountCents: 100 }), { status: 200 });
			}
			if (url.endsWith('/v1/system')) {
				return new Response(
					JSON.stringify({
						state: 'active',
						killSwitchReason: null,
						killSwitchTrippedAt: null
					}),
					{ status: 200 }
				);
			}
			if (url.includes('/v1/audit')) {
				return new Response(JSON.stringify([]), { status: 200 });
			}
			if (url.endsWith('/v1/sources')) {
				return new Response(JSON.stringify(SOURCES_MOCK), { status: 200 });
			}
			return new Response('not found', { status: 404 });
		});
		vi.stubGlobal('fetch', fetchMock);

		const result = await deposit(STRATEGY, 100, 'live');
		expect(result.ok).toBe(true);
		expect(get(strategies).find((s) => s.name === STRATEGY)!.bankrollCents).toBe(999_999);
	});

	it('kill switch uses system pause endpoint', async () => {
		const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url.endsWith('/v1/system/pause') && init?.method === 'POST') {
				return new Response(null, { status: 204 });
			}
			if (url.endsWith('/v1/strategies')) {
				return new Response(JSON.stringify(get(strategies)), { status: 200 });
			}
			if (url.endsWith('/v1/system')) {
				return new Response(
					JSON.stringify({
						state: 'paused',
						killSwitchReason: 'incident',
						killSwitchTrippedAt: new Date().toISOString()
					}),
					{ status: 200 }
				);
			}
			if (url.includes('/v1/audit')) {
				return new Response(JSON.stringify([]), { status: 200 });
			}
			if (url.endsWith('/v1/sources')) {
				return new Response(JSON.stringify(SOURCES_MOCK), { status: 200 });
			}
			return new Response('not found', { status: 404 });
		});
		vi.stubGlobal('fetch', fetchMock);

		const result = await tripKillSwitch('incident');
		expect(result.ok).toBe(true);
		expect(get(system).state).toBe('paused');
	});

	it('pause strategy calls API when live', async () => {
		const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
			const url = String(input);
			if (url.includes('/pause') && init?.method === 'POST') {
				return new Response(null, { status: 204 });
			}
			if (url.endsWith('/v1/strategies')) {
				const list = get(strategies).map((s) =>
					s.name === STRATEGY ? { ...s, state: 'operator_paused' } : s
				);
				return new Response(JSON.stringify(list), { status: 200 });
			}
			if (url.endsWith('/v1/system')) {
				return new Response(
					JSON.stringify({
						state: 'active',
						killSwitchReason: null,
						killSwitchTrippedAt: null
					}),
					{ status: 200 }
				);
			}
			if (url.includes('/v1/audit')) {
				return new Response(JSON.stringify([]), { status: 200 });
			}
			if (url.endsWith('/v1/sources')) {
				return new Response(JSON.stringify(SOURCES_MOCK), { status: 200 });
			}
			return new Response('not found', { status: 404 });
		});
		vi.stubGlobal('fetch', fetchMock);

		const result = await pauseStrategy(STRATEGY, 'live pause');
		expect(result.ok).toBe(true);
		expect(get(strategies).find((s) => s.name === STRATEGY)!.state).toBe('operator_paused');
	});
});
