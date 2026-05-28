import { derived, get, writable } from 'svelte/store';
import { FIXTURE } from '../mocks/fixtures';
import type {
	AuditEvent,
	BankrollPoint,
	CalibrationBucket,
	CashEvent,
	EnvSnapshot,
	PaperPosition,
	Plugin,
	Signal,
	SourceHealth,
	StrategyInstance,
	SystemEnvState
} from '../types';

const STORAGE_KEY = 'polytryhard';

function loadPersisted(): EnvSnapshot | null {
	if (typeof localStorage === 'undefined') return null;
	try {
		const raw = localStorage.getItem(STORAGE_KEY);
		if (!raw) return null;
		return JSON.parse(raw) as EnvSnapshot;
	} catch {
		return null;
	}
}

function persist(snap: EnvSnapshot): void {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(STORAGE_KEY, JSON.stringify(snap));
}

function hydrate(): EnvSnapshot {
	return loadPersisted() ?? structuredClone(FIXTURE);
}

let snapshot: EnvSnapshot = hydrate();

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
	persist(snapshot);
}

export function resetToFixtures(): void {
	if (typeof localStorage !== 'undefined') {
		localStorage.removeItem(STORAGE_KEY);
	}
	snapshot = structuredClone(FIXTURE);
	syncFromSnapshot();
}

/** Reload in-memory stores from localStorage (or fixtures if empty). */
export function rehydrateFromStorage(): void {
	snapshot = hydrate();
	syncFromSnapshot();
}

export const systemPaused = derived(system, ($s) => $s.state === 'paused');
