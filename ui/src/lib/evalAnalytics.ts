// Pure eval view helpers for strategy detail analytics. Mirrors operator-facing
// thresholds used alongside server metrics from core/eval/metrics.py.

import type { CalibrationBucket, EvalSnapshotView } from './types';

/** Brier at or below this is labeled "tight" in strategy verdict copy. */
export const BRIER_TIGHT_THRESHOLD = 0.23;

/** High-probability calibration bins at or above this predicted mean are checked for overconfidence. */
export const OVERCONFIDENCE_HIGH_PREDICTED_MIN = 0.7;

/** Minimum predicted−observed gap before a high bin is flagged as overconfident. */
export const OVERCONFIDENCE_GAP_MIN = 0.03;

export type CalibrationBinInput = Pick<
	EvalSnapshotView['calibrationBins'][number],
	'predictedMean' | 'observedFreq' | 'count'
>;

export interface OverconfidenceCallout {
	predicted: number;
	observed: number;
}

export function isBrierTight(brierScore: number): boolean {
	return brierScore <= BRIER_TIGHT_THRESHOLD;
}

export function isEdgeProven(posteriorEdgeCiLow: number): boolean {
	return posteriorEdgeCiLow > 0;
}

export function findOverconfidentHighBin(
	bins: CalibrationBinInput[]
): OverconfidenceCallout | null {
	const high = bins.filter(
		(b) =>
			b.predictedMean >= OVERCONFIDENCE_HIGH_PREDICTED_MIN &&
			b.count > 0 &&
			b.predictedMean - b.observedFreq > OVERCONFIDENCE_GAP_MIN
	);
	if (high.length === 0) return null;
	const worst = high.reduce((a, b) =>
		a.predictedMean - a.observedFreq > b.predictedMean - b.observedFreq ? a : b
	);
	return {
		predicted: Math.round(worst.predictedMean * 100),
		observed: Math.round(worst.observedFreq * 100)
	};
}

export function evalWindowOptions(windows: EvalSnapshotView[]): string[] {
	return windows.length > 0 ? windows.map((w) => w.window) : ['7d', '30d', 'all'];
}

export function resolveSelectedEvalWindow(
	windows: EvalSnapshotView[],
	selectedWindow: string
): string {
	if (windows.length === 0) return selectedWindow;
	if (windows.some((w) => w.window === selectedWindow)) return selectedWindow;
	return windows.find((w) => w.window === '30d')?.window ?? windows[0].window;
}

export function activeEvalSnapshot(
	windows: EvalSnapshotView[],
	selectedWindow: string
): EvalSnapshotView | undefined {
	return windows.find((w) => w.window === selectedWindow) ?? windows[0];
}

export function calibrationBucketsForSnapshot(
	snapshot: EvalSnapshotView | undefined,
	fallback: CalibrationBucket[]
): CalibrationBucket[] {
	if (!snapshot) return fallback;
	return snapshot.calibrationBins.map((b, i) => ({
		bucket: i,
		predicted: b.predictedMean,
		actual: b.observedFreq,
		count: b.count
	}));
}
