import { vi } from 'vitest';

class LocalStorageMock implements Storage {
	private store = new Map<string, string>();

	get length(): number {
		return this.store.size;
	}

	clear(): void {
		this.store.clear();
	}

	getItem(key: string): string | null {
		return this.store.get(key) ?? null;
	}

	key(index: number): string | null {
		return [...this.store.keys()][index] ?? null;
	}

	removeItem(key: string): void {
		this.store.delete(key);
	}

	setItem(key: string, value: string): void {
		this.store.set(key, value);
	}
}

vi.stubGlobal('localStorage', new LocalStorageMock());

if (!globalThis.crypto?.randomUUID) {
	vi.stubGlobal('crypto', {
		randomUUID: () =>
			`00000000-0000-4000-8000-${Math.floor(Math.random() * 1e12)
				.toString(16)
				.padStart(12, '0')}`
	});
}
