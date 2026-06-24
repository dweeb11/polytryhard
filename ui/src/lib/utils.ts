import type { PaperPosition, SignalOutcome, StrategyInstance } from './types';

export function uuid(): string {
	return crypto.randomUUID();
}

export function nowIso(): string {
	return new Date().toISOString();
}

export function freeCashCents(
	strategy: StrategyInstance,
	positions: PaperPosition[]
): number {
	const reserved = positions
		.filter((p) => p.strategyName === strategy.name && p.status === 'open')
		.reduce((sum, p) => sum + p.costBasisCents, 0);
	return Math.max(0, strategy.bankrollCents - reserved);
}

export function drawdownPct(strategy: StrategyInstance): number {
	if (strategy.bankrollHwmCents <= 0) return 0;
	return (
		((strategy.bankrollHwmCents - strategy.bankrollCents) / strategy.bankrollHwmCents) * 100
	);
}

export function formatCents(cents: number): string {
	const sign = cents < 0 ? '-' : '';
	const abs = Math.abs(cents);
	return `${sign}$${(abs / 100).toFixed(2)}`;
}

export function compareIsoDesc(a: string, b: string): number {
	const ta = Date.parse(a);
	const tb = Date.parse(b);
	const na = Number.isNaN(ta) ? Number.NEGATIVE_INFINITY : ta;
	const nb = Number.isNaN(tb) ? Number.NEGATIVE_INFINITY : tb;
	return nb - na;
}

export function formatIsoDateTime(iso: string): string {
	if (!iso) return '—';
	const ms = Date.parse(iso);
	if (Number.isNaN(ms)) return '—';
	return new Date(ms).toLocaleString();
}

/** UTC calendar day key (`YYYY-MM-DD`) for an ISO timestamp. */
export function utcDayKey(iso: string): string {
	const ms = Date.parse(iso);
	if (Number.isNaN(ms)) return '';
	return new Date(ms).toISOString().slice(0, 10);
}

export function isUtcToday(iso: string, nowMs: number = Date.now()): boolean {
	const key = utcDayKey(iso);
	if (!key) return false;
	return key === new Date(nowMs).toISOString().slice(0, 10);
}

export function utcYesterdayKey(nowMs: number = Date.now()): string {
	const d = new Date(nowMs);
	d.setUTCDate(d.getUTCDate() - 1);
	return d.toISOString().slice(0, 10);
}

export function formatUtcMonthDay(iso: string): string {
	const ms = Date.parse(iso);
	if (Number.isNaN(ms)) return '—';
	return new Date(ms).toLocaleDateString('en-US', {
		month: 'short',
		day: 'numeric',
		timeZone: 'UTC'
	});
}

/** Compact 24h time for ledger/signal rows (local timezone). */
export function compactIsoTime(iso: string): string {
	if (!iso) return '—';
	const ms = Date.parse(iso);
	if (Number.isNaN(ms)) return '—';
	return new Date(ms).toLocaleTimeString([], {
		hour: '2-digit',
		minute: '2-digit',
		hour12: false
	});
}

/** Group list items under consecutive `signalDayGroupLabel` headings. */
export function groupItemsByDayLabel<T>(
	items: readonly T[],
	getIso: (item: T) => string,
	nowMs: number = Date.now()
): Array<{ day: string; items: T[] }> {
	const groups: Array<{ day: string; items: T[] }> = [];
	for (const item of items) {
		const day = signalDayGroupLabel(getIso(item), nowMs);
		const group = groups.at(-1);
		if (group && group.day === day) group.items.push(item);
		else groups.push({ day, items: [item] });
	}
	return groups;
}

/** Group label for signal lists: `Today · Jun 1`, `Yesterday · …`, or `Jun 1`. */
export function signalDayGroupLabel(iso: string, nowMs: number = Date.now()): string {
	const key = utcDayKey(iso);
	if (!key) return '—';
	const todayKey = new Date(nowMs).toISOString().slice(0, 10);
	const md = formatUtcMonthDay(iso);
	if (key === todayKey) return `Today · ${md}`;
	if (key === utcYesterdayKey(nowMs)) return `Yesterday · ${md}`;
	return md;
}

export function formatAge(
	iso: string | null | undefined,
	nowMs: number = Date.now()
): string {
	if (!iso) return '—';
	const ms = Date.parse(iso);
	if (Number.isNaN(ms)) return '—';
	const sec = Math.max(0, Math.floor((nowMs - ms) / 1000));
	if (sec < 60) return `${sec}s ago`;
	if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
	if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
	return `${Math.floor(sec / 86400)}d ago`;
}

export function clamp(n: number, min: number, max: number): number {
	return Math.min(max, Math.max(min, n));
}

export const PAUSABLE_STATES = ['active'] as const;
export const RESUMABLE_STATES = [
	'low_bankroll_paused',
	'drawdown_paused',
	'operator_paused'
] as const;
// Mirrors backend AUTO_RESUME_ON_DEPOSIT_STATES: only a low-bankroll pause
// clears automatically on deposit. Drawdown/operator pauses require an
// explicit resume even when a deposit crosses the bankroll floor.
export const AUTO_RESUME_ON_DEPOSIT_STATES = ['low_bankroll_paused'] as const;

export function strategyStateLabel(state: string): string {
	return state.replace(/_/g, ' ');
}

export function formatOutcomeLabel(outcome: SignalOutcome | string): string {
	if (outcome === 'unknown_outcome') return 'unknown outcome';
	return outcome.replace(/_/g, ' ');
}

export function outcomeColor(outcome: SignalOutcome | string): string {
	if (outcome === 'order_placed') return 'text-emerald-400';
	if (outcome === 'unknown_outcome') return 'text-red-400';
	if (outcome === 'rejected_system_paused') return 'text-red-400';
	if (outcome.startsWith('rejected_')) return 'text-amber-400';
	return 'text-slate-300';
}
