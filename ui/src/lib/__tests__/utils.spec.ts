import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	formatAge,
	isUtcToday,
	signalDayGroupLabel,
	utcDayKey,
	utcYesterdayKey
} from '$lib/utils';

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

	it('accepts an explicit nowMs for reactive callers', () => {
		const now = Date.parse('2026-06-01T12:30:00Z');
		expect(formatAge('2026-06-01T12:29:45Z', now)).toBe('15s ago');
	});
});

describe('utc day helpers', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('uses UTC calendar days for today checks', () => {
		vi.useFakeTimers();
		vi.setSystemTime(new Date('2026-06-02T01:00:00Z'));

		expect(utcDayKey('2026-06-01T23:00:00Z')).toBe('2026-06-01');
		expect(isUtcToday('2026-06-02T00:30:00Z')).toBe(true);
		expect(isUtcToday('2026-06-01T23:00:00Z')).toBe(false);
	});

	it('labels signal groups in UTC', () => {
		vi.useFakeTimers();
		const now = Date.parse('2026-06-02T12:00:00Z');
		vi.setSystemTime(now);

		expect(signalDayGroupLabel('2026-06-02T01:00:00Z', now)).toBe('Today · Jun 2');
		expect(signalDayGroupLabel('2026-06-01T12:00:00Z', now)).toBe('Yesterday · Jun 1');
		expect(signalDayGroupLabel('2026-05-30T12:00:00Z', now)).toBe('May 30');
	});

	it('computes yesterday in UTC', () => {
		const now = Date.parse('2026-06-02T12:00:00Z');
		expect(utcYesterdayKey(now)).toBe('2026-06-01');
	});
});
