import { env } from '$env/dynamic/public';

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

export async function apiGet(
	path: string,
	query?: Record<string, string | number | undefined>
): Promise<unknown> {
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
	return parseJson(response);
}

export async function apiPost(path: string, body?: JsonBody): Promise<unknown> {
	const { backendUrl, backendToken } = publicEnv();
	const response = await fetch(`${backendUrl}${path}`, {
		method: 'POST',
		headers: {
			Authorization: `Bearer ${backendToken}`,
			'Content-Type': 'application/json'
		},
		body: body ? JSON.stringify(body) : undefined
	});
	return parseJson(response);
}
