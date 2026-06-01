import type { PaperPosition, StrategyInstance } from './types';

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

export function formatAge(iso: string): string {
	const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
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

export function strategyStateLabel(state: string): string {
	return state.replace(/_/g, ' ');
}

export function outcomeColor(outcome: string): string {
	if (outcome === 'order_placed') return 'text-emerald-400';
	if (outcome === 'rejected_system_paused') return 'text-red-400';
	if (outcome.startsWith('rejected_')) return 'text-amber-400';
	return 'text-slate-300';
}
