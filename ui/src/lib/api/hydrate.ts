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
import { liveDataRefresh } from '$lib/api/liveDataRefresh';
import { tradingHydration } from '$lib/api/tradingHydration';
import type { ApiGetResponse } from '$lib/api/responses';
import type {
	ApiCalibrationBin,
	ApiCashEvent,
	ApiPaperPositionRecord,
	ApiSignalRecord,
	ApiSourceHealthEntry,
	ApiStrategyEval
} from '$lib/api/schemas';
import { compareIsoDesc } from '$lib/utils';
import type {
	BankrollPoint,
	CalibrationBucket,
	CashEvent,
	KnownSignalOutcome,
	PaperPosition,
	PositionStatus,
	Signal,
	SignalOutcome,
	SourceHealth,
	SourceState
} from '$lib/types';
import { KNOWN_SIGNAL_OUTCOMES } from '$lib/types';
import { apiGet } from './client';

/** Max rows per trading list; API supports `before` cursor pagination beyond this. */
export const HYDRATE_TRADING_LIMIT = 100;

const SOURCE_DISPLAY_NAMES: Record<string, string> = {
	kalshi_markets: 'Kalshi Markets',
	open_meteo: 'Open-Meteo (GFS + ECMWF)'
};

const KNOWN_SIGNAL_OUTCOME_SET = new Set<string>(KNOWN_SIGNAL_OUTCOMES);

function mapSourceStatus(status: string | null | undefined): SourceState {
	if (status === 'ok') return 'healthy';
	if (status === 'degraded') return 'degraded';
	return 'down';
}

export function parseSignalOutcome(raw: unknown): SignalOutcome {
	const value = typeof raw === 'string' ? raw : '';
	return KNOWN_SIGNAL_OUTCOME_SET.has(value) ? (value as KnownSignalOutcome) : 'unknown_outcome';
}

export function sortSignalsByEvaluatedAt(records: Signal[]): Signal[] {
	return [...records].sort((a, b) => compareIsoDesc(a.evaluatedAt, b.evaluatedAt));
}

export function sortPositionsByOpenedAt(records: PaperPosition[]): PaperPosition[] {
	return [...records].sort((a, b) => compareIsoDesc(a.openedAt, b.openedAt));
}

export function mapSourceEntry(entry: ApiSourceHealthEntry): SourceHealth {
	const name = entry.name;
	return {
		name,
		displayName: SOURCE_DISPLAY_NAMES[name] ?? name,
		state: mapSourceStatus(entry.status),
		lastSuccessfulFetch: entry.lastSuccessAt ?? entry.lastRunAt ?? '',
		lastError: entry.lastError ?? null
	};
}

export function mapSignalRecord(entry: ApiSignalRecord): Signal {
	const outcome = parseSignalOutcome(entry.outcome);
	let rejectionReason = entry.rejectionReason ?? null;
	if (outcome === 'unknown_outcome' && entry.outcome) {
		rejectionReason = rejectionReason ?? `Unknown API outcome: ${entry.outcome}`;
	}
	return {
		id: entry.id,
		strategyName: entry.strategyName,
		ticker: entry.ticker,
		evaluatedAt: entry.evaluatedAt,
		probYes: entry.probYes,
		confidence: entry.confidence,
		outcome,
		rejectionReason
	};
}

export function mapPositionRecord(entry: ApiPaperPositionRecord): PaperPosition {
	const status = entry.status;
	return {
		id: entry.id,
		strategyName: entry.strategyName,
		ticker: entry.ticker,
		side: entry.side === 'no' ? 'no' : 'yes',
		openedAt: entry.openedAt,
		closedAt: entry.closedAt ?? null,
		openAvgPrice: entry.openAvgPrice,
		qty: entry.qty,
		costBasisCents: entry.costBasisCents,
		realizedPnlCents: entry.realizedPnlCents ?? null,
		unrealizedPnlCents: entry.unrealizedPnlCents ?? null,
		status: (status === 'closed' || status === 'resolved' ? status : 'open') as PositionStatus
	};
}

export function mapCalibrationBins(bins: ApiCalibrationBin[]): CalibrationBucket[] {
	return bins.map((b, i) => ({
		bucket: i,
		predicted: b.predictedMean,
		actual: b.observedFreq,
		count: b.count
	}));
}

export function mapCashEventsToBankroll(
	events: Pick<ApiCashEvent, 'occurredAt' | 'balanceAfterCents'>[]
): BankrollPoint[] {
	return events
		.map((e) => ({
			at: e.occurredAt,
			bankrollCents: e.balanceAfterCents
		}))
		.sort((a, b) => -compareIsoDesc(a.at, b.at));
}

export function mapCashEventRecord(entry: ApiCashEvent): CashEvent {
	return {
		id: entry.id,
		strategyName: entry.strategyName,
		occurredAt: entry.occurredAt,
		kind: entry.kind,
		amountCents: entry.amountCents,
		balanceAfterCents: entry.balanceAfterCents,
		reason: entry.reason,
		refPositionId: entry.refPositionId
	};
}

export async function hydrateStrategyEval(name: string): Promise<void> {
	const detail = await apiGet<ApiStrategyEval>(`/v1/eval/${name}`);
	evalByStrategy.update((m) => ({ ...m, [name]: detail }));

	// Seed calibration from the first window; the Task 8 window selector drives the displayed window.
	const latest = detail.windows[0];
	if (latest) {
		calibrationByStrategy.update((m) => ({ ...m, [name]: mapCalibrationBins(latest.calibrationBins) }));
	}

	const events = await apiGet<ApiCashEvent[]>(`/v1/strategies/${name}/cash-events`);
	const mappedEvents = events.map(mapCashEventRecord);
	cashEvents.update((current) => [
		...mappedEvents,
		...current.filter((event) => event.strategyName !== name)
	]);
	bankrollHistoryByStrategy.update((m) => ({ ...m, [name]: mapCashEventsToBankroll(events) }));
}

export interface HydrateLedgerResult {
	failedEndpoints: string[];
}

function logHydrateFailure(endpoint: string, error: unknown): void {
	console.error(`Live data refresh failed: ${endpoint}`, error);
}

async function tryHydrate<T>(
	endpoint: string,
	fetch: () => Promise<T>,
	apply: (value: T) => void,
	failures: string[]
): Promise<void> {
	try {
		const value = await fetch();
		apply(value);
	} catch (error) {
		logHydrateFailure(endpoint, error);
		failures.push(endpoint);
	}
}

export async function hydrateLedgerFromApi(): Promise<HydrateLedgerResult> {
	const failures: string[] = [];
	liveDataRefresh.set({ status: 'refreshing', failedEndpoints: [] });

	await Promise.all([
		tryHydrate(
			'/v1/strategies',
			() => apiGet<ApiGetResponse<'/v1/strategies'>>('/v1/strategies'),
			(value) => strategies.set(value),
			failures
		),
		tryHydrate(
			'/v1/system',
			() => apiGet<ApiGetResponse<'/v1/system'>>('/v1/system'),
			(value) => system.set(value),
			failures
		),
		tryHydrate(
			'/v1/audit',
			() => apiGet<ApiGetResponse<'/v1/audit'>>('/v1/audit', { limit: '50' }),
			(value) => audit.set(value),
			failures
		),
		tryHydrate(
			'/v1/sources',
			() => apiGet<ApiGetResponse<'/v1/sources'>>('/v1/sources'),
			(value) => sources.set(value.map(mapSourceEntry)),
			failures
		)
	]);

	let signalRecords: Signal[] | null = null;
	try {
		const rows = await apiGet<ApiGetResponse<'/v1/signals'>>('/v1/signals', {
			limit: String(HYDRATE_TRADING_LIMIT)
		});
		signalRecords = sortSignalsByEvaluatedAt(rows.map(mapSignalRecord));
		tradingHydration.update((state) => ({ ...state, signals: 'fresh' }));
	} catch (error) {
		logHydrateFailure('/v1/signals', error);
		failures.push('/v1/signals');
		tradingHydration.update((state) => ({ ...state, signals: 'stale' }));
	}

	let positionRecords: PaperPosition[] | null = null;
	try {
		const rows = await apiGet<ApiGetResponse<'/v1/positions'>>('/v1/positions', {
			limit: String(HYDRATE_TRADING_LIMIT)
		});
		positionRecords = sortPositionsByOpenedAt(rows.map(mapPositionRecord));
		tradingHydration.update((state) => ({ ...state, positions: 'fresh' }));
	} catch (error) {
		logHydrateFailure('/v1/positions', error);
		failures.push('/v1/positions');
		tradingHydration.update((state) => ({ ...state, positions: 'stale' }));
	}

	if (signalRecords !== null) signals.set(signalRecords);
	if (positionRecords !== null) positions.set(positionRecords);

	try {
		const rosterRows = await apiGet<ApiGetResponse<'/v1/eval'>>('/v1/eval');
		evalRoster.set(Object.fromEntries(rosterRows.map((r) => [r.strategyName, r])));
	} catch (error) {
		logHydrateFailure('/v1/eval', error);
		failures.push('/v1/eval');
	}

	liveDataRefresh.set({
		status: failures.length === 0 ? 'fresh' : 'stale',
		failedEndpoints: failures
	});
	return { failedEndpoints: failures };
}
