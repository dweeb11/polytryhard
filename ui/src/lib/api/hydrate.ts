import { audit, positions, signals, sources, strategies, system } from '$lib/stores';
import { tradingHydration } from '$lib/api/tradingHydration';
import { compareIsoDesc } from '$lib/utils';
import type {
	AuditEvent,
	CalibrationBucket,
	KnownSignalOutcome,
	PaperPosition,
	PositionStatus,
	Signal,
	SignalOutcome,
	SourceHealth,
	SourceState,
	StrategyInstance,
	SystemEnvState
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

export function mapSourceEntry(entry: Record<string, unknown>): SourceHealth {
	const name = String(entry.name ?? '');
	return {
		name,
		displayName: SOURCE_DISPLAY_NAMES[name] ?? name,
		state: mapSourceStatus(typeof entry.status === 'string' ? entry.status : null),
		lastSuccessfulFetch:
			typeof entry.lastSuccessAt === 'string'
				? entry.lastSuccessAt
				: typeof entry.lastRunAt === 'string'
					? entry.lastRunAt
					: '',
		lastError: typeof entry.lastError === 'string' ? entry.lastError : null
	};
}

export function mapSignalRecord(entry: Record<string, unknown>): Signal {
	const rawOutcome = entry.outcome;
	const outcome = parseSignalOutcome(rawOutcome);
	let rejectionReason =
		typeof entry.rejectionReason === 'string'
			? entry.rejectionReason
			: entry.rejectionReason == null
				? null
				: String(entry.rejectionReason);
	if (outcome === 'unknown_outcome' && typeof rawOutcome === 'string' && rawOutcome) {
		rejectionReason = rejectionReason ?? `Unknown API outcome: ${rawOutcome}`;
	}
	return {
		id: String(entry.id ?? ''),
		strategyName: String(entry.strategyName ?? ''),
		ticker: String(entry.ticker ?? ''),
		evaluatedAt: String(entry.evaluatedAt ?? ''),
		probYes: Number(entry.probYes ?? 0),
		confidence: Number(entry.confidence ?? 0),
		outcome,
		rejectionReason
	};
}

export function mapPositionRecord(entry: Record<string, unknown>): PaperPosition {
	const status = String(entry.status ?? 'open');
	return {
		id: String(entry.id ?? ''),
		strategyName: String(entry.strategyName ?? ''),
		ticker: String(entry.ticker ?? ''),
		side: entry.side === 'no' ? 'no' : 'yes',
		openedAt: String(entry.openedAt ?? ''),
		closedAt:
			typeof entry.closedAt === 'string'
				? entry.closedAt
				: entry.closedAt == null
					? null
					: String(entry.closedAt),
		openAvgPrice: Number(entry.openAvgPrice ?? 0),
		qty: Number(entry.qty ?? 0),
		costBasisCents: Number(entry.costBasisCents ?? 0),
		realizedPnlCents:
			typeof entry.realizedPnlCents === 'number'
				? entry.realizedPnlCents
				: entry.realizedPnlCents == null
					? null
					: Number(entry.realizedPnlCents),
		unrealizedPnlCents:
			typeof entry.unrealizedPnlCents === 'number' ? entry.unrealizedPnlCents : null,
		status: (status === 'closed' || status === 'resolved' ? status : 'open') as PositionStatus
	};
}

export function mapCalibrationBins(
	bins: Array<Record<string, unknown>>
): CalibrationBucket[] {
	return bins.map((b, i) => ({
		bucket: i,
		predicted: Number(b.predictedMean ?? 0),
		actual: Number(b.observedFreq ?? 0),
		count: Number(b.count ?? 0)
	}));
}

export async function hydrateLedgerFromApi(): Promise<void> {
	const [strategyList, systemState, auditEvents, sourceEntries] = await Promise.all([
		apiGet('/v1/strategies') as Promise<StrategyInstance[]>,
		apiGet('/v1/system') as Promise<SystemEnvState>,
		apiGet('/v1/audit', { limit: '50' }) as Promise<AuditEvent[]>,
		apiGet('/v1/sources') as Promise<Record<string, unknown>[]>
	]);
	strategies.set(strategyList);
	system.set(systemState);
	audit.set(auditEvents);
	sources.set(sourceEntries.map(mapSourceEntry));

	let signalRecords: Signal[] | null = null;
	try {
		const rows = (await apiGet('/v1/signals', {
			limit: String(HYDRATE_TRADING_LIMIT)
		})) as Record<string, unknown>[];
		signalRecords = sortSignalsByEvaluatedAt(rows.map(mapSignalRecord));
		tradingHydration.update((state) => ({ ...state, signals: 'fresh' }));
	} catch {
		tradingHydration.update((state) => ({ ...state, signals: 'stale' }));
	}

	let positionRecords: PaperPosition[] | null = null;
	try {
		const rows = (await apiGet('/v1/positions', {
			limit: String(HYDRATE_TRADING_LIMIT)
		})) as Record<string, unknown>[];
		positionRecords = sortPositionsByOpenedAt(rows.map(mapPositionRecord));
		tradingHydration.update((state) => ({ ...state, positions: 'fresh' }));
	} catch {
		tradingHydration.update((state) => ({ ...state, positions: 'stale' }));
	}

	if (signalRecords !== null) signals.set(signalRecords);
	if (positionRecords !== null) positions.set(positionRecords);
}
