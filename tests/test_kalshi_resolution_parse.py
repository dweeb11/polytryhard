from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.contracts.source import ContractResolutionDraft, FetchResult
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.sources.kalshi.resolution import parse_market_result
from core.sources.persistence import persist_fetch_result


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
