from __future__ import annotations

from urllib.parse import urlencode

from core.clock import Clock
from core.contracts.source import FetchResult, IngestionSource, SourceContext
from core.db.shared_enums import SourceRunStatus
from core.settings import Settings
from core.sources.kalshi.auth import auth_headers
from core.sources.kalshi.parse import parse_market, parse_orderbook


class KalshiMarketsSource(IngestionSource):
    @property
    def name(self) -> str:
        return "kalshi_markets"

    @property
    def schedule_seconds(self) -> int:
        return 300

    def is_enabled(self, settings: Settings) -> bool:
        return settings.kalshi_configured

    async def fetch(self, clock: Clock, ctx: SourceContext) -> FetchResult:
        settings = ctx.settings
        if not settings.kalshi_configured:
            return FetchResult(
                status=SourceRunStatus.DEGRADED,
                error_text="Kalshi credentials not configured",
            )
        assert settings.kalshi_api_key_id is not None
        assert settings.kalshi_private_key is not None

        api_base = settings.kalshi_api_base_url
        result = FetchResult()
        for series in settings.kalshi_series_prefixes:
            path = "/trade-api/v2/markets"
            cursor: str | None = None
            while True:
                params: dict[str, str | int] = {
                    "series_ticker": series,
                    "status": "open",
                    "limit": 100,
                }
                if cursor is not None:
                    params["cursor"] = cursor
                query = urlencode(params)
                url = f"{api_base}{path}?{query}"
                headers = auth_headers(
                    key_id=settings.kalshi_api_key_id,
                    private_key_pem=settings.kalshi_private_key,
                    method="GET",
                    path=path,
                )
                response = await ctx.http.get(url, headers=headers)
                if response.status_code >= 400:
                    return FetchResult(
                        status=SourceRunStatus.DEGRADED,
                        error_text=f"Kalshi discovery HTTP {response.status_code}",
                    )
                payload = response.json()
                for market_payload in payload.get("markets", []):
                    upsert = parse_market(market_payload)
                    if upsert is not None:
                        result.market_upserts.append(upsert)
                cursor = payload.get("cursor")
                if not cursor:
                    break

        active_markets = list(ctx.markets)
        tickers = {market.ticker for market in active_markets}
        tickers.update(market.ticker for market in result.market_upserts)
        as_of = clock.now()

        for ticker in sorted(tickers):
            path = f"/trade-api/v2/markets/{ticker}/orderbook"
            url = f"{api_base}{path}"
            headers = auth_headers(
                key_id=settings.kalshi_api_key_id,
                private_key_pem=settings.kalshi_private_key,
                method="GET",
                path=path,
            )
            response = await ctx.http.get(url, headers=headers)
            if response.status_code >= 400:
                continue
            snapshot = parse_orderbook(ticker=ticker, as_of=as_of, payload=response.json())
            if snapshot is not None:
                result.market_snapshots.append(snapshot)

        if not result.market_snapshots and not result.market_upserts:
            return FetchResult(
                status=SourceRunStatus.DEGRADED,
                error_text="Kalshi returned no markets or snapshots",
            )
        if tickers and not result.market_snapshots and (
            result.market_upserts or active_markets
        ):
            return FetchResult(
                status=SourceRunStatus.DEGRADED,
                error_text="Kalshi orderbook fetch produced no snapshots",
                market_upserts=result.market_upserts,
            )
        return result
