from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.contracts.source import RawMarketSnapshotDraft, ReferenceMarketUpsert


def parse_market(payload: dict[str, Any]) -> ReferenceMarketUpsert | None:
    ticker = payload.get("ticker")
    if not isinstance(ticker, str):
        return None

    def _parse_dt(value: object) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed

    return ReferenceMarketUpsert(
        ticker=ticker,
        series=str(payload.get("series_ticker") or payload.get("series") or ""),
        title=str(payload.get("title") or ticker),
        status=str(payload.get("status") or "unknown"),
        settlement_source=(
            str(payload["settlement_source"]) if payload.get("settlement_source") else None
        ),
        settlement_ref=str(payload["settlement_ref"]) if payload.get("settlement_ref") else None,
        open_time=_parse_dt(payload.get("open_time")),
        close_time=_parse_dt(payload.get("close_time")),
        settlement_time=_parse_dt(payload.get("settlement_time")),
        raw_jsonb=dict(payload),
    )


def parse_orderbook(
    *, ticker: str, as_of: datetime, payload: dict[str, Any]
) -> RawMarketSnapshotDraft | None:
    orderbook = payload.get("orderbook") or payload.get("orderbook_fp") or {}
    yes_bids = orderbook.get("yes") or []
    no_bids = orderbook.get("no") or []

    bid_yes: Decimal | None = None
    bid_size: int | None = None
    if yes_bids:
        top = yes_bids[0]
        if isinstance(top, list) and len(top) >= 2:
            bid_yes = Decimal(str(top[0])) / Decimal("100")
            bid_size = int(top[1])

    ask_yes: Decimal | None = None
    ask_size: int | None = None
    if no_bids:
        top = no_bids[0]
        if isinstance(top, list) and len(top) >= 2:
            ask_yes = Decimal("1") - Decimal(str(top[0])) / Decimal("100")
            ask_size = int(top[1])

    mid_yes: Decimal | None = None
    if bid_yes is not None and ask_yes is not None:
        mid_yes = (bid_yes + ask_yes) / Decimal("2")

    last_trade = payload.get("last_trade") or {}
    last_trade_price: Decimal | None = None
    last_trade_size: int | None = None
    if isinstance(last_trade, dict):
        if last_trade.get("yes_price") is not None:
            last_trade_price = Decimal(str(last_trade["yes_price"])) / Decimal("100")
        if last_trade.get("count") is not None:
            last_trade_size = int(last_trade["count"])

    if bid_yes is None and ask_yes is None and last_trade_price is None:
        return None

    return RawMarketSnapshotDraft(
        ticker=ticker,
        as_of=as_of,
        bid_yes=bid_yes,
        ask_yes=ask_yes,
        mid_yes=mid_yes,
        bid_size=bid_size,
        ask_size=ask_size,
        last_trade_price=last_trade_price,
        last_trade_size=last_trade_size,
        raw_jsonb=dict(payload),
    )
