import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import {
	deposit,
	withdraw,
	pauseStrategy,
	resumeStrategy,
	forceCloseAndWithdraw,
	tripKillSwitch,
	resumeKillSwitch,
	canEmitSignals,
	resolveSignalOutcome
} from '$lib/actions';
import {
	audit,
	cashEvents,
	positions,
	resetToFixtures,
	rehydrateFromStorage,
	strategies,
	system,
	bankrollHistoryByStrategy
} from '$lib/stores';
import { FIXTURE } from '$lib/mocks/fixtures';

const STRATEGY = 'weather_ensemble_disagreement';

function setupFixture(): void {
	localStorage.clear();
	resetToFixtures();
	system.set({ state: 'active', killSwitchReason: null, killSwitchTrippedAt: null });
}

function setStrategy(
	name: string,
	patch: Partial<(typeof FIXTURE.strategies)[number]>
): void {
	strategies.update((list) =>
		list.map((s) => (s.name === name ? { ...s, ...patch } : s))
	);
}

describe('deposit', () => {
	beforeEach(setupFixture);

	it('increments bankroll and writes cash_event, audit, and history', () => {
		const before = get(strategies).find((s) => s.name === STRATEGY)!;
		const result = deposit(STRATEGY, 5_000, 'test deposit');

		expect(result.ok).toBe(true);
		const after = get(strategies).find((s) => s.name === STRATEGY)!;
		expect(after.bankrollCents).toBe(before.bankrollCents + 5_000);
		expect(get(cashEvents)[0]).toMatchObject({
			strategyName: STRATEGY,
			kind: 'deposit',
			amountCents: 5_000
		});
		expect(get(audit)[0].action).toBe('deposit');
		const history = get(bankrollHistoryByStrategy)[STRATEGY] ?? [];
		expect(history.at(-1)?.bankrollCents).toBe(after.bankrollCents);
	});

	it('rejects non-positive amounts', () => {
		expect(deposit(STRATEGY, 0, 'zero').ok).toBe(false);
	});

	it('rejects when kill switch is active', () => {
		tripKillSwitch('halt');
		expect(deposit(STRATEGY, 1_000, 'blocked').ok).toBe(false);
	});

	it('rejects decommissioned strategies', () => {
		setStrategy(STRATEGY, { state: 'decommissioned' });
		expect(deposit(STRATEGY, 1_000, 'nope').ok).toBe(false);
	});

	it('auto-resumes low_bankroll_paused to active when crossing minBankrollCents', () => {
		setStrategy(STRATEGY, {
			state: 'low_bankroll_paused',
			bankrollCents: 5_000,
			config: { ...FIXTURE.strategies[0].config, autoResumeOnDeposit: true, minBankrollCents: 10_000 }
		});
		deposit(STRATEGY, 6_000, 'top up');
		const after = get(strategies).find((s) => s.name === STRATEGY)!;
		expect(after.state).toBe('active');
		expect(after.bankrollCents).toBe(11_000);
	});
});

describe('withdraw', () => {
	beforeEach(setupFixture);

	it('rejects when amount exceeds free cash with open positions', () => {
		const strat = get(strategies).find((s) => s.name === STRATEGY)!;
		const result = withdraw(STRATEGY, strat.bankrollCents, 'too much');
		expect(result.ok).toBe(false);
		expect(result.ok === false && result.reason).toContain('free cash');
	});

	it('rejects on kill switch', () => {
		tripKillSwitch('halt');
		expect(withdraw(STRATEGY, 100, 'blocked').ok).toBe(false);
	});

	it('writes negative cash_event on success', () => {
		const before = get(strategies).find((s) => s.name === STRATEGY)!;
		const result = withdraw(STRATEGY, 1_000, 'partial');
		expect(result.ok).toBe(true);
		expect(get(cashEvents)[0]).toMatchObject({ kind: 'withdraw', amountCents: -1_000 });
		const after = get(strategies).find((s) => s.name === STRATEGY)!;
		expect(after.bankrollCents).toBe(before.bankrollCents - 1_000);
	});
});

describe('pauseStrategy / resumeStrategy', () => {
	beforeEach(setupFixture);

	it('pauses only from pausable states', () => {
		expect(pauseStrategy(STRATEGY, 'pause').ok).toBe(true);
		expect(get(strategies).find((s) => s.name === STRATEGY)!.state).toBe('operator_paused');
		expect(pauseStrategy(STRATEGY, 'again').ok).toBe(false);
	});

	it('resumes to active from resumable states', () => {
		setStrategy(STRATEGY, { state: 'drawdown_paused' });
		expect(resumeStrategy(STRATEGY, 'go').ok).toBe(true);
		expect(get(strategies).find((s) => s.name === STRATEGY)!.state).toBe('active');
	});

	it('rejects resume from active', () => {
		expect(resumeStrategy(STRATEGY, 'nope').ok).toBe(false);
	});
});

describe('forceCloseAndWithdraw', () => {
	beforeEach(setupFixture);

	it('closes open positions for the strategy and realizes PnL', () => {
		const openBefore = get(positions).filter(
			(p) => p.strategyName === STRATEGY && p.status === 'open'
		);
		const unrealized = openBefore.reduce((sum, p) => sum + p.unrealizedPnlCents, 0);
		const bankrollBefore = get(strategies).find((s) => s.name === STRATEGY)!.bankrollCents;
		const pnlEventsBefore = get(cashEvents).filter(
			(e) => e.strategyName === STRATEGY && e.kind === 'realized_pnl'
		).length;

		forceCloseAndWithdraw(STRATEGY, 'flatten');

		const openAfter = get(positions).filter(
			(p) => p.strategyName === STRATEGY && p.status === 'open'
		);
		expect(openAfter).toHaveLength(0);
		const bankrollAfter = get(strategies).find((s) => s.name === STRATEGY)!.bankrollCents;
		expect(bankrollAfter).toBe(bankrollBefore + unrealized);
		const pnlEventsAfter = get(cashEvents).filter(
			(e) => e.strategyName === STRATEGY && e.kind === 'realized_pnl'
		).length;
		expect(pnlEventsAfter - pnlEventsBefore).toBe(openBefore.length);
	});

	it('is idempotent when no open positions remain', () => {
		forceCloseAndWithdraw(STRATEGY, 'first');
		const bankroll = get(strategies).find((s) => s.name === STRATEGY)!.bankrollCents;
		const result = forceCloseAndWithdraw(STRATEGY, 'second');
		expect(result.ok).toBe(true);
		expect(get(strategies).find((s) => s.name === STRATEGY)!.bankrollCents).toBe(bankroll);
	});
});

describe('kill switch', () => {
	beforeEach(setupFixture);

	it('requires a reason to trip and resume', () => {
		expect(tripKillSwitch('').ok).toBe(false);
		expect(tripKillSwitch('incident').ok).toBe(true);
		expect(get(system).state).toBe('paused');
		expect(resumeKillSwitch('').ok).toBe(false);
		expect(resumeKillSwitch('cleared').ok).toBe(true);
		expect(get(system).state).toBe('active');
	});

	it('blocks deposit while paused', () => {
		tripKillSwitch('halt');
		expect(deposit(STRATEGY, 500, 'blocked').ok).toBe(false);
	});
});

describe('canEmitSignals / resolveSignalOutcome', () => {
	beforeEach(setupFixture);

	it('returns false when strategy is paused', () => {
		setStrategy(STRATEGY, { state: 'operator_paused' });
		expect(canEmitSignals(STRATEGY)).toBe(false);
		expect(resolveSignalOutcome(STRATEGY)).toBe('rejected_system_paused');
	});

	it('returns rejected_kelly_zero when kelly is zero', () => {
		setStrategy(STRATEGY, { kellyFraction: 0 });
		expect(resolveSignalOutcome(STRATEGY)).toBe('rejected_kelly_zero');
	});

	it('can place orders when active with positive kelly', () => {
		vi.spyOn(Math, 'random').mockReturnValue(0.9);
		expect(canEmitSignals(STRATEGY)).toBe(true);
		expect(resolveSignalOutcome(STRATEGY)).toBe('order_placed');
		vi.restoreAllMocks();
	});
});

describe('persistence round-trip', () => {
	beforeEach(setupFixture);

	it('restores mutated state from localStorage', () => {
		deposit(STRATEGY, 2_500, 'persist me');
		const stored = localStorage.getItem('polytryhard');
		expect(stored).toBeTruthy();
		const expectedBankroll =
			JSON.parse(stored!).strategies.find((s: { name: string }) => s.name === STRATEGY)
				.bankrollCents;

		resetToFixtures();
		localStorage.setItem('polytryhard', stored!);
		rehydrateFromStorage();

		const strat = get(strategies).find((s) => s.name === STRATEGY)!;
		expect(strat.bankrollCents).toBe(expectedBankroll);
		expect(get(cashEvents)[0].kind).toBe('deposit');
	});
});
