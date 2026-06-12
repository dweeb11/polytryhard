import { describe, expect, it } from 'vitest';
import {
	strategyBaselineConfigRows,
	strategySoakConfigRows
} from '../strategyConfigDisplay';
import type { StrategyConfig } from '../types';

const baseConfig: StrategyConfig = {
	minBankrollCents: 10_000,
	minTradeableBankrollCents: 5_000,
	maxDrawdownPctFromHwm: 30,
	autoResumeOnDeposit: true,
	maxInputAgeSeconds: 900,
	confidenceFloor: 0.55,
	exposureCapPct: 0.1,
	correlationCapPct: 0.05
};

describe('strategyConfigDisplay', () => {
	it('renders baseline rules as plain-english rows', () => {
		const rows = strategyBaselineConfigRows(baseConfig);
		expect(rows).toEqual([
			['Pause if bankroll drops below', '$100.00'],
			['Stop opening trades below', '$50.00'],
			['Stop trading at drawdown', '30.0% from HWM'],
			['Ignore inputs older than', '15 min'],
			['Auto-resume on deposit', 'yes']
		]);
	});

	it('formats sub-2-minute input ages in seconds', () => {
		const rows = strategyBaselineConfigRows({ ...baseConfig, maxInputAgeSeconds: 90 });
		expect(rows).toContainEqual(['Ignore inputs older than', '90 s']);
	});

	it('renders ensemble-specific soak rows', () => {
		const config = {
			...baseConfig,
			disagreementThreshold: 2.0,
			spreadMarginMultiplier: 1.5
		};
		const rows = strategySoakConfigRows('weather_ensemble_disagreement', config);
		expect(rows.map(([label]) => label)).toEqual([
			'Only trade when confidence ≥',
			'Require model disagreement of',
			'Spread margin multiplier',
			'Max exposure per market',
			'Max correlated exposure'
		]);
		expect(rows[0][1]).toBe('55.0%');
	});

	it('renders stale-quote-specific soak rows', () => {
		const config = { ...baseConfig, wideSpreadThreshold: 0.08 };
		const rows = strategySoakConfigRows('weather_stale_quote', config);
		expect(rows.map(([label]) => label)).toEqual([
			'Only trade when confidence ≥',
			'Treat spreads as wide above',
			'Max exposure per market',
			'Max correlated exposure'
		]);
	});
});
