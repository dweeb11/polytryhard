// Hand-written types for mock-only and UI view models. API-aligned shapes are
// re-exported from OpenAPI schemas via $lib/api/schemas.ts.

import type {
	ApiAuditEvent,
	ApiCashEvent,
	ApiCashEventKind,
	ApiEvalRosterEntry,
	ApiEvalSnapshot,
	ApiPositionSide,
	ApiSignalOutcome,
	ApiStrategyInstance,
	ApiStrategyState,
	ApiSystemEnvState,
	ApiSystemState
} from '$lib/api/schemas';

export type AuditEvent = ApiAuditEvent;
export type CashEvent = ApiCashEvent;
export type CashEventKind = ApiCashEventKind;
export type EvalRosterEntryView = ApiEvalRosterEntry;
export type EvalSnapshotView = ApiEvalSnapshot;
export type PositionSide = ApiPositionSide;
export type StrategyInstance = ApiStrategyInstance;
export type StrategyState = ApiStrategyState;
export type SystemEnvState = ApiSystemEnvState;
export type SystemState = ApiSystemState;

/** API-known outcomes; keep in sync with OpenAPI `SignalOutcome`. */
export const KNOWN_SIGNAL_OUTCOMES = [
	'order_placed',
	'rejected_kelly_zero',
	'rejected_exposure_cap',
	'rejected_correlation_cap',
	'rejected_below_threshold',
	'rejected_below_min_position',
	'rejected_market_closed',
	'rejected_stale_inputs',
	'rejected_system_paused'
] as const satisfies readonly ApiSignalOutcome[];

export type KnownSignalOutcome = (typeof KNOWN_SIGNAL_OUTCOMES)[number];

/** Includes UI-only fallback when the API sends an unrecognized outcome string. */
export type SignalOutcome = KnownSignalOutcome | 'unknown_outcome';

export type PluginType =
	| 'source'
	| 'feature_provider'
	| 'strategy'
	| 'executor'
	| 'rubric';

export type SourceState = 'healthy' | 'degraded' | 'down';
export type PositionStatus = 'open' | 'closed' | 'resolved';

export interface StrategyConfig {
	minBankrollCents: number;
	minTradeableBankrollCents: number;
	maxDrawdownPctFromHwm: number;
	autoResumeOnDeposit: boolean;
	maxInputAgeSeconds: number;
	confidenceFloor?: number | null;
	disagreementThreshold?: number | null;
	spreadMarginMultiplier?: number | null;
	wideSpreadThreshold?: number | null;
	exposureCapPct?: number | null;
	correlationCapPct?: number | null;
}

export interface Signal {
	id: string;
	strategyName: string;
	ticker: string;
	evaluatedAt: string;
	probYes: number;
	confidence: number;
	outcome: SignalOutcome;
	rejectionReason: string | null;
}

export interface SourceHealth {
	name: string;
	displayName: string;
	state: SourceState;
	lastSuccessfulFetch: string;
	lastError: string | null;
}

export interface Plugin {
	id: string;
	type: PluginType;
	name: string;
	version: string;
	enabled: boolean;
	lastToggledAt: string;
}

export interface PaperPosition {
	id: string;
	strategyName: string;
	ticker: string;
	side: PositionSide;
	openedAt: string;
	closedAt: string | null;
	openAvgPrice: number;
	qty: number;
	costBasisCents: number;
	realizedPnlCents: number | null;
	unrealizedPnlCents: number | null;
	status: PositionStatus;
}

export interface CalibrationBucket {
	bucket: number;
	predicted: number;
	actual: number;
	count: number;
}

export interface BankrollPoint {
	at: string;
	bankrollCents: number;
}

export interface EnvSnapshot {
	strategies: StrategyInstance[];
	signals: Signal[];
	sources: SourceHealth[];
	plugins: Plugin[];
	audit: AuditEvent[];
	cashEvents: CashEvent[];
	positions: PaperPosition[];
	system: SystemEnvState;
	calibration: Record<string, CalibrationBucket[]>;
	bankrollHistory: Record<string, BankrollPoint[]>;
}

export type ActionResult<T = Record<string, unknown>> =
	| { ok: true; data?: T }
	| { ok: false; reason: string };

export interface Toast {
	id: string;
	type: 'success' | 'error' | 'info';
	message: string;
	createdAt: number;
}
