import type { StrategyConfig } from './types';
import { formatCents } from './utils';

export type ConfigRow = [label: string, value: string];

function formatConfigNumber(value: number | null | undefined, decimals = 2): string {
	return value == null ? '—' : value.toFixed(decimals);
}

function formatConfigPct(value: number | null | undefined): string {
	return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export function strategyBaselineConfigRows(config: StrategyConfig): ConfigRow[] {
	return [
		['Min bankroll', formatCents(config.minBankrollCents)],
		['Tradeable floor', formatCents(config.minTradeableBankrollCents)],
		['Max drawdown from HWM', `${config.maxDrawdownPctFromHwm.toFixed(1)}%`],
		['Max input age', `${config.maxInputAgeSeconds}s`]
	];
}

const SOAK_ROWS_BY_STRATEGY: Record<string, Array<(config: StrategyConfig) => ConfigRow>> = {
	weather_ensemble_disagreement: [
		(config) => ['Confidence floor', formatConfigPct(config.confidenceFloor)],
		(config) => ['Disagreement threshold', formatConfigNumber(config.disagreementThreshold, 1)],
		(config) => ['Spread multiplier', formatConfigNumber(config.spreadMarginMultiplier, 1)],
		(config) => ['Exposure cap', formatConfigPct(config.exposureCapPct)],
		(config) => ['Correlation cap', formatConfigPct(config.correlationCapPct)]
	],
	weather_stale_quote: [
		(config) => ['Confidence floor', formatConfigPct(config.confidenceFloor)],
		(config) => ['Wide spread threshold', formatConfigPct(config.wideSpreadThreshold)],
		(config) => ['Exposure cap', formatConfigPct(config.exposureCapPct)],
		(config) => ['Correlation cap', formatConfigPct(config.correlationCapPct)]
	]
};

const SHARED_SOAK_ROWS: Array<(config: StrategyConfig) => ConfigRow> = [
	(config) => ['Confidence floor', formatConfigPct(config.confidenceFloor)],
	(config) => ['Exposure cap', formatConfigPct(config.exposureCapPct)],
	(config) => ['Correlation cap', formatConfigPct(config.correlationCapPct)]
];

export function strategySoakConfigRows(strategyName: string, config: StrategyConfig): ConfigRow[] {
	const builders = SOAK_ROWS_BY_STRATEGY[strategyName] ?? SHARED_SOAK_ROWS;
	return builders.map((build) => build(config));
}
