from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from core.contracts.source import ReferenceMarketUpsert
from core.db.shared_enums import SourceRunStatus
from core.settings import Settings
from core.sources.kalshi import KalshiMarketsSource
from core.sources.kalshi.parse import parse_market, parse_orderbook

CASSETTES = Path(__file__).resolve().parent / "cassettes"

_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PEM = _TEST_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")


def _load_cassette(name: str) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads((CASSETTES / name).read_text(encoding="utf-8")),
    )


def test_parse_market_from_discovery_cassette() -> None:
    payload = _load_cassette("kalshi_markets_discovery.json")
    market = payload["markets"][0]
    upsert = parse_market(market)
    assert upsert == ReferenceMarketUpsert(
        ticker="KXHIGHNY-25MAY28-T72",
        series="KXHIGHNY",
        title="Highest temp in NYC on May 28",
        status="open",
        open_time=datetime(2026, 5, 27, 0, 0, tzinfo=UTC),
        close_time=datetime(2026, 5, 28, 23, 59, 59, tzinfo=UTC),
        settlement_source=None,
        settlement_ref=None,
        settlement_time=None,
        raw_jsonb=market,
    )


def test_parse_market_derives_series_from_live_active_ticker() -> None:
    upsert = parse_market(
        {
            "ticker": "KXHIGHNY-26JUN08-B72.5",
            "title": "NYC high temperature on Jun 8",
            "status": "active",
        }
    )

    assert upsert is not None
    assert upsert.series == "KXHIGHNY"
    assert upsert.status == "active"


def test_parse_market_extracts_strike_fields() -> None:
    payload = {
        "ticker": "KXHIGHNY-25MAY28-B72.5",
        "series_ticker": "KXHIGHNY",
        "title": "High temp in NYC on May 28",
        "status": "active",
        "strike_type": "between",
        "floor_strike": 72,
        "cap_strike": 73,
    }
    upsert = parse_market(payload)
    assert upsert is not None
    assert upsert.strike_type == "between"
    assert upsert.floor_strike == Decimal("72")
    assert upsert.cap_strike == Decimal("73")


def test_parse_market_strike_fields_default_none() -> None:
    upsert = parse_market({"ticker": "KXHIGHNY-25MAY28-T72", "status": "active"})
    assert upsert is not None
    assert upsert.strike_type is None
    assert upsert.floor_strike is None
    assert upsert.cap_strike is None


def test_parse_orderbook_from_fp_cassette() -> None:
    payload = _load_cassette("kalshi_orderbook.json")
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    snapshot = parse_orderbook(ticker="KXHIGHNY-25MAY28-T72", as_of=as_of, payload=payload)
    assert snapshot is not None
    assert snapshot.bid_yes == Decimal("0.4500")
    assert snapshot.ask_yes == Decimal("0.4800")
    assert snapshot.mid_yes == Decimal("0.4650")
    assert snapshot.bid_size == 120
    assert snapshot.ask_size == 80
    assert snapshot.last_trade_price is None
    assert snapshot.last_trade_size is None


def test_parse_orderbook_legacy_cent_format() -> None:
    payload = _load_cassette("kalshi_orderbook_legacy.json")
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    snapshot = parse_orderbook(ticker="TEST", as_of=as_of, payload=payload)
    assert snapshot is not None
    assert snapshot.bid_yes == Decimal("0.45")
    assert snapshot.ask_yes == Decimal("0.48")
    assert snapshot.bid_size == 120
    assert snapshot.ask_size == 80
    assert snapshot.last_trade_price == Decimal("0.46")
    assert snapshot.last_trade_size == 10


class _MockResponse:
    def __init__(self, *, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockHttp:
    def __init__(self, *, responses: list[tuple[str, _MockResponse]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> _MockResponse:
        self.calls.append(url)
        for prefix, response in self._responses:
            if prefix in url:
                return response
        return _MockResponse(status_code=404, payload={})


@pytest.mark.asyncio
async def test_kalshi_fetch_degraded_when_orderbooks_empty() -> None:
    discovery = _load_cassette("kalshi_markets_discovery.json")
    settings = Settings(
        REQUIRE_DBS=False,
        KALSHI_API_KEY_ID="key",
        KALSHI_PRIVATE_KEY=TEST_PEM,
    )
    http = _MockHttp(
        responses=[
            ("/trade-api/v2/markets", _MockResponse(status_code=200, payload=discovery)),
            ("/orderbook", _MockResponse(status_code=404, payload={})),
        ]
    )
    from core.clock import FakeClock
    from core.contracts.source import SourceContext

    source = KalshiMarketsSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=settings,
            locations=(),
            markets=(),
            http=http,
        ),
    )
    assert result.status == SourceRunStatus.DEGRADED
    assert result.error_text == "Kalshi orderbook fetch produced no snapshots"
    assert len(result.market_upserts) == 1


@pytest.mark.asyncio
async def test_kalshi_fetch_skips_stale_db_market_orderbooks() -> None:
    discovery = _load_cassette("kalshi_markets_discovery.json")
    orderbook = _load_cassette("kalshi_orderbook.json")
    settings = Settings(
        REQUIRE_DBS=False,
        KALSHI_API_KEY_ID="key",
        KALSHI_PRIVATE_KEY=TEST_PEM,
    )
    stale_ticker = "KXHIGHNY-26JUN07-B87.5"
    http = _MockHttp(
        responses=[
            ("/trade-api/v2/markets?", _MockResponse(status_code=200, payload=discovery)),
            (
                f"/markets/{discovery['markets'][0]['ticker']}/orderbook",
                _MockResponse(status_code=200, payload=orderbook),
            ),
        ]
    )
    from core.clock import FakeClock
    from core.contracts.source import ReferenceMarketUpsert, SourceContext

    source = KalshiMarketsSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=settings,
            locations=(),
            markets=(
                ReferenceMarketUpsert(
                    ticker=stale_ticker,
                    series="KXHIGHNY",
                    title="stale",
                    status="active",
                    settlement_source=None,
                    settlement_ref=None,
                    open_time=None,
                    close_time=None,
                    settlement_time=None,
                    raw_jsonb={},
                ),
            ),
            http=http,
        ),
    )
    assert result.status == SourceRunStatus.OK
    assert len(result.market_snapshots) == 1
    assert result.market_snapshots[0].ticker == discovery["markets"][0]["ticker"]
    assert stale_ticker not in "".join(http.calls)
