import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import {
	hydrateLedgerFromApi,
	hydrateStrategyEval,
	mapCalibrationBins,
	mapCashEventsToBankroll,
	mapPositionRecord,
	mapSignalRecord,
	parseSignalOutcome,
	sortPositionsByOpenedAt,
	sortSignalsByEvaluatedAt
} from '$lib/api/hydrate';
import { liveDataRefresh } from '$lib/api/liveDataRefresh';
import { tradingHydration } from '$lib/api/tradingHydration';
import {
	audit,
	bankrollHistoryByStrategy,
	calibrationByStrategy,
	cashEvents,
	evalByStrategy,
	evalRoster,
	positions,
	signals,
	sources,
	strategies,
	system
} from '$lib/stores';
import { FIXTURE } from '$lib/mocks/fixtures';
import type { ApiPaperPositionRecord, ApiSignalRecord } from '$lib/api/schemas';

const { apiGetMock } = vi.hoisted(() => ({
	apiGetMock: vi.fn()
}));

vi.mock('$lib/api/client', () => ({
	apiGet: apiGetMock
}));

const STRATEGY_LIST = FIXTURE.strategies;
const SYSTEM_STATE = FIXTURE.system;
const AUDIT_EVENTS = FIXTURE.audit.slice(0, 2);
const SOURCE_ENTRIES = [{ name: 'kalshi_markets', status: 'ok', lastSuccessAt: '2026-06-01T12:00:00Z' }];
const EVAL_ROSTER = [
	{
		strategyName: 'weather_ensemble_disagreement',
		nTrades: 5,
		hitRate: 0.6,
		brierScore: 0.2,
		pnlCents: 400,
		posteriorEdgeCiLow: 0.01
	},
	{
		strategyName: 'weather_stale_quote',
		nTrades: 0,
		hitRate: null,
		brierScore: null,
		pnlCents: 0,
		posteriorEdgeCiLow: null
	}
];

function apiSignal(overrides: Partial<ApiSignalRecord> & Pick<ApiSignalRecord, 'id'>): ApiSignalRecord {
	return {
		strategyName: 'weather_ensemble_disagreement',
		ticker: 'KXHIGHNY-26JUN01',
		evaluatedAt: '2026-06-01T12:00:00Z',
		probYes: 0.5,
		confidence: 0.5,
		outcome: 'order_placed',
		rejectionReason: null,
		...overrides
	};
}

function apiPosition(
	overrides: Partial<ApiPaperPositionRecord> & Pick<ApiPaperPositionRecord, 'id'>
): ApiPaperPositionRecord {
	return {
		strategyName: 'weather_ensemble_disagreement',
		ticker: 'KXHIGHNY-26JUN01',
		side: 'yes',
		openedAt: '2026-06-01T12:00:00Z',
		closedAt: null,
		openAvgPrice: 0.5,
		qty: 1,
		costBasisCents: 50,
		realizedPnlCents: null,
		unrealizedPnlCents: null,
		status: 'open',
		...overrides
	};
}

function mockCoreHydrate(): void {
	apiGetMock.mockImplementation((path: string) => {
		if (path === '/v1/strategies') return Promise.resolve(STRATEGY_LIST);
		if (path === '/v1/system') return Promise.resolve(SYSTEM_STATE);
		if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
		if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
		if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
		return Promise.reject(new Error(`unexpected path: ${path}`));
	});
}

describe('hydrate mappers', () => {
	it('maps signal records from API shape', () => {
		const signal = mapSignalRecord({
			id: 'sig-1',
			strategyName: 'weather_ensemble_disagreement',
			ticker: 'KXHIGHNY-26JUN01',
			evaluatedAt: '2026-06-01T12:00:00.000Z',
			probYes: 0.62,
			confidence: 0.8,
			outcome: 'order_placed',
			rejectionReason: null
		});
		expect(signal.outcome).toBe('order_placed');
		expect(signal.rejectionReason).toBeNull();
	});

	it('maps unknown signal outcomes to unknown_outcome with raw value in rejectionReason', () => {
		expect(parseSignalOutcome('not_a_real_outcome')).toBe('unknown_outcome');
		const signal = mapSignalRecord({
			...apiSignal({ id: 'sig-bogus' }),
			outcome: 'bogus'
		} as unknown as ApiSignalRecord);
		expect(signal.outcome).toBe('unknown_outcome');
		expect(signal.rejectionReason).toBe('Unknown API outcome: bogus');
	});

	it('maps position records and preserves null unrealized P&L', () => {
		const position = mapPositionRecord({
			id: 'pos-1',
			strategyName: 'weather_stale_quote',
			ticker: 'KXHIGHNY-26JUN01',
			side: 'yes',
			openedAt: '2026-06-01T12:00:00.000Z',
			closedAt: null,
			openAvgPrice: 0.45,
			qty: 10,
			costBasisCents: 450,
			realizedPnlCents: null,
			unrealizedPnlCents: null,
			status: 'open'
		});
		expect(position.unrealizedPnlCents).toBeNull();
		expect(position.side).toBe('yes');
	});

	it('sorts signals newest-first by evaluatedAt', () => {
		const sorted = sortSignalsByEvaluatedAt([
			mapSignalRecord(apiSignal({ id: 'a', evaluatedAt: '2026-06-01T10:00:00Z' })),
			mapSignalRecord(apiSignal({ id: 'b', evaluatedAt: '2026-06-01T12:00:00Z' })),
			mapSignalRecord(apiSignal({ id: 'c', evaluatedAt: '2026-06-01T11:00:00Z' }))
		]);
		expect(sorted.map((s) => s.id)).toEqual(['b', 'c', 'a']);
	});

	it('sorts positions newest-first by openedAt', () => {
		const sorted = sortPositionsByOpenedAt([
			mapPositionRecord(apiPosition({ id: 'a', openedAt: '2026-06-01T10:00:00Z' })),
			mapPositionRecord(apiPosition({ id: 'b', openedAt: '2026-06-01T12:00:00Z' }))
		]);
		expect(sorted.map((p) => p.id)).toEqual(['b', 'a']);
	});
});

describe('hydrateLedgerFromApi', () => {
	beforeEach(() => {
		apiGetMock.mockReset();
		localStorage.clear();
		tradingHydration.set({ signals: 'fresh', positions: 'fresh' });
		liveDataRefresh.set({ status: 'idle', failedEndpoints: [] });
	});

	it('hydrates core ledger and trading endpoints', async () => {
		mockCoreHydrate();
		apiGetMock.mockImplementation((path: string) => {
			if (path === '/v1/signals') {
				return Promise.resolve([
					{
						id: 'sig-new',
						strategyName: 'weather_ensemble_disagreement',
						ticker: 'KXHIGHNY-26JUN01',
						evaluatedAt: '2026-06-01T13:00:00Z',
						probYes: 0.55,
						confidence: 0.7,
						outcome: 'order_placed',
						rejectionReason: null
					}
				]);
			}
			if (path === '/v1/positions') {
				return Promise.resolve([
					{
						id: 'pos-new',
						strategyName: 'weather_ensemble_disagreement',
						ticker: 'KXHIGHNY-26JUN01',
						side: 'yes',
						openedAt: '2026-06-01T13:00:00Z',
						closedAt: null,
						openAvgPrice: 0.5,
						qty: 5,
						costBasisCents: 250,
						realizedPnlCents: null,
						unrealizedPnlCents: 120,
						status: 'open'
					}
				]);
			}
			if (path === '/v1/strategies') return Promise.resolve(STRATEGY_LIST);
			if (path === '/v1/system') return Promise.resolve(SYSTEM_STATE);
			if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
			if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
			if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		await hydrateLedgerFromApi();

		expect(get(strategies)).toEqual(STRATEGY_LIST);
		expect(get(system)).toEqual(SYSTEM_STATE);
		expect(get(audit)).toEqual(AUDIT_EVENTS);
		expect(get(sources)).toHaveLength(1);
		expect(get(signals)).toHaveLength(1);
		expect(get(signals)[0]?.id).toBe('sig-new');
		expect(get(positions)).toHaveLength(1);
		expect(get(positions)[0]?.id).toBe('pos-new');
		expect(get(tradingHydration)).toEqual({ signals: 'fresh', positions: 'fresh' });
		expect(get(liveDataRefresh)).toEqual({ status: 'fresh', failedEndpoints: [] });
	});

	it('sorts hydrated signals newest-first', async () => {
		mockCoreHydrate();
		apiGetMock.mockImplementation((path: string) => {
			if (path === '/v1/signals') {
				return Promise.resolve([
					{
						id: 'older',
						evaluatedAt: '2026-06-01T10:00:00Z',
						outcome: 'order_placed'
					},
					{
						id: 'newer',
						evaluatedAt: '2026-06-01T12:00:00Z',
						outcome: 'order_placed'
					}
				]);
			}
			if (path === '/v1/positions') return Promise.resolve([]);
			if (path === '/v1/strategies') return Promise.resolve(STRATEGY_LIST);
			if (path === '/v1/system') return Promise.resolve(SYSTEM_STATE);
			if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
			if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
			if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		await hydrateLedgerFromApi();

		expect(get(signals).map((s) => s.id)).toEqual(['newer', 'older']);
	});

	it('keeps existing signals and positions when trading endpoints fail', async () => {
		signals.set([mapSignalRecord(apiSignal({ id: 'local-sig', evaluatedAt: '2026-06-01T09:00:00Z' }))]);
		positions.set([mapPositionRecord(apiPosition({ id: 'local-pos', openedAt: '2026-06-01T09:00:00Z' }))]);
		mockCoreHydrate();
		apiGetMock.mockImplementation((path: string) => {
			if (path === '/v1/signals' || path === '/v1/positions') {
				return Promise.reject(new Error('endpoint unavailable'));
			}
			if (path === '/v1/strategies') return Promise.resolve(STRATEGY_LIST);
			if (path === '/v1/system') return Promise.resolve(SYSTEM_STATE);
			if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
			if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
			if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		await hydrateLedgerFromApi();

		expect(get(strategies)).toEqual(STRATEGY_LIST);
		expect(get(signals)).toHaveLength(1);
		expect(get(signals)[0]?.id).toBe('local-sig');
		expect(get(positions)).toHaveLength(1);
		expect(get(positions)[0]?.id).toBe('local-pos');
		expect(get(tradingHydration)).toEqual({ signals: 'stale', positions: 'stale' });
		expect(get(liveDataRefresh)).toEqual({
			status: 'stale',
			failedEndpoints: ['/v1/signals', '/v1/positions']
		});
	});

	it('updates signals but keeps positions when only positions endpoint fails', async () => {
		positions.set([mapPositionRecord(apiPosition({ id: 'local-pos', openedAt: '2026-06-01T09:00:00Z' }))]);
		mockCoreHydrate();
		apiGetMock.mockImplementation((path: string) => {
			if (path === '/v1/signals') {
				return Promise.resolve([
					{ id: 'remote-sig', evaluatedAt: '2026-06-01T12:00:00Z', outcome: 'order_placed' }
				]);
			}
			if (path === '/v1/positions') return Promise.reject(new Error('positions down'));
			if (path === '/v1/strategies') return Promise.resolve(STRATEGY_LIST);
			if (path === '/v1/system') return Promise.resolve(SYSTEM_STATE);
			if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
			if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
			if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		await hydrateLedgerFromApi();

		expect(get(signals)[0]?.id).toBe('remote-sig');
		expect(get(positions)[0]?.id).toBe('local-pos');
		expect(get(tradingHydration)).toEqual({ signals: 'fresh', positions: 'stale' });
		expect(get(liveDataRefresh)).toEqual({
			status: 'stale',
			failedEndpoints: ['/v1/positions']
		});
	});

	it('keeps prior core ledger data when core endpoints fail', async () => {
		strategies.set(STRATEGY_LIST);
		system.set(SYSTEM_STATE);
		mockCoreHydrate();
		apiGetMock.mockImplementation((path: string) => {
			if (path === '/v1/strategies' || path === '/v1/system') {
				return Promise.reject(new Error('endpoint unavailable'));
			}
			if (path === '/v1/audit') return Promise.resolve(AUDIT_EVENTS);
			if (path === '/v1/sources') return Promise.resolve(SOURCE_ENTRIES);
			if (path === '/v1/signals') return Promise.resolve([]);
			if (path === '/v1/positions') return Promise.resolve([]);
			if (path === '/v1/eval') return Promise.resolve(EVAL_ROSTER);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		const result = await hydrateLedgerFromApi();

		expect(result.failedEndpoints).toEqual(['/v1/strategies', '/v1/system']);
		expect(get(strategies)).toEqual(STRATEGY_LIST);
		expect(get(system)).toEqual(SYSTEM_STATE);
		expect(get(liveDataRefresh).status).toBe('stale');
		expect(get(liveDataRefresh).failedEndpoints).toContain('/v1/strategies');
	});

	it('hydrates the eval roster store', async () => {
		mockCoreHydrate();
		await hydrateLedgerFromApi();
		const roster = get(evalRoster);
		expect(roster['weather_ensemble_disagreement']).toEqual({
			strategyName: 'weather_ensemble_disagreement', nTrades: 5, hitRate: 0.6, brierScore: 0.2, pnlCents: 400, posteriorEdgeCiLow: 0.01
		});
		expect(roster['weather_stale_quote'].brierScore).toBeNull();
		expect(roster['weather_stale_quote'].posteriorEdgeCiLow).toBeNull();
	});
});

describe('mapCashEventsToBankroll', () => {
	it('builds an ascending balance timeline from cash events', () => {
		const events = [
			{ occurredAt: '2026-06-02T00:00:00Z', balanceAfterCents: 11000 },
			{ occurredAt: '2026-06-01T00:00:00Z', balanceAfterCents: 10000 }
		];
		const points = mapCashEventsToBankroll(events);
		expect(points).toEqual([
			{ at: '2026-06-01T00:00:00Z', bankrollCents: 10000 },
			{ at: '2026-06-02T00:00:00Z', bankrollCents: 11000 }
		]);
	});

	it('returns [] when there are no events', () => {
		expect(mapCashEventsToBankroll([])).toEqual([]);
	});
});

describe('mapCalibrationBins', () => {
	it('maps API bins to chart buckets', () => {
		const bins = [
			{ lower: 0.0, upper: 0.1, predictedMean: 0.05, observedFreq: 0.0, count: 3 },
			{ lower: 0.5, upper: 0.6, predictedMean: 0.55, observedFreq: 0.5, count: 4 }
		];
		const buckets = mapCalibrationBins(bins);
		expect(buckets).toEqual([
			{ bucket: 0, predicted: 0.05, actual: 0.0, count: 3 },
			{ bucket: 1, predicted: 0.55, actual: 0.5, count: 4 }
		]);
	});

	it('returns [] for empty bins', () => {
		expect(mapCalibrationBins([])).toEqual([]);
	});
});

describe('hydrateStrategyEval', () => {
	it('populates eval + calibration + bankroll stores for a strategy in live mode', async () => {
		const name = 'weather_ensemble_disagreement';
		apiGetMock.mockImplementation((path: string) => {
			if (path === `/v1/eval/${name}`)
				return Promise.resolve({
					strategyName: name,
					windows: [
						{
							window: '30d', computedAt: '2026-06-01T00:00:00Z', nTrades: 4, nWins: 2,
							hitRate: 0.5, brierScore: 0.2, logLoss: 0.6, pnlCents: 300,
							sharpeProxy: 0.3, maxDrawdownCents: -40, posteriorEdgeMean: 0.05,
							posteriorEdgeCiLow: 0.0, posteriorEdgeCiHigh: 0.1,
							calibrationBins: [{ lower: 0.5, upper: 0.6, predictedMean: 0.55, observedFreq: 0.5, count: 4 }]
						}
					]
				});
			if (path === `/v1/strategies/${name}/cash-events`)
				return Promise.resolve([
					{
						id: 'live-cash-1',
						strategyName: name,
						occurredAt: '2026-06-01T00:00:00Z',
						kind: 'deposit',
						amountCents: 10300,
						balanceAfterCents: 10300,
						reason: 'seed',
						refPositionId: null
					}
				]);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});
		cashEvents.set([
			{
				id: 'stale-fixture-cash',
				strategyName: name,
				occurredAt: '2026-05-01T00:00:00Z',
				kind: 'realized_pnl',
				amountCents: 25000,
				balanceAfterCents: 125000,
				reason: 'fixture',
				refPositionId: null
			},
			{
				id: 'other-strategy-cash',
				strategyName: 'weather_stale_quote',
				occurredAt: '2026-05-01T00:00:00Z',
				kind: 'deposit',
				amountCents: 10000,
				balanceAfterCents: 10000,
				reason: 'other',
				refPositionId: null
			}
		]);

		await hydrateStrategyEval(name);

		expect(get(evalByStrategy)[name].strategyName).toBe(name);
		expect(get(evalByStrategy)[name].windows[0].window).toBe('30d');
		expect(get(calibrationByStrategy)[name][0].predicted).toBe(0.55);
		expect(get(bankrollHistoryByStrategy)[name][0].bankrollCents).toBe(10300);
		expect(get(cashEvents).filter((event) => event.strategyName === name)).toEqual([
			{
				id: 'live-cash-1',
				strategyName: name,
				occurredAt: '2026-06-01T00:00:00Z',
				kind: 'deposit',
				amountCents: 10300,
				balanceAfterCents: 10300,
				reason: 'seed',
				refPositionId: null
			}
		]);
		expect(get(cashEvents).some((event) => event.id === 'stale-fixture-cash')).toBe(false);
		expect(get(cashEvents).some((event) => event.id === 'other-strategy-cash')).toBe(true);
	});
});
