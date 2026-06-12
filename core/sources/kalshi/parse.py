from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from core.contracts.source import RawMarketSnapshotDraft, ReferenceMarketUpsert


def _series_from_ticker(ticker: str) -> str:
    return ticker.split("-", 1)[0]


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
        series=str(
            payload.get("series_ticker") or payload.get("series") or _series_from_ticker(ticker)
        ),
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


def _fp_level(
    levels: object,
) -> tuple[Decimal | None, int | None]:
    if not isinstance(levels, list) or not levels:
        return None, None
    top = levels[0]
    if not isinstance(top, list) or len(top) < 2:
        return None, None
    price = Decimal(str(top[0]))
    size = int(Decimal(str(top[1])))
    return price, size


def _cent_level(
    levels: object,
) -> tuple[Decimal | None, int | None]:
    if not isinstance(levels, list) or not levels:
        return None, None
    top = levels[0]
    if not isinstance(top, list) or len(top) < 2:
        return None, None
    price = Decimal(str(top[0])) / Decimal("100")
    size = int(top[1])
    return price, size


def parse_orderbook(
    *, ticker: str, as_of: datetime, payload: dict[str, Any]
) -> RawMarketSnapshotDraft | None:
    orderbook_fp = payload.get("orderbook_fp")
    orderbook_legacy = payload.get("orderbook")

    bid_yes: Decimal | None = None
    bid_size: int | None = None
    ask_yes: Decimal | None = None
    ask_size: int | None = None

    if isinstance(orderbook_fp, dict):
        bid_yes, bid_size = _fp_level(orderbook_fp.get("yes_dollars"))
        no_price, ask_size = _fp_level(orderbook_fp.get("no_dollars"))
        if no_price is not None:
            ask_yes = Decimal("1") - no_price
    elif isinstance(orderbook_legacy, dict):
        bid_yes, bid_size = _cent_level(orderbook_legacy.get("yes"))
        no_price, ask_size = _cent_level(orderbook_legacy.get("no"))
        if no_price is not None:
            ask_yes = Decimal("1") - no_price

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
