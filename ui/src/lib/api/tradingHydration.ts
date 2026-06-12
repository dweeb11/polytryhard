import { writable } from 'svelte/store';

export type TradingHydrationFreshness = 'fresh' | 'stale';

export interface TradingHydrationState {
	signals: TradingHydrationFreshness;
	positions: TradingHydrationFreshness;
}

/** Updated by hydrateLedgerFromApi when live trading read endpoints succeed or fail. */
export const tradingHydration = writable<TradingHydrationState>({
	signals: 'fresh',
	positions: 'fresh'
});
