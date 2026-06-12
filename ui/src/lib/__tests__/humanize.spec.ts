import { describe, expect, it } from 'vitest';
import { humanizeTicker, outcomeLabel, outcomeTone, strategyVerdict } from '../humanize';
import type { StrategyInstance } from '../types';
import type { EvalRosterEntryView } from '../types';

function active(): StrategyInstance {
	return {
		name: 'weather_baseline_v2',
		enabled: true,
		state: 'active',
		bankrollCents: 51240,
		bankrollHwmCents: 52360,
		initialDepositCents: 50000,
		kellyFraction: 0.25,
		config: {
			minBankrollCents: 5000,
			minTradeableBankrollCents: 10000,
			maxDrawdownPctFromHwm: 12,
			autoResumeOnDeposit: true,
			maxInputAgeSeconds: 2700
		},
		lastStateChangeAt: '2026-06-01T00:00:00Z',
		todayPnlCents: 318
	};
}

function evalEntry(overrides: Partial<EvalRosterEntryView>): EvalRosterEntryView {
	return {
		strategyName: 'weather_baseline_v2',
		nTrades: 142,
		hitRate: 0.62,
		brierScore: 0.214,
		pnlCents: 1127,
		posteriorEdgeCiLow: 0.008,
		...overrides
	};
}

describe('humanizeTicker', () => {
	it('decodes KXHIGH city/date/threshold tickers', () => {
		expect(humanizeTicker('KXHIGHNY-25MAY26-T72')).toBe('NYC high ≥ 72°F · May 26');
		expect(humanizeTicker('KXHIGHCHI-25MAY26-T68')).toBe('Chicago high ≥ 68°F · May 26');
		expect(humanizeTicker('KXHIGHLAX-25MAY26-T75')).toBe('LA high ≥ 75°F · May 26');
	});

	it('falls back to the raw ticker for unknown patterns', () => {
		expect(humanizeTicker('KXBTC-25MAY26-B105')).toBe('KXBTC-25MAY26-B105');
		expect(humanizeTicker('')).toBe('');
	});

	it('keeps unknown city codes readable', () => {
		expect(humanizeTicker('KXHIGHXYZ-25MAY26-T80')).toBe('XYZ high ≥ 80°F · May 26');
	});
});

describe('outcomeLabel', () => {
	it('maps known outcomes to plain language', () => {
		expect(outcomeLabel('order_placed')).toBe('order placed');
		expect(outcomeLabel('rejected_below_threshold')).toBe('skipped · edge below threshold');
		expect(outcomeLabel('rejected_kelly_zero')).toBe('skipped · Kelly sized to zero');
		expect(outcomeLabel('rejected_below_min_position')).toBe('skipped · below min position');
		expect(outcomeLabel('rejected_exposure_cap')).toBe('skipped · exposure cap');
		expect(outcomeLabel('rejected_correlation_cap')).toBe('skipped · correlation cap');
		expect(outcomeLabel('rejected_market_closed')).toBe('skipped · market closed');
		expect(outcomeLabel('rejected_stale_inputs')).toBe('blocked · stale inputs');
		expect(outcomeLabel('rejected_system_paused')).toBe('blocked · kill switch');
	});

	it('falls back to de-underscored text', () => {
		expect(outcomeLabel('unknown_outcome')).toBe('unknown outcome');
		expect(outcomeLabel('rejected_future_reason')).toBe('rejected future reason');
	});
});

describe('outcomeTone', () => {
	it('classifies outcomes for styling', () => {
		expect(outcomeTone('order_placed')).toBe('placed');
		expect(outcomeTone('rejected_below_threshold')).toBe('skip');
		expect(outcomeTone('rejected_kelly_zero')).toBe('skip');
		expect(outcomeTone('rejected_stale_inputs')).toBe('block');
		expect(outcomeTone('rejected_system_paused')).toBe('block');
		expect(outcomeTone('unknown_outcome')).toBe('block');
	});
});

describe('strategyVerdict', () => {
	it('calls a proven edge', () => {
		expect(strategyVerdict(active(), evalEntry({}))).toMatch(/proven/i);
	});

	it('calls out a drawdown pause with the configured stop', () => {
		const verdict = strategyVerdict({ ...active(), state: 'drawdown_paused' }, evalEntry({}));
		expect(verdict).toMatch(/drawdown/i);
		expect(verdict).toMatch(/12/);
	});

	it('calls out a low-bankroll pause', () => {
		expect(strategyVerdict({ ...active(), state: 'low_bankroll_paused' }, null)).toMatch(
			/bankroll/i
		);
	});

	it('says needs-more-data when CI straddles zero', () => {
		expect(
			strategyVerdict(active(), evalEntry({ nTrades: 87, posteriorEdgeCiLow: -0.011 }))
		).toMatch(/not yet proven/i);
	});

	it('handles missing eval data', () => {
		expect(strategyVerdict(active(), null)).toMatch(/no resolved trades/i);
	});
});
