// Pure presentation helpers that translate engine vocabulary (tickers, outcome
// enums, eval metrics) into operator-readable language. No I/O, no clock.

import type { EvalRosterEntryView, SignalOutcome, StrategyInstance } from './types';

const CITY_NAMES: Record<string, string> = {
	NY: 'NYC',
	CHI: 'Chicago',
	AUS: 'Austin',
	MIA: 'Miami',
	DEN: 'Denver',
	PHIL: 'Philadelphia',
	LAX: 'LA'
};

const MONTH_NAMES: Record<string, string> = {
	JAN: 'Jan',
	FEB: 'Feb',
	MAR: 'Mar',
	APR: 'Apr',
	MAY: 'May',
	JUN: 'Jun',
	JUL: 'Jul',
	AUG: 'Aug',
	SEP: 'Sep',
	OCT: 'Oct',
	NOV: 'Nov',
	DEC: 'Dec'
};

const KXHIGH_PATTERN = /^KXHIGH([A-Z]+)-(\d{2})([A-Z]{3})(\d{2})-T(\d+)$/;

/** "KXHIGHNY-25MAY26-T72" → "NYC high ≥ 72°F · May 26"; unknown shapes pass through. */
export function humanizeTicker(ticker: string): string {
	const match = KXHIGH_PATTERN.exec(ticker);
	if (!match) return ticker;
	const [, city, , monthCode, day, threshold] = match;
	const month = MONTH_NAMES[monthCode];
	if (!month) return ticker;
	const cityName = CITY_NAMES[city] ?? city;
	return `${cityName} high ≥ ${threshold}°F · ${month} ${Number(day)}`;
}

const OUTCOME_LABELS: Record<string, string> = {
	order_placed: 'order placed',
	rejected_kelly_zero: 'skipped · Kelly sized to zero',
	rejected_exposure_cap: 'skipped · exposure cap',
	rejected_correlation_cap: 'skipped · correlation cap',
	rejected_below_threshold: 'skipped · edge below threshold',
	rejected_below_min_position: 'skipped · below min position',
	rejected_market_closed: 'skipped · market closed',
	rejected_stale_inputs: 'blocked · stale inputs',
	rejected_system_paused: 'blocked · kill switch'
};

export function outcomeLabel(outcome: SignalOutcome | string): string {
	return OUTCOME_LABELS[outcome] ?? outcome.replace(/_/g, ' ');
}

export type OutcomeTone = 'placed' | 'skip' | 'block';

/**
 * placed → an order went out; skip → the strategy chose not to trade
 * (informational); block → a guardrail refused the trade (needs attention).
 */
export function outcomeTone(outcome: SignalOutcome | string): OutcomeTone {
	if (outcome === 'order_placed') return 'placed';
	if (outcome === 'rejected_stale_inputs' || outcome === 'rejected_system_paused') return 'block';
	if (outcome.startsWith('rejected_')) return 'skip';
	return 'block';
}

/** One-sentence card verdict: paused states first, then edge evidence. */
export function strategyVerdict(
	strategy: StrategyInstance,
	evalEntry: EvalRosterEntryView | null | undefined
): string {
	if (strategy.state === 'drawdown_paused') {
		return `Hit its ${strategy.config.maxDrawdownPctFromHwm.toFixed(0)}% drawdown stop — decide: refund or retire.`;
	}
	if (strategy.state === 'low_bankroll_paused') {
		return 'Bankroll fell below its floor — deposit to resume.';
	}
	if (strategy.state === 'operator_paused') {
		return 'Paused by operator.';
	}
	if (strategy.state === 'decommissioned') {
		return 'Decommissioned.';
	}
	if (strategy.state === 'seeded') {
		return 'Seeded — waiting for its first signals.';
	}
	if (!evalEntry || evalEntry.nTrades === 0) {
		return 'No resolved trades yet — verdict pending.';
	}
	if (evalEntry.posteriorEdgeCiLow != null && evalEntry.posteriorEdgeCiLow > 0) {
		return `Proven edge over ${evalEntry.nTrades} trades — worst-case bound is positive.`;
	}
	return `Edge not yet proven over ${evalEntry.nTrades} trades — CI still straddles zero.`;
}
