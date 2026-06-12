import { derived, writable } from 'svelte/store';
import { setTickEnabled } from '../mocks/tick';

export type UiMode = 'developer' | 'release';

const STORAGE_KEY = 'polytryhard:uiMode';

function readStored(): UiMode {
	if (typeof localStorage === 'undefined') return 'developer';
	return localStorage.getItem(STORAGE_KEY) === 'release' ? 'release' : 'developer';
}

export const uiMode = writable<UiMode>(readStored());

export const isDeveloperMode = derived(uiMode, ($mode) => $mode === 'developer');

export function setUiMode(mode: UiMode): void {
	uiMode.set(mode);
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem(STORAGE_KEY, mode);
	}
	if (mode === 'release') {
		setTickEnabled(false);
	}
}
