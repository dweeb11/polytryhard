from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.clock import FakeClock
from core.db.models import SignalRow
from core.db.shared_enums import ForecastSource
from core.db.shared_models import RawForecastRunRow, RawMarketSnapshotRow, ReferenceMarketRow
from core.engine.tick import _strategy_open_positions, run_engine_tick
from core.ledger import writer
from core.domain.enums import AuditActor, PositionSide
from core.ledger.seed import seed_strategies_if_needed
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def _seed_shared(session: Session) -> None:
    seed_locations_if_needed(session)
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    session.add(
        ReferenceMarketRow(
            ticker="KXHIGHNY-25MAY28-T72",
            series="KXHIGHNY",
            title="test market",
            status="open",
            raw_jsonb={},
        )
    )
    session.add(
        RawMarketSnapshotRow(
            id="snap-1",
            ticker="KXHIGHNY-25MAY28-T72",
            as_of=as_of,
            bid_yes=Decimal("0.10"),
            ask_yes=Decimal("0.20"),
            mid_yes=Decimal("0.05"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    for source, values in (
        (ForecastSource.GFS, [Decimal("95"), Decimal("97")]),
        (ForecastSource.ECMWF, [Decimal("88"), Decimal("92")]),
    ):
        for idx, value in enumerate(values, start=1):
            session.add(
                RawForecastRunRow(
                    id=f"nyc-{source.value}-{idx}",
                    source=source,
                    run_time=as_of,
                    ingested_at=as_of,
                    location_id="nyc",
                    valid_window_start=as_of,
                    valid_window_end=as_of,
                    variable="temperature_2m",
                    value=value,
                    ensemble_member=idx,
                    raw_jsonb={},
                )
            )
    session.commit()


@pytest.mark.asyncio
async def test_engine_tick_writes_signal_and_optional_fill(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    shared_engine = create_engine(shared_url)
    per_env_engine = create_engine(per_env_url)
    shared = sessionmaker(bind=shared_engine, expire_on_commit=False)()
    per_env = sessionmaker(bind=per_env_engine, expire_on_commit=False)()

    _seed_shared(shared)
    seed_strategies_if_needed(per_env, request_id="seed-engine")

    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

    stats = await run_engine_tick(
        settings=settings,
        clock=clock,
        shared_session=shared,
        per_env_session=per_env,
        request_id="integration-test",
    )

    assert stats["features"] > 0
    assert stats["signals"] >= 1
    assert 0 <= stats["orders"] <= stats["signals"]
    signal_count = per_env.scalar(select(func.count()).select_from(SignalRow))
    assert signal_count is not None and signal_count >= 1


def test_strategy_open_positions_sees_flushed_open_row(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    _, per_env_url = per_env_sqlite_urls
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    seed_strategies_if_needed(per_env, request_id="test-open-positions-seed")

    writer.open_paper_position(
        per_env,
        strategy_name="weather_stale_quote",
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=1,
        price=Decimal("0.15"),
        cost_basis_cents=15,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="test-open-positions",
    )
    per_env.flush()

    assert len(_strategy_open_positions(per_env, "weather_stale_quote")) == 1
