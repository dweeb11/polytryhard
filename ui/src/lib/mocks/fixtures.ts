import type { EnvSnapshot } from '$lib/types';
import { uuid } from '$lib/utils';

const defaultConfig = {
	minBankrollCents: 10_000,
	minTradeableBankrollCents: 5_000,
	maxDrawdownPctFromHwm: 30,
	autoResumeOnDeposit: true,
	maxInputAgeSeconds: 900
};

function hoursAgo(h: number): string {
	return new Date(Date.now() - h * 3600_000).toISOString();
}

function calibrationBuckets(): EnvSnapshot['calibration'][string] {
	return Array.from({ length: 10 }, (_, i) => {
		const mid = (i + 0.5) / 10;
		return {
			bucket: i,
			predicted: mid,
			actual: mid + (Math.random() - 0.5) * 0.08,
			count: 4 + i * 2
		};
	});
}

function bankrollHistory(base: number): EnvSnapshot['bankrollHistory'][string] {
	const pts: EnvSnapshot['bankrollHistory'][string] = [];
	for (let i = 14; i >= 0; i--) {
		pts.push({
			at: hoursAgo(i * 8),
			bankrollCents: base + Math.round((14 - i) * 1200 + (Math.random() - 0.5) * 3000)
		});
	}
	return pts;
}

function makeSignals(
	strategyNames: string[],
	count: number
): EnvSnapshot['signals'] {
	const outcomes = [
		'order_placed',
		'rejected_kelly_zero',
		'rejected_below_threshold',
		'rejected_exposure_cap',
		'rejected_stale_inputs'
	] as const;
	const tickers = ['KXHIGHNY-25MAY26-T72', 'KXHIGHCHI-25MAY26-T68', 'KXHIGHLAX-25MAY26-T75'];
	const signals: EnvSnapshot['signals'] = [];
	for (let i = 0; i < count; i++) {
		const strategy = strategyNames[i % strategyNames.length];
		const outcome = outcomes[i % outcomes.length];
		signals.push({
			id: uuid(),
			strategyName: strategy,
			ticker: tickers[i % tickers.length],
			evaluatedAt: hoursAgo(i * 0.4),
			probYes: 0.35 + (i % 7) * 0.08,
			confidence: 0.55 + (i % 5) * 0.07,
			outcome,
			rejectionReason: outcome === 'order_placed' ? null : `simulated ${outcome}`
		});
	}
	return signals.sort(
		(a, b) => new Date(b.evaluatedAt).getTime() - new Date(a.evaluatedAt).getTime()
	);
}

function basePlugins(): EnvSnapshot['plugins'] {
	const ts = hoursAgo(48);
	return [
		{
			id: 'source-kalshi_markets',
			type: 'source',
			name: 'kalshi_markets',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'source-nws_forecast',
			type: 'source',
			name: 'nws_forecast',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'source-gfs_ensemble',
			type: 'source',
			name: 'gfs_ensemble',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'source-ecmwf_open_meteo',
			type: 'source',
			name: 'ecmwf_open_meteo',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'feature-ensemble_mean_temp',
			type: 'feature_provider',
			name: 'ensemble_mean_temp',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'feature-forecast_disagreement',
			type: 'feature_provider',
			name: 'forecast_disagreement',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'strategy-weather_ensemble_disagreement',
			type: 'strategy',
			name: 'weather_ensemble_disagreement',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'strategy-weather_stale_quote',
			type: 'strategy',
			name: 'weather_stale_quote',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'strategy-weather_baseline_v2',
			type: 'strategy',
			name: 'weather_baseline_v2',
			version: '2.0.0',
			enabled: true,
			lastToggledAt: ts
		},
		{
			id: 'executor-paper',
			type: 'executor',
			name: 'paper',
			version: '1.0.0',
			enabled: true,
			lastToggledAt: ts
		}
	];
}

function seedFixture(): EnvSnapshot {
	const strategies = [
		{
			name: 'weather_ensemble_disagreement',
			enabled: true,
			state: 'active' as const,
			bankrollCents: 125_000,
			bankrollHwmCents: 140_000,
			initialDepositCents: 100_000,
			kellyFraction: 0.25,
			config: defaultConfig,
			lastStateChangeAt: hoursAgo(72),
			todayPnlCents: 2_400
		},
		{
			name: 'weather_stale_quote',
			enabled: true,
			state: 'drawdown_paused' as const,
			bankrollCents: 68_000,
			bankrollHwmCents: 100_000,
			initialDepositCents: 80_000,
			kellyFraction: 0.2,
			config: defaultConfig,
			lastStateChangeAt: hoursAgo(12),
			todayPnlCents: -1_100
		},
		{
			name: 'weather_baseline_v2',
			enabled: true,
			state: 'operator_paused' as const,
			bankrollCents: 210_000,
			bankrollHwmCents: 220_000,
			initialDepositCents: 150_000,
			kellyFraction: 0.15,
			config: defaultConfig,
			lastStateChangeAt: hoursAgo(6),
			todayPnlCents: 800
		}
	];

	const names = strategies.map((s) => s.name);

	return {
		strategies,
		signals: makeSignals(names, 52),
		sources: [
			{
				name: 'kalshi_markets',
				displayName: 'Kalshi Markets (WS)',
				state: 'healthy',
				lastSuccessfulFetch: hoursAgo(0.01),
				lastError: null
			},
			{
				name: 'nws_forecast',
				displayName: 'NOAA NWS',
				state: 'healthy',
				lastSuccessfulFetch: hoursAgo(0.5),
				lastError: null
			},
			{
				name: 'gfs_ensemble',
				displayName: 'GFS Ensemble',
				state: 'degraded',
				lastSuccessfulFetch: hoursAgo(2.5),
				lastError: 'HTTP 503 from Open-Meteo'
			},
			{
				name: 'ecmwf_open_meteo',
				displayName: 'ECMWF (Open-Meteo)',
				state: 'down',
				lastSuccessfulFetch: hoursAgo(6),
				lastError: 'Connection timeout after 30s'
			}
		],
		plugins: basePlugins(),
		audit: Array.from({ length: 20 }, (_, i) => ({
			id: uuid(),
			occurredAt: hoursAgo(i * 3 + 1),
			actor: i % 4 === 0 ? ('scheduler' as const) : ('user' as const),
			action: ['deposit', 'pause_strategy', 'probe_source', 'toggle_plugin'][i % 4],
			targetType: ['strategy', 'source', 'plugin'][i % 3],
			targetId: names[i % names.length],
			beforeState: { state: 'active' },
			afterState: { state: i % 2 ? 'operator_paused' : 'active' },
			reason: 'fixture seed event',
			requestId: uuid()
		})),
		cashEvents: [
			{
				id: uuid(),
				strategyName: 'weather_ensemble_disagreement',
				occurredAt: hoursAgo(72),
				kind: 'deposit',
				amountCents: 100_000,
				balanceAfterCents: 100_000,
				reason: 'initial seed',
				refPositionId: null
			},
			{
				id: uuid(),
				strategyName: 'weather_ensemble_disagreement',
				occurredAt: hoursAgo(24),
				kind: 'realized_pnl',
				amountCents: 25_000,
				balanceAfterCents: 125_000,
				reason: 'closed position',
				refPositionId: null
			}
		],
		positions: [
			{
				id: uuid(),
				strategyName: 'weather_ensemble_disagreement',
				ticker: 'KXHIGHNY-25MAY26-T72',
				side: 'yes',
				openedAt: hoursAgo(4),
				closedAt: null,
				openAvgPrice: 0.42,
				qty: 50,
				costBasisCents: 21_000,
				realizedPnlCents: null,
				unrealizedPnlCents: 1_200,
				status: 'open'
			},
			{
				id: uuid(),
				strategyName: 'weather_stale_quote',
				ticker: 'KXHIGHCHI-25MAY26-T68',
				side: 'no',
				openedAt: hoursAgo(8),
				closedAt: null,
				openAvgPrice: 0.38,
				qty: 30,
				costBasisCents: 11_400,
				realizedPnlCents: null,
				unrealizedPnlCents: -400,
				status: 'open'
			}
		],
		system: { state: 'active', killSwitchReason: null, killSwitchTrippedAt: null },
		calibration: Object.fromEntries(names.map((n) => [n, calibrationBuckets()])),
		bankrollHistory: Object.fromEntries(
			strategies.map((s) => [s.name, bankrollHistory(s.bankrollCents)])
		)
	};
}

export function createFixtureSnapshot(): EnvSnapshot {
	return structuredClone(seedFixture());
}

export function strategyEntries(): string[] {
	return seedFixture().strategies.map((s) => s.name);
}

export const FIXTURE: EnvSnapshot = createFixtureSnapshot();
