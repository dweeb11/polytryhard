import { get } from 'svelte/store';
import {
	audit,
	bankrollHistoryByStrategy,
	cashEvents,
	persistCurrent,
	positions,
	resetToFixtures,
	signals,
	strategies,
	sources,
	plugins,
	system
} from './stores';
import { pushToast } from './stores/toasts';
import type {
	ActionResult,
	AuditEvent,
	CashEvent,
	Signal,
	SignalOutcome,
	StrategyInstance,
	StrategyState
} from './types';
import {
	RESUMABLE_STATES,
	PAUSABLE_STATES,
	clamp,
	freeCashCents,
	nowIso,
	uuid
} from './utils';

function toastResult(result: ActionResult, successMsg: string): ActionResult {
	if (result.ok) {
		pushToast('success', successMsg);
		persistCurrent();
	} else {
		pushToast('error', result.reason);
	}
	return result;
}

function isSystemPaused(): boolean {
	return get(system).state === 'paused';
}

function findStrategy(name: string): StrategyInstance | undefined {
	return get(strategies).find((s) => s.name === name);
}

function appendAudit(
	action: string,
	targetType: string,
	targetId: string,
	beforeState: Record<string, unknown>,
	afterState: Record<string, unknown>,
	reason: string,
	actor: AuditEvent['actor'] = 'user'
): void {
	const event: AuditEvent = {
		id: uuid(),
		occurredAt: nowIso(),
		actor,
		action,
		targetType,
		targetId,
		beforeState,
		afterState,
		reason,
		requestId: uuid()
	};
	audit.update((a) => [event, ...a]);
}

function appendCashEvent(
	strategyName: string,
	kind: CashEvent['kind'],
	amountCents: number,
	balanceAfter: number,
	reason: string,
	refPositionId: string | null = null
): void {
	cashEvents.update((events) => [
		{
			id: uuid(),
			strategyName,
			occurredAt: nowIso(),
			kind,
			amountCents,
			balanceAfterCents: balanceAfter,
			reason,
			refPositionId
		},
		...events
	]);
}

function updateStrategy(name: string, patch: Partial<StrategyInstance>): void {
	strategies.update((list) =>
		list.map((s) => (s.name === name ? { ...s, ...patch, lastStateChangeAt: nowIso() } : s))
	);
}

function bumpBankrollHistory(name: string, bankrollCents: number): void {
	bankrollHistoryByStrategy.update((hist) => {
		const points = hist[name] ?? [];
		return {
			...hist,
			[name]: [...points.slice(-29), { at: nowIso(), bankrollCents }]
		};
	});
}

export function deposit(
	strategyName: string,
	amountCents: number,
	reason: string
): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	if (strat.state === 'decommissioned')
		return toastResult({ ok: false, reason: 'Cannot deposit to decommissioned strategy' }, '');
	if (amountCents <= 0) return toastResult({ ok: false, reason: 'Amount must be positive' }, '');

	const before = { bankrollCents: strat.bankrollCents, state: strat.state };
	const newBankroll = strat.bankrollCents + amountCents;
	let newState: StrategyState = strat.state;
	if (
		strat.config.autoResumeOnDeposit &&
		RESUMABLE_STATES.includes(strat.state as (typeof RESUMABLE_STATES)[number]) &&
		newBankroll >= strat.config.minBankrollCents
	) {
		newState = 'active';
	}

	updateStrategy(strategyName, {
		bankrollCents: newBankroll,
		state: newState
	});
	appendCashEvent(strategyName, 'deposit', amountCents, newBankroll, reason);
	appendAudit('deposit', 'strategy', strategyName, before, {
		bankrollCents: newBankroll,
		state: newState
	}, reason);
	bumpBankrollHistory(strategyName, newBankroll);
	return toastResult({ ok: true }, `Deposited $${(amountCents / 100).toFixed(2)} to ${strategyName}`);
}

export function withdraw(
	strategyName: string,
	amountCents: number,
	reason: string
): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	if (amountCents <= 0) return toastResult({ ok: false, reason: 'Amount must be positive' }, '');

	const free = freeCashCents(strat, get(positions));
	if (amountCents > free) {
		return toastResult(
			{ ok: false, reason: `Withdrawal exceeds free cash (${(free / 100).toFixed(2)} available)` },
			''
		);
	}

	const before = { bankrollCents: strat.bankrollCents };
	const newBankroll = strat.bankrollCents - amountCents;
	updateStrategy(strategyName, { bankrollCents: newBankroll });
	appendCashEvent(strategyName, 'withdraw', -amountCents, newBankroll, reason);
	appendAudit('withdraw', 'strategy', strategyName, before, { bankrollCents: newBankroll }, reason);
	bumpBankrollHistory(strategyName, newBankroll);
	return toastResult({ ok: true }, `Withdrew $${(amountCents / 100).toFixed(2)} from ${strategyName}`);
}

export function pauseStrategy(strategyName: string, reason: string): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	if (!PAUSABLE_STATES.includes(strat.state as (typeof PAUSABLE_STATES)[number])) {
		return toastResult(
			{ ok: false, reason: `Cannot pause from state ${strat.state.replace(/_/g, ' ')}` },
			''
		);
	}
	const before = { state: strat.state };
	updateStrategy(strategyName, {
		state: 'operator_paused'
	});
	appendAudit('pause_strategy', 'strategy', strategyName, before, { state: 'operator_paused' }, reason);
	return toastResult({ ok: true }, `Paused ${strategyName}`);
}

export function resumeStrategy(strategyName: string, reason: string): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	if (!RESUMABLE_STATES.includes(strat.state as (typeof RESUMABLE_STATES)[number])) {
		return toastResult({ ok: false, reason: `Cannot resume from state ${strat.state}` }, '');
	}
	const before = { state: strat.state };
	updateStrategy(strategyName, { state: 'active' });
	appendAudit('resume_strategy', 'strategy', strategyName, before, { state: 'active' }, reason);
	return toastResult({ ok: true }, `Resumed ${strategyName} → active`);
}

export function setKellyFraction(
	strategyName: string,
	fraction: number,
	reason: string
): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	if (strat.state === 'decommissioned')
		return toastResult({ ok: false, reason: 'Strategy is decommissioned' }, '');
	const value = clamp(fraction, 0, 1);
	const before = { kellyFraction: strat.kellyFraction };
	updateStrategy(strategyName, { kellyFraction: value });
	appendAudit(
		'set_kelly_fraction',
		'strategy',
		strategyName,
		before,
		{ kellyFraction: value },
		reason
	);
	return toastResult({ ok: true }, `Kelly fraction set to ${(value * 100).toFixed(1)}%`);
}

export function forceCloseAndWithdraw(strategyName: string, reason: string): ActionResult {
	if (isSystemPaused()) return toastResult({ ok: false, reason: 'System kill switch is active' }, '');
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	const open = get(positions).filter(
		(p) => p.strategyName === strategyName && p.status === 'open'
	);
	let bankroll = strat.bankrollCents;
	for (const pos of open) {
		const pnl = pos.unrealizedPnlCents;
		bankroll += pnl;
		appendCashEvent(strategyName, 'realized_pnl', pnl, bankroll, `close ${pos.ticker}`, pos.id);
	}
	positions.update((list) =>
		list.map((p) =>
			p.strategyName === strategyName && p.status === 'open'
				? {
						...p,
						status: 'closed' as const,
						closedAt: nowIso(),
						realizedPnlCents: p.unrealizedPnlCents,
						unrealizedPnlCents: 0
					}
				: p
		)
	);
	const before = { bankrollCents: strat.bankrollCents, openPositions: open.length };
	updateStrategy(strategyName, { bankrollCents: bankroll });
	appendAudit(
		'force_close_and_withdraw',
		'strategy',
		strategyName,
		before,
		{ bankrollCents: bankroll, openPositions: 0 },
		reason
	);
	bumpBankrollHistory(strategyName, bankroll);
	return toastResult(
		{ ok: true },
		`Closed ${open.length} position(s); bankroll now $${(bankroll / 100).toFixed(2)} (withdraw when ready)`
	);
}

export function decommission(strategyName: string, reason: string): ActionResult {
	const strat = findStrategy(strategyName);
	if (!strat) return toastResult({ ok: false, reason: 'Strategy not found' }, '');
	const before = { state: strat.state };
	updateStrategy(strategyName, { state: 'decommissioned', enabled: false });
	appendAudit('decommission', 'strategy', strategyName, before, { state: 'decommissioned' }, reason);
	return toastResult({ ok: true }, `${strategyName} decommissioned`);
}

export function tripKillSwitch(reason: string): ActionResult {
	if (!reason.trim()) return toastResult({ ok: false, reason: 'Reason is required' }, '');
	const before = { ...get(system) };
	system.set({
		state: 'paused',
		killSwitchReason: reason,
		killSwitchTrippedAt: nowIso()
	});
	appendAudit('trip_kill_switch', 'system', 'global', before, { ...get(system) }, reason);
	return toastResult({ ok: true }, 'Kill switch tripped — executors blocked');
}

export function resumeKillSwitch(reason: string): ActionResult {
	if (!reason.trim()) return toastResult({ ok: false, reason: 'Reason is required to resume' }, '');
	const before = { ...get(system) };
	system.set({
		state: 'active',
		killSwitchReason: null,
		killSwitchTrippedAt: null
	});
	appendAudit('resume_kill_switch', 'system', 'global', before, { ...get(system) }, reason);
	return toastResult({ ok: true }, 'Kill switch cleared — system active');
}

export function togglePlugin(pluginId: string, enabled: boolean, reason = 'operator toggle'): ActionResult {
	const plugin = get(plugins).find((p) => p.id === pluginId);
	if (!plugin) return toastResult({ ok: false, reason: 'Plugin not found' }, '');
	const before = { enabled: plugin.enabled };
	plugins.update((list) =>
		list.map((p) =>
			p.id === pluginId ? { ...p, enabled, lastToggledAt: nowIso() } : p
		)
	);
	appendAudit('toggle_plugin', 'plugin', pluginId, before, { enabled }, reason);
	return toastResult(
		{ ok: true },
		`${plugin.name} ${enabled ? 'enabled' : 'disabled'}`
	);
}

export function probeSource(sourceName: string): ActionResult {
	const src = get(sources).find((s) => s.name === sourceName);
	if (!src) return toastResult({ ok: false, reason: 'Source not found' }, '');
	const success = Math.random() < 0.7;
	const before = { ...src };
	if (success) {
		sources.update((list) =>
			list.map((s) =>
				s.name === sourceName
					? {
							...s,
							state: 'healthy',
							lastSuccessfulFetch: nowIso(),
							lastError: null
						}
					: s
			)
		);
		const after = get(sources).find((s) => s.name === sourceName)!;
		appendAudit('probe_source', 'source', sourceName, { ...before }, { ...after }, 'probe success');
		return toastResult({ ok: true }, `${src.displayName}: probe succeeded`);
	}
	sources.update((list) =>
		list.map((s) =>
			s.name === sourceName
				? {
						...s,
						state: 'degraded',
						lastError: 'probe failed (simulated)'
					}
				: s
		)
	);
	const afterFail = get(sources).find((s) => s.name === sourceName)!;
	appendAudit('probe_source', 'source', sourceName, { ...before }, { ...afterFail }, 'probe failed');
	return toastResult({ ok: false, reason: `${src.displayName}: probe failed (simulated)` }, '');
}

export function resetPrototype(reason = 'operator reset'): ActionResult {
	resetToFixtures();
	pushToast('info', 'Prototype reset to fixtures');
	persistCurrent();
	appendAudit('reset_prototype', 'system', 'global', {}, {}, reason);
	return { ok: true };
}

/** Emit a simulated signal through the same path as tick */
export function emitSignal(signal: Omit<Signal, 'id'>): void {
	const full: Signal = { ...signal, id: uuid() };
	signals.update((s) => [full, ...s].slice(0, 200));
}

export function canEmitSignals(strategyName: string): boolean {
	const strat = findStrategy(strategyName);
	if (!strat || !strat.enabled || strat.state === 'decommissioned') return false;
	const pausedStates: StrategyState[] = [
		'low_bankroll_paused',
		'drawdown_paused',
		'operator_paused'
	];
	if (pausedStates.includes(strat.state)) return false;
	return true;
}

export function resolveSignalOutcome(strategyName: string): SignalOutcome {
	if (isSystemPaused()) return 'rejected_system_paused';
	const strat = findStrategy(strategyName);
	if (!strat) return 'rejected_below_threshold';
	const pausedStates: StrategyState[] = [
		'low_bankroll_paused',
		'drawdown_paused',
		'operator_paused'
	];
	if (pausedStates.includes(strat.state)) return 'rejected_system_paused';
	if (strat.kellyFraction <= 0) return 'rejected_kelly_zero';
	return Math.random() > 0.35 ? 'order_placed' : 'rejected_below_threshold';
}
