const LIVE_API_EMPTY = {
	signals: [] as unknown[],
	positions: [] as unknown[]
};

export function handleLiveApiGet(url: string): Response | null {
	if (url.includes('/v1/signals')) {
		return new Response(JSON.stringify(LIVE_API_EMPTY.signals), { status: 200 });
	}
	if (url.includes('/v1/positions')) {
		return new Response(JSON.stringify(LIVE_API_EMPTY.positions), { status: 200 });
	}
	return null;
}
