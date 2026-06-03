// Hand-written prototype types. From M2 these will be generated from the FastAPI OpenAPI schema;
// do not add fields here that should originate in Pydantic.

export type SystemState = 'active' | 'paused';

export type StrategyState =
	| 'seeded'
	| 'active'
	| 'low_bankroll_paused'
	| 'drawdown_paused'
	| 'operator_paused'
	| 'decommissioned';

/** API-known outcomes; keep in sync with OpenAPI `SignalOutcome` until types are generated. */
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
] as const;

export type KnownSignalOutcome = (typeof KNOWN_SIGNAL_OUTCOMES)[number];

/** Includes UI-only fallback when the API sends an unrecognized outcome string. */
export type SignalOutcome = KnownSignalOutcome | 'unknown_outcome';

export type CashEventKind =
	| 'deposit'
	| 'withdraw'
	| 'realized_pnl'
	| 'fee'
	| 'transfer_in'
	| 'transfer_out';

export type PluginType =
	| 'source'
	| 'feature_provider'
	| 'strategy'
	| 'executor'
	| 'rubric';

export type SourceState = 'healthy' | 'degraded' | 'down';
export type PositionStatus = 'open' | 'closed' | 'resolved';
export type PositionSide = 'yes' | 'no';

export interface StrategyConfig {
	minBankrollCents: number;
	minTradeableBankrollCents: number;
	maxDrawdownPctFromHwm: number;
	autoResumeOnDeposit: boolean;
	maxInputAgeSeconds: number;
}

export interface StrategyInstance {
	name: string;
	enabled: boolean;
	state: StrategyState;
	bankrollCents: number;
	bankrollHwmCents: number;
	initialDepositCents: number;
	kellyFraction: number;
	config: StrategyConfig;
	lastStateChangeAt: string;
	todayPnlCents: number;
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

export interface CashEvent {
	id: string;
	strategyName: string;
	occurredAt: string;
	kind: CashEventKind;
	amountCents: number;
	balanceAfterCents: number;
	reason: string;
	refPositionId: string | null;
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

export interface AuditEvent {
	id: string;
	occurredAt: string;
	actor: 'user' | 'system' | 'scheduler';
	action: string;
	targetType: string;
	targetId: string;
	beforeState: Record<string, unknown>;
	afterState: Record<string, unknown>;
	reason: string;
	requestId: string;
}

export interface SystemEnvState {
	state: SystemState;
	killSwitchReason: string | null;
	killSwitchTrippedAt: string | null;
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

export interface EvalSnapshotView {
	window: string;
	computedAt: string;
	nTrades: number;
	nWins: number;
	hitRate: number | null;
	brierScore: number | null;
	logLoss: number | null;
	pnlCents: number;
	sharpeProxy: number | null;
	maxDrawdownCents: number;
	posteriorEdgeMean: number;
	posteriorEdgeCiLow: number;
	posteriorEdgeCiHigh: number;
	calibrationBins: Array<{
		lower: number;
		upper: number;
		predictedMean: number;
		observedFreq: number;
		count: number;
	}>;
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
