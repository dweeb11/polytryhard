from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.contracts.source import (
    ContractResolutionDraft,
    FetchResult,
    RawMarketSnapshotDraft,
    ReferenceMarketUpsert,
)
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.db.shared_models import (
    ContractResolutionRow,
    RawMarketSnapshotRow,
    ReferenceMarketRow,
    SourceRunRow,
)
from core.sources.persistence import persist_fetch_result


def test_persist_fetch_result_new_ticker_parents_before_dependents(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    """Regression: parent reference_market and source_run must flush before snapshots."""
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    ticker = "NEW-TICKER"
    now = datetime(2026, 6, 7, tzinfo=UTC)
    result = FetchResult(
        status=SourceRunStatus.OK,
        market_upserts=[
            ReferenceMarketUpsert(
                ticker=ticker,
                series="KXHIGHNY",
                title="Test market",
                status="open",
                strike_type="between",
                floor_strike=Decimal("72"),
                cap_strike=Decimal("73"),
                raw_jsonb={"ticker": ticker},
            )
        ],
        market_snapshots=[
            RawMarketSnapshotDraft(
                ticker=ticker,
                as_of=now,
                bid_yes=Decimal("0.40"),
                ask_yes=Decimal("0.42"),
                mid_yes=Decimal("0.41"),
                bid_size=10,
                ask_size=12,
                last_trade_price=Decimal("0.41"),
                last_trade_size=5,
                raw_jsonb={"ticker": ticker},
            )
        ],
        resolutions=[
            ContractResolutionDraft(
                ticker=ticker,
                resolved_at=now,
                resolution=ContractResolution.NO,
                settlement_value=Decimal("0"),
                source_evidence_jsonb={"result": "no"},
            )
        ],
    )

    with Session(engine) as session:
        assert session.scalar(select(ReferenceMarketRow).limit(1)) is None

        run_row = persist_fetch_result(
            session,
            source_name="kalshi_markets",
            request_id="req-new-ticker",
            started_at=now,
            finished_at=now,
            result=result,
        )

        market = session.get(ReferenceMarketRow, ticker)
        assert market is not None
        assert market.series == "KXHIGHNY"
        assert market.strike_type == "between"
        assert market.floor_strike == Decimal("72")
        assert market.cap_strike == Decimal("73")

        persisted_run = session.get(SourceRunRow, run_row.id)
        assert persisted_run is not None
        assert persisted_run.source_name == "kalshi_markets"

        snapshots = session.scalars(
            select(RawMarketSnapshotRow).where(RawMarketSnapshotRow.ticker == ticker)
        ).all()
        assert len(snapshots) == 1
        assert snapshots[0].source_run_id == run_row.id

        resolution = session.get(ContractResolutionRow, ticker)
        assert resolution is not None
        assert resolution.resolution == ContractResolution.NO
