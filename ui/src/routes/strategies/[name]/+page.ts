import { strategyEntries } from '$lib/mocks/fixtures';

export const prerender = true;

export function entries() {
	return strategyEntries().map((name) => ({ name }));
}
