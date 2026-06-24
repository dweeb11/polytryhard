import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	compactIsoTime,
	formatAge,
	groupItemsByDayLabel,
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

describe('compactIsoTime', () => {
	it('returns a placeholder for missing or invalid timestamps', () => {
		expect(compactIsoTime('')).toBe('—');
		expect(compactIsoTime('not-a-date')).toBe('—');
	});

	it('formats valid ISO timestamps as 24h local time', () => {
		const formatted = compactIsoTime('2026-06-01T14:05:00Z');
		expect(formatted).toMatch(/^\d{2}:\d{2}$/);
		expect(formatted).toBe(
			new Date('2026-06-01T14:05:00Z').toLocaleTimeString([], {
				hour: '2-digit',
				minute: '2-digit',
				hour12: false
			})
		);
	});
});

describe('groupItemsByDayLabel', () => {
	it('groups consecutive items with the same day label', () => {
		const now = Date.parse('2026-06-02T12:00:00Z');
		const items = [
			{ id: 'a', at: '2026-06-02T10:00:00Z' },
			{ id: 'b', at: '2026-06-02T09:00:00Z' },
			{ id: 'c', at: '2026-06-01T12:00:00Z' }
		];

		expect(groupItemsByDayLabel(items, (item) => item.at, now)).toEqual([
			{ key: '2026-06-02', day: 'Today · Jun 2', items: [items[0], items[1]] },
			{ key: '2026-06-01', day: 'Yesterday · Jun 1', items: [items[2]] }
		]);
	});

	it('keeps separate groups when the same month/day repeats in different years', () => {
		const items = [
			{ id: 'a', at: '2026-06-01T10:00:00Z' },
			{ id: 'b', at: '2025-06-01T09:00:00Z' }
		];

		const groups = groupItemsByDayLabel(items, (item) => item.at);
		expect(groups).toEqual([
			{ key: '2026-06-01', day: 'Jun 1', items: [items[0]] },
			{ key: '2025-06-01', day: 'Jun 1', items: [items[1]] }
		]);
	});
});
