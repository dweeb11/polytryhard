import { describe, expect, it } from 'vitest';

import {
	activeEvalSnapshot,
	BRIER_TIGHT_THRESHOLD,
	calibrationBucketsForSnapshot,
	evalWindowOptions,
	findOverconfidentHighBin,
	isBrierTight,
	isEdgeProven,
	OVERCONFIDENCE_HIGH_PREDICTED_MIN,
	resolveSelectedEvalWindow
} from '$lib/evalAnalytics';
import type { EvalSnapshotView } from '$lib/types';

function snapshot(
	window: string,
	overrides: Partial<EvalSnapshotView> = {}
): EvalSnapshotView {
	return {
		window,
		computedAt: '2026-06-01T00:00:00Z',
		nTrades: 10,
		nWins: 6,
		hitRate: 0.6,
		brierScore: 0.2,
		logLoss: 0.5,
		pnlCents: 400,
		sharpeProxy: 1.2,
		maxDrawdownCents: 100,
		posteriorEdgeMean: 0.05,
		posteriorEdgeCiLow: 0.01,
		posteriorEdgeCiHigh: 0.09,
		calibrationBins: [],
		...overrides
	};
}

describe('isBrierTight', () => {
	it('labels scores at or below the tight threshold as tight', () => {
		expect(isBrierTight(BRIER_TIGHT_THRESHOLD)).toBe(true);
		expect(isBrierTight(0.1)).toBe(true);
	});

	it('labels scores above the tight threshold as loose', () => {
		expect(isBrierTight(BRIER_TIGHT_THRESHOLD + 0.001)).toBe(false);
		expect(isBrierTight(0.3)).toBe(false);
	});
});

describe('isEdgeProven', () => {
	it('requires a strictly positive posterior edge lower bound', () => {
		expect(isEdgeProven(0.01)).toBe(true);
		expect(isEdgeProven(0)).toBe(false);
		expect(isEdgeProven(-0.01)).toBe(false);
	});
});

describe('findOverconfidentHighBin', () => {
	it('returns null when no high bins exceed the gap threshold', () => {
		expect(
			findOverconfidentHighBin([
				{ predictedMean: 0.75, observedFreq: 0.73, count: 5 }
			])
		).toBeNull();
	});

	it('ignores bins below the high predicted minimum', () => {
		expect(
			findOverconfidentHighBin([
				{ predictedMean: OVERCONFIDENCE_HIGH_PREDICTED_MIN - 0.01, observedFreq: 0.5, count: 5 }
			])
		).toBeNull();
	});

	it('ignores empty bins', () => {
		expect(
			findOverconfidentHighBin([
				{ predictedMean: 0.82, observedFreq: 0.5, count: 0 }
			])
		).toBeNull();
	});

	it('flags the worst high bin and rounds percentages', () => {
		const result = findOverconfidentHighBin([
			{ predictedMean: 0.75, observedFreq: 0.7, count: 4 },
			{ predictedMean: 0.82, observedFreq: 0.65, count: 6 }
		]);
		expect(result).toEqual({ predicted: 82, observed: 65 });
	});

	it('requires gap greater than the minimum', () => {
		expect(
			findOverconfidentHighBin([
				{ predictedMean: 0.8, observedFreq: 0.77, count: 3 }
			])
		).not.toBeNull();
		expect(
			findOverconfidentHighBin([
				{ predictedMean: 0.8, observedFreq: 0.78, count: 3 }
			])
		).toBeNull();
	});
});

describe('eval window helpers', () => {
	const windows = [
		snapshot('7d'),
		snapshot('30d'),
		snapshot('all', { nTrades: 20 })
	];

	it('lists API windows or default fallbacks', () => {
		expect(evalWindowOptions(windows)).toEqual(['7d', '30d', 'all']);
		expect(evalWindowOptions([])).toEqual(['7d', '30d', 'all']);
	});

	it('keeps a valid selected window', () => {
		expect(resolveSelectedEvalWindow(windows, '7d')).toBe('7d');
	});

	it('falls back to 30d then first window', () => {
		expect(resolveSelectedEvalWindow(windows, '90d')).toBe('30d');
		expect(resolveSelectedEvalWindow([snapshot('7d'), snapshot('all')], '90d')).toBe('7d');
	});

	it('selects the active snapshot for the chosen window', () => {
		expect(activeEvalSnapshot(windows, 'all')?.nTrades).toBe(20);
		expect(activeEvalSnapshot(windows, 'missing')?.window).toBe('7d');
	});
});

describe('calibrationBucketsForSnapshot', () => {
	it('maps snapshot bins to chart buckets', () => {
		const active = snapshot('30d', {
			calibrationBins: [
				{
					lower: 0.7,
					upper: 0.8,
					predictedMean: 0.75,
					observedFreq: 0.68,
					count: 4
				}
			]
		});
		expect(calibrationBucketsForSnapshot(active, [])).toEqual([
			{ bucket: 0, predicted: 0.75, actual: 0.68, count: 4 }
		]);
	});

	it('returns fallback buckets when snapshot is missing', () => {
		const fallback = [{ bucket: 1, predicted: 0.5, actual: 0.5, count: 2 }];
		expect(calibrationBucketsForSnapshot(undefined, fallback)).toBe(fallback);
	});
});
