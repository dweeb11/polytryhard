import type { StrategyConfig } from './types';
import { formatCents } from './utils';

export type ConfigRow = [label: string, value: string];

function formatConfigNumber(value: number | null | undefined, decimals = 2): string {
	return value == null ? '—' : value.toFixed(decimals);
}

function formatConfigPct(value: number | null | undefined): string {
	return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

function formatInputAge(seconds: number): string {
	return seconds >= 120 ? `${Math.round(seconds / 60)} min` : `${seconds} s`;
}

export function strategyBaselineConfigRows(config: StrategyConfig): ConfigRow[] {
	return [
		['Pause if bankroll drops below', formatCents(config.minBankrollCents)],
		['Stop opening trades below', formatCents(config.minTradeableBankrollCents)],
		['Stop trading at drawdown', `${config.maxDrawdownPctFromHwm.toFixed(1)}% from HWM`],
		['Ignore inputs older than', formatInputAge(config.maxInputAgeSeconds)],
		['Auto-resume on deposit', config.autoResumeOnDeposit ? 'yes' : 'no']
	];
}

const SOAK_ROWS_BY_STRATEGY: Record<string, Array<(config: StrategyConfig) => ConfigRow>> = {
	weather_ensemble_disagreement: [
		(config) => ['Only trade when confidence ≥', formatConfigPct(config.confidenceFloor)],
		(config) => [
			'Require model disagreement of',
			config.disagreementThreshold == null
				? '—'
				: `${formatConfigNumber(config.disagreementThreshold, 1)}°`
		],
		(config) => ['Spread margin multiplier', formatConfigNumber(config.spreadMarginMultiplier, 1)],
		(config) => ['Max exposure per market', formatConfigPct(config.exposureCapPct)],
		(config) => ['Max correlated exposure', formatConfigPct(config.correlationCapPct)]
	],
	weather_stale_quote: [
		(config) => ['Only trade when confidence ≥', formatConfigPct(config.confidenceFloor)],
		(config) => ['Treat spreads as wide above', formatConfigPct(config.wideSpreadThreshold)],
		(config) => ['Max exposure per market', formatConfigPct(config.exposureCapPct)],
		(config) => ['Max correlated exposure', formatConfigPct(config.correlationCapPct)]
	]
};

const SHARED_SOAK_ROWS: Array<(config: StrategyConfig) => ConfigRow> = [
	(config) => ['Only trade when confidence ≥', formatConfigPct(config.confidenceFloor)],
	(config) => ['Max exposure per market', formatConfigPct(config.exposureCapPct)],
	(config) => ['Max correlated exposure', formatConfigPct(config.correlationCapPct)]
];

export function strategySoakConfigRows(strategyName: string, config: StrategyConfig): ConfigRow[] {
	const builders = SOAK_ROWS_BY_STRATEGY[strategyName] ?? SHARED_SOAK_ROWS;
	return builders.map((build) => build(config));
}
