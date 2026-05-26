import { derived, get, writable } from 'svelte/store';
import { FIXTURES } from '../mocks/fixtures';
import type {
	AuditEvent,
	BankrollPoint,
	CalibrationBucket,
	CashEvent,
	EnvName,
	EnvSnapshot,
	PaperPosition,
	Plugin,
	Signal,
	SourceHealth,
	StrategyInstance,
	SystemEnvState
} from '../types';

export const currentEnv = writable<EnvName>('main');


function storageKey(env: EnvName): string {
	return `polytryhard:${env}`;
}

function loadPersisted(env: EnvName): EnvSnapshot | null {
	if (typeof localStorage === 'undefined') return null;
	try {
		const raw = localStorage.getItem(storageKey(env));
		if (!raw) return null;
		return JSON.parse(raw) as EnvSnapshot;
	} catch {
		return null;
	}
}

function persist(env: EnvName, snap: EnvSnapshot): void {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(storageKey(env), JSON.stringify(snap));
}

function hydrate(env: EnvName): EnvSnapshot {
	return loadPersisted(env) ?? structuredClone(FIXTURES[env]);
}

let activeEnv: EnvName = 'main';
let snapshot: EnvSnapshot = hydrate('main');

export const strategies = writable<StrategyInstance[]>(snapshot.strategies);
export const signals = writable<Signal[]>(snapshot.signals);
export const sources = writable<SourceHealth[]>(snapshot.sources);
export const plugins = writable<Plugin[]>(snapshot.plugins);
export const audit = writable<AuditEvent[]>(snapshot.audit);
export const cashEvents = writable<CashEvent[]>(snapshot.cashEvents);
export const positions = writable<PaperPosition[]>(snapshot.positions);
export const system = writable<SystemEnvState>(snapshot.system);
export const calibrationByStrategy = writable<Record<string, CalibrationBucket[]>>(
	snapshot.calibration
);
export const bankrollHistoryByStrategy = writable<Record<string, BankrollPoint[]>>(
	snapshot.bankrollHistory
);

function syncFromSnapshot(): void {
	strategies.set(snapshot.strategies);
	signals.set(snapshot.signals);
	sources.set(snapshot.sources);
	plugins.set(snapshot.plugins);
	audit.set(snapshot.audit);
	cashEvents.set(snapshot.cashEvents);
	positions.set(snapshot.positions);
	system.set(snapshot.system);
	calibrationByStrategy.set(snapshot.calibration);
	bankrollHistoryByStrategy.set(snapshot.bankrollHistory);
}

function pullSnapshot(): EnvSnapshot {
	return {
		strategies: get(strategies),
		signals: get(signals),
		sources: get(sources),
		plugins: get(plugins),
		audit: get(audit),
		cashEvents: get(cashEvents),
		positions: get(positions),
		system: get(system),
		calibration: get(calibrationByStrategy),
		bankrollHistory: get(bankrollHistoryByStrategy)
	};
}

export function persistCurrent(): void {
	snapshot = pullSnapshot();
	persist(activeEnv, snapshot);
}

export function subscribePersistence(): () => void {
	const stores = [
		strategies,
		signals,
		sources,
		plugins,
		audit,
		cashEvents,
		positions,
		system,
		calibrationByStrategy,
		bankrollHistoryByStrategy
	];
	const unsubs = stores.map((s) => s.subscribe(() => persistCurrent()));
	return () => unsubs.forEach((u) => u());
}

export function loadEnv(env: EnvName): void {
	activeEnv = env;
	snapshot = hydrate(env);
	syncFromSnapshot();
	currentEnv.set(env);
}

export function resetEnvToFixtures(env: EnvName): void {
	if (typeof localStorage !== 'undefined') {
		localStorage.removeItem(storageKey(env));
	}
	if (env === activeEnv) {
		snapshot = structuredClone(FIXTURES[env]);
		syncFromSnapshot();
	}
}

export const systemPaused = derived(system, ($s) => $s.state === 'paused');

/** strategy name -> missing requirement labels when a required plugin capability is off */
export const strategyBlockedBy = derived([plugins, strategies], ([$plugins, $strategies]) => {
	const enabledProvides = new Set($plugins.filter((p) => p.enabled).flatMap((p) => p.provides));
	const map = new Map<string, string[]>();
	for (const strat of $strategies) {
		const sp = $plugins.find(
			(p) => p.type === 'strategy' && (p.id === `strategy-${strat.name}` || p.name === strat.name)
		);
		if (!sp) continue;
		const missing = sp.requires.filter((r) => !enabledProvides.has(r));
		if (missing.length) map.set(strat.name, missing);
	}
	return map;
});
