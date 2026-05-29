import { audit, strategies, system } from '$lib/stores';
import type { AuditEvent, StrategyInstance, SystemEnvState } from '$lib/types';
import { apiGet } from './client';

export async function hydrateLedgerFromApi(): Promise<void> {
	const [strategyList, systemState, auditEvents] = await Promise.all([
		apiGet('/v1/strategies') as Promise<StrategyInstance[]>,
		apiGet('/v1/system') as Promise<SystemEnvState>,
		apiGet('/v1/audit', { limit: '50' }) as Promise<AuditEvent[]>
	]);
	strategies.set(strategyList);
	system.set(systemState);
	audit.set(auditEvents);
}
