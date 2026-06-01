import { audit, positions, signals, sources, strategies, system } from '$lib/stores';
import type {
	AuditEvent,
	PaperPosition,
	PositionStatus,
	Signal,
	SignalOutcome,
	SourceHealth,
	SourceState,
	StrategyInstance,
	SystemEnvState
} from '$lib/types';
import { apiGet } from './client';

const SOURCE_DISPLAY_NAMES: Record<string, string> = {
	kalshi_markets: 'Kalshi Markets',
	open_meteo: 'Open-Meteo (GFS + ECMWF)'
};

function mapSourceStatus(status: string | null | undefined): SourceState {
	if (status === 'ok') return 'healthy';
	if (status === 'degraded') return 'degraded';
	return 'down';
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
	return {
		id: String(entry.id ?? ''),
		strategyName: String(entry.strategyName ?? ''),
		ticker: String(entry.ticker ?? ''),
		evaluatedAt: String(entry.evaluatedAt ?? ''),
		probYes: Number(entry.probYes ?? 0),
		confidence: Number(entry.confidence ?? 0),
		outcome: String(entry.outcome ?? 'rejected_below_threshold') as SignalOutcome,
		rejectionReason:
			typeof entry.rejectionReason === 'string'
				? entry.rejectionReason
				: entry.rejectionReason == null
					? null
					: String(entry.rejectionReason)
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

export async function hydrateLedgerFromApi(): Promise<void> {
	const [strategyList, systemState, auditEvents, sourceEntries, signalRecords, positionRecords] =
		await Promise.all([
			apiGet('/v1/strategies') as Promise<StrategyInstance[]>,
			apiGet('/v1/system') as Promise<SystemEnvState>,
			apiGet('/v1/audit', { limit: '50' }) as Promise<AuditEvent[]>,
			apiGet('/v1/sources') as Promise<Record<string, unknown>[]>,
			apiGet('/v1/signals', { limit: '100' }) as Promise<Record<string, unknown>[]>,
			apiGet('/v1/positions', { limit: '100' }) as Promise<Record<string, unknown>[]>
		]);
	strategies.set(strategyList);
	system.set(systemState);
	audit.set(auditEvents);
	sources.set(sourceEntries.map(mapSourceEntry));
	signals.set(signalRecords.map(mapSignalRecord));
	positions.set(positionRecords.map(mapPositionRecord));
}
