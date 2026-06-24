import { env } from '$env/dynamic/public';
import type { ApiGetResponse } from './responses';
import type { paths } from './types';

type JsonBody = Record<string, unknown>;

function publicEnv(): { backendUrl: string; backendToken: string } {
	return {
		backendUrl: (env.PUBLIC_BACKEND_URL ?? '').replace(/\/$/, ''),
		backendToken: env.PUBLIC_BACKEND_TOKEN ?? ''
	};
}

export function isBackendConfigured(): boolean {
	const { backendUrl, backendToken } = publicEnv();
	return Boolean(backendUrl && backendToken);
}

async function parseJson<T>(response: Response): Promise<T> {
	if (!response.ok) {
		const text = await response.text();
		let detail = text;
		try {
			const body = JSON.parse(text) as { detail?: string };
			if (typeof body.detail === 'string') {
				detail = body.detail;
			}
		} catch {
			// keep raw text
		}
		throw new Error(detail || `HTTP ${response.status}`);
	}
	if (response.status === 204) {
		return undefined as T;
	}
	return (await response.json()) as T;
}

/** GET with typed JSON body. Use `ApiGetResponse<'/v1/...'>` for static OpenAPI paths. */
export async function apiGet<T>(
	path: string,
	query?: Record<string, string | number | undefined>
): Promise<T> {
	const { backendUrl, backendToken } = publicEnv();
	const url = new URL(`${backendUrl}${path}`);
	if (query) {
		for (const [key, value] of Object.entries(query)) {
			if (value !== undefined) {
				url.searchParams.set(key, String(value));
			}
		}
	}
	const response = await fetch(url, {
		headers: { Authorization: `Bearer ${backendToken}` }
	});
	return parseJson<T>(response);
}

/** Typed GET when the path is a static OpenAPI route key. */
export async function apiGetPath<P extends keyof paths>(
	path: P,
	query?: Record<string, string | number | undefined>
): Promise<ApiGetResponse<P>> {
	return apiGet(path, query);
}

export async function apiPost<T = void>(path: string, body?: JsonBody): Promise<T> {
	const { backendUrl, backendToken } = publicEnv();
	const response = await fetch(`${backendUrl}${path}`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${backendToken}`,
			'Content-Type': 'application/json'
		},
		body: body ? JSON.stringify(body) : undefined
	});
	return parseJson<T>(response);
}
