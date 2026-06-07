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
	it('renders baseline rows without soak knobs', () => {
		const rows = strategyBaselineConfigRows(baseConfig);
		expect(rows.map(([label]) => label)).toEqual([
			'Min bankroll',
			'Tradeable floor',
			'Max drawdown from HWM',
			'Max input age'
		]);
	});

	it('renders ensemble-specific soak rows', () => {
		const config = {
			...baseConfig,
			disagreementThreshold: 2.0,
			spreadMarginMultiplier: 1.5
		};
		const rows = strategySoakConfigRows('weather_ensemble_disagreement', config);
		expect(rows.map(([label]) => label)).toEqual([
			'Confidence floor',
			'Disagreement threshold',
			'Spread multiplier',
			'Exposure cap',
			'Correlation cap'
		]);
	});

	it('renders stale-quote-specific soak rows', () => {
		const config = { ...baseConfig, wideSpreadThreshold: 0.08 };
		const rows = strategySoakConfigRows('weather_stale_quote', config);
		expect(rows.map(([label]) => label)).toEqual([
			'Confidence floor',
			'Wide spread threshold',
			'Exposure cap',
			'Correlation cap'
		]);
	});
});
