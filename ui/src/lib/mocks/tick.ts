import { get } from 'svelte/store';
import {
	emitSignal,
	resolveSignalOutcome,
	canEmitSignals
} from '../actions';
import { positions, sources, strategies } from '../stores';
import { tickSimulatorEnabled } from '../stores/tick';
import { nowIso } from '../utils';

let intervalId: ReturnType<typeof setInterval> | null = null;

export function startTickSimulator(): void {
	if (intervalId) return;
	intervalId = setInterval(tickOnce, 3000);
}

export function stopTickSimulator(): void {
	if (intervalId) {
		clearInterval(intervalId);
		intervalId = null;
	}
}

export function setTickEnabled(enabled: boolean): void {
	tickSimulatorEnabled.set(enabled);
	if (enabled) startTickSimulator();
	else stopTickSimulator();
}

function tickOnce(): void {
	if (!get(tickSimulatorEnabled)) return;

	sources.update((list) =>
		list.map((s) => {
			const age = Date.now() - new Date(s.lastSuccessfulFetch).getTime();
			let state = s.state;
			if (age > 600000 && s.state === 'healthy') state = 'degraded';
			if (age > 3600000) state = 'down';
			return { ...s, state };
		})
	);

	positions.update((list) =>
		list.map((p) => {
			if (p.status !== 'open') return p;
			const drift = Math.round((Math.random() - 0.48) * 120);
			return { ...p, unrealizedPnlCents: p.unrealizedPnlCents + drift };
		})
	);

	strategies.update((list) =>
		list.map((s) => ({
			...s,
			todayPnlCents: s.todayPnlCents + Math.round((Math.random() - 0.5) * 80)
		}))
	);

	if (Math.random() > 0.55) return;
	const strats = get(strategies).filter((s) => s.enabled && s.state !== 'decommissioned');
	if (!strats.length) return;
	const strat = strats[Math.floor(Math.random() * strats.length)];
	if (!canEmitSignals(strat.name)) return;

	const outcome = resolveSignalOutcome(strat.name);
	const tickers = ['KXHIGHMIA-25MAY', 'KXHIGHCHI-25MAY', 'KXHIGHNYC-25MAY'];
	emitSignal({
		strategyName: strat.name,
		ticker: tickers[Math.floor(Math.random() * tickers.length)],
		evaluatedAt: nowIso(),
		probYes: 0.4 + Math.random() * 0.2,
		confidence: 0.5 + Math.random() * 0.3,
		outcome,
		rejectionReason: outcome === 'order_placed' ? null : `tick: ${outcome}`
	});
}

export function initTickFromStore(): void {
	tickSimulatorEnabled.subscribe((on) => {
		if (on) startTickSimulator();
		else stopTickSimulator();
	});
}
