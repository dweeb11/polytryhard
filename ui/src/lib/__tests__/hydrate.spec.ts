import { describe, expect, it } from 'vitest';

import { mapPositionRecord, mapSignalRecord } from '$lib/api/hydrate';

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
});
