import { audit, sources, strategies, system } from '$lib/stores';
import type { AuditEvent, SourceHealth, SourceState, StrategyInstance, SystemEnvState } from '$lib/types';
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

function mapSourceEntry(entry: Record<string, unknown>): SourceHealth {
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
}
