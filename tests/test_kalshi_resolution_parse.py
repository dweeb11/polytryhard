from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.clock import FakeClock
from core.contracts.source import ContractResolutionDraft, FetchResult, ReferenceMarketUpsert, SourceContext
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.settings import Settings
from core.sources.kalshi.resolution import KalshiResolutionSource, parse_market_result
from core.sources.persistence import persist_fetch_result

_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
TEST_PEM = _TEST_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode("utf-8")


class _MockResponse:
    def __init__(self, *, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class _MockHttp:
    def __init__(self, *, responses: dict[str, _MockResponse]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> _MockResponse:
        self.calls.append(url)
        for suffix, response in self._responses.items():
            if suffix in url:
                return response
        return _MockResponse(status_code=404, payload={})


def _resolution_settings() -> Settings:
    return Settings(
        REQUIRE_DBS=False,
        KALSHI_API_KEY_ID="key",
        KALSHI_PRIVATE_KEY=TEST_PEM,
    )


def _market(ticker: str, *, status: str = "open") -> ReferenceMarketUpsert:
    return ReferenceMarketUpsert(
        ticker=ticker,
        series="S",
        title="t",
        status=status,
        raw_jsonb={},
    )


def _seed_market(session: Session, ticker: str) -> None:
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="S",
            title="t",
            settlement_source=None,
            settlement_ref=None,
            open_time=None,
            close_time=None,
            settlement_time=None,
            status="closed",
            raw_jsonb={},
        )
    )
    session.commit()


def test_persist_resolution_is_idempotent(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    ticker = "KXHIGHNY-25JUN01-T70"
    draft = ContractResolutionDraft(
        ticker=ticker,
        resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
        resolution=ContractResolution.NO,
        settlement_value=Decimal("0"),
        source_evidence_jsonb={"result": "no"},
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)
    with Session(engine) as session:
        _seed_market(session, ticker)
        persist_fetch_result(
            session,
            source_name="kalshi_resolution",
            request_id="r1",
            started_at=now,
            finished_at=now,
            result=FetchResult(status=SourceRunStatus.OK, resolutions=[draft]),
        )
        persist_fetch_result(
            session,
            source_name="kalshi_resolution",
            request_id="r2",
            started_at=now,
            finished_at=now,
            result=FetchResult(status=SourceRunStatus.OK, resolutions=[draft]),
        )
        rows = session.scalars(select(ContractResolutionRow)).all()
        assert len(rows) == 1
        assert rows[0].resolution == ContractResolution.NO


def test_parse_yes() -> None:
    out = parse_market_result({"market": {"status": "finalized", "result": "yes"}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.YES
    assert settlement_value == Decimal("1")


def test_parse_no() -> None:
    out = parse_market_result({"market": {"status": "settled", "result": "no"}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.NO
    assert settlement_value == Decimal("0")


def test_parse_void_empty_result_on_settled() -> None:
    out = parse_market_result({"market": {"status": "settled", "result": ""}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.VOID
    assert settlement_value == Decimal("0")


def test_parse_not_yet_settled_returns_none() -> None:
    assert parse_market_result({"market": {"status": "active", "result": ""}}) is None


def test_parse_missing_market_returns_none() -> None:
    assert parse_market_result({}) is None


@pytest.mark.asyncio
async def test_fetch_skips_markets_with_existing_resolution_row() -> None:
    ticker = "KXHIGHNY-25JUN01-T70"
    http = _MockHttp(
        responses={
            ticker: _MockResponse(
                status_code=200,
                payload={"market": {"status": "settled", "result": "yes"}},
            ),
        }
    )
    source = KalshiResolutionSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 6, 2, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=_resolution_settings(),
            locations=(),
            markets=(_market(ticker),),
            http=http,
            resolved_tickers=frozenset({ticker}),
        ),
    )
    assert result.status == SourceRunStatus.OK
    assert result.resolutions == []
    assert http.calls == []


@pytest.mark.asyncio
async def test_fetch_polls_settled_reference_status_without_resolution_row() -> None:
    ticker = "KXHIGHNY-25JUN01-T71"
    http = _MockHttp(
        responses={
            ticker: _MockResponse(
                status_code=200,
                payload={"market": {"status": "settled", "result": "no"}},
            ),
        }
    )
    source = KalshiResolutionSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 6, 2, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=_resolution_settings(),
            locations=(),
            markets=(_market(ticker, status="settled"),),
            http=http,
        ),
    )
    assert result.status == SourceRunStatus.OK
    assert len(result.resolutions) == 1
    assert result.resolutions[0].ticker == ticker
    assert result.resolutions[0].resolution == ContractResolution.NO


@pytest.mark.asyncio
async def test_fetch_continues_after_per_ticker_4xx() -> None:
    bad = "KXHIGHNY-BAD"
    good = "KXHIGHNY-GOOD"
    http = _MockHttp(
        responses={
            bad: _MockResponse(status_code=404, payload={}),
            good: _MockResponse(
                status_code=200,
                payload={"market": {"status": "finalized", "result": "yes"}},
            ),
        }
    )
    source = KalshiResolutionSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 6, 2, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=_resolution_settings(),
            locations=(),
            markets=(_market(bad), _market(good)),
            http=http,
        ),
    )
    assert result.status == SourceRunStatus.OK
    assert len(result.resolutions) == 1
    assert result.resolutions[0].ticker == good
    assert len(http.calls) == 2


@pytest.mark.asyncio
async def test_fetch_degraded_when_all_tickers_return_4xx() -> None:
    ticker = "KXHIGHNY-MISSING"
    http = _MockHttp(
        responses={
            ticker: _MockResponse(status_code=404, payload={}),
        }
    )
    source = KalshiResolutionSource()
    result = await source.fetch(
        FakeClock(start=datetime(2026, 6, 2, tzinfo=UTC)),
        SourceContext(
            request_id="test",
            settings=_resolution_settings(),
            locations=(),
            markets=(_market(ticker),),
            http=http,
        ),
    )
    assert result.status == SourceRunStatus.DEGRADED
    assert result.resolutions == []
    assert "404" in (result.error_text or "")
