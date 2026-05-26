import { writable } from 'svelte/store';
import type { Toast } from '../types';
import { uuid } from '../utils';

export const toasts = writable<Toast[]>([]);

export function pushToast(type: Toast['type'], message: string, ttlMs = 5000): void {
	const id = uuid();
	toasts.update((list) => [...list, { id, type, message, createdAt: Date.now() }]);
	setTimeout(() => {
		toasts.update((list) => list.filter((t) => t.id !== id));
	}, ttlMs);
}

export function dismissToast(id: string): void {
	toasts.update((list) => list.filter((t) => t.id !== id));
}
