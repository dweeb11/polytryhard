import { describe, expect, it } from 'vitest';

import type {
	ApiCalibrationBin,
	ApiCashEvent,
	ApiPaperPositionRecord,
	ApiSignalRecord,
	ApiSourceHealthEntry
} from '$lib/api/schemas';

type FieldCoverage = 'mapped' | 'ignored';

/** Compile-time guard: every OpenAPI field must be mapped or explicitly ignored. */
const signalRecordCoverage = {
	id: 'mapped',
	strategyName: 'mapped',
	ticker: 'mapped',
	evaluatedAt: 'mapped',
	probYes: 'mapped',
	confidence: 'mapped',
	featuresSnapshot: 'ignored',
	marketState: 'ignored',
	outcome: 'mapped',
	rejectionReason: 'mapped'
} as const satisfies Record<keyof ApiSignalRecord, FieldCoverage>;

const paperPositionCoverage = {
	id: 'mapped',
	strategyName: 'mapped',
	ticker: 'mapped',
	side: 'mapped',
	openedAt: 'mapped',
	closedAt: 'mapped',
	openAvgPrice: 'mapped',
	qty: 'mapped',
	costBasisCents: 'mapped',
	realizedPnlCents: 'mapped',
	unrealizedPnlCents: 'mapped',
	status: 'mapped'
} as const satisfies Record<keyof ApiPaperPositionRecord, FieldCoverage>;

const cashEventCoverage = {
	id: 'mapped',
	strategyName: 'mapped',
	occurredAt: 'mapped',
	kind: 'mapped',
	amountCents: 'mapped',
	balanceAfterCents: 'mapped',
	reason: 'mapped',
	refPositionId: 'mapped'
} as const satisfies Record<keyof ApiCashEvent, FieldCoverage>;

const sourceHealthCoverage = {
	name: 'mapped',
	enabled: 'ignored',
	status: 'mapped',
	lastRunAt: 'mapped',
	lastSuccessAt: 'mapped',
	rowsLastRun: 'ignored',
	lastError: 'mapped'
} as const satisfies Record<keyof ApiSourceHealthEntry, FieldCoverage>;

const calibrationBinCoverage = {
	lower: 'ignored',
	upper: 'ignored',
	predictedMean: 'mapped',
	observedFreq: 'mapped',
	count: 'mapped'
} as const satisfies Record<keyof ApiCalibrationBin, FieldCoverage>;

describe('openapi mapper contract', () => {
	it('documents SignalRecord field coverage', () => {
		expect(Object.keys(signalRecordCoverage).length).toBeGreaterThan(0);
	});

	it('documents PaperPositionRecord field coverage', () => {
		expect(Object.keys(paperPositionCoverage).length).toBeGreaterThan(0);
	});

	it('documents CashEvent field coverage', () => {
		expect(Object.keys(cashEventCoverage).length).toBeGreaterThan(0);
	});

	it('documents SourceHealthEntry field coverage', () => {
		expect(Object.keys(sourceHealthCoverage).length).toBeGreaterThan(0);
	});

	it('documents CalibrationBin field coverage', () => {
		expect(Object.keys(calibrationBinCoverage).length).toBeGreaterThan(0);
	});
});
