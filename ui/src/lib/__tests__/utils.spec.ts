import { afterEach, describe, expect, it, vi } from 'vitest';

import { formatAge } from '$lib/utils';

describe('formatAge', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('returns a placeholder for missing or invalid timestamps', () => {
		expect(formatAge('')).toBe('—');
		expect(formatAge(null)).toBe('—');
		expect(formatAge(undefined)).toBe('—');
		expect(formatAge('not-a-date')).toBe('—');
	});

	it('formats valid timestamps relative to now', () => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date('2026-06-01T12:30:00Z'));

		expect(formatAge('2026-06-01T12:29:45Z')).toBe('15s ago');
		expect(formatAge('2026-06-01T12:00:00Z')).toBe('30m ago');
		expect(formatAge('2026-06-01T10:00:00Z')).toBe('2h ago');
		expect(formatAge('2026-05-30T12:00:00Z')).toBe('2d ago');
	});
});
