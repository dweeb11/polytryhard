from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.clock import Clock
from core.contracts.source import (
    ContractResolutionDraft,
    FetchResult,
    IngestionSource,
    SourceContext,
)
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.settings import Settings
from core.sources.kalshi.auth import auth_headers

_SETTLED_STATUSES = {"settled", "finalized"}
_UNRESOLVED_REFERENCE_STATUSES = {"settled", "finalized"}


def parse_market_result(payload: dict[str, Any]) -> tuple[ContractResolution, Decimal] | None:
    """Pure: decode a Kalshi market payload into (resolution, yes-settlement-price).

    Returns None when the market is not yet settled or the payload is malformed.
    Settlement value is the YES settlement price in [0, 1]: 1 for yes, 0 otherwise.
    """
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    status = market.get("status")
    if status not in _SETTLED_STATUSES:
        return None
    result = market.get("result")
    if result == "yes":
        return ContractResolution.YES, Decimal("1")
    if result == "no":
        return ContractResolution.NO, Decimal("0")
    return ContractResolution.VOID, Decimal("0")


class KalshiResolutionSource(IngestionSource):
    @property
    def name(self) -> str:
        return "kalshi_resolution"

    @property
    def schedule_seconds(self) -> int:
        return 3600

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

        candidates = [
            m for m in ctx.markets if m.status not in _UNRESOLVED_REFERENCE_STATUSES
        ]
        if not candidates:
            return FetchResult(status=SourceRunStatus.OK)

        api_base = settings.kalshi_api_base_url
        result = FetchResult()
        resolved_at = clock.now()
        for market in candidates:
            path = f"/trade-api/v2/markets/{market.ticker}"
            url = f"{api_base}{path}"
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
                    error_text=f"Kalshi HTTP {response.status_code} for {market.ticker}",
                )
            payload = response.json()
            parsed = parse_market_result(payload)
            if parsed is None:
                continue
            resolution, settlement_value = parsed
            result.resolutions.append(
                ContractResolutionDraft(
                    ticker=market.ticker,
                    resolved_at=resolved_at,
                    resolution=resolution,
                    settlement_value=settlement_value,
                    source_evidence_jsonb=payload.get("market", {}),
                )
            )
        return result
