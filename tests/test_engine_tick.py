from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.clock import FakeClock
from core.db.enums import SignalOutcome
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import SignalRow, StrategyInstanceRow
from core.db.shared_enums import ForecastSource
from core.db.shared_models import RawForecastRunRow, RawMarketSnapshotRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide
from core.engine.tick import _strategy_open_positions, run_engine_tick
from core.ledger import writer
from core.ledger.seed import seed_strategies_if_needed
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def _add_open_market_with_snapshot(
    session: Session,
    *,
    ticker: str,
    as_of: datetime,
    snap_id: str,
) -> None:
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="KXHIGHNY",
            title=f"test market {ticker}",
            status="open",
            raw_jsonb={},
        )
    )
    session.flush()
    session.add(
        RawMarketSnapshotRow(
            id=snap_id,
            ticker=ticker,
            as_of=as_of,
            bid_yes=Decimal("0.35"),
            ask_yes=Decimal("0.50"),
            mid_yes=Decimal("0.30"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )


def _seed_shared(session: Session, *, extra_tickers: tuple[str, ...] = ()) -> None:
    seed_locations_if_needed(session)
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    _add_open_market_with_snapshot(
        session, ticker="KXHIGHNY-25MAY28-T72", as_of=as_of, snap_id="snap-1"
    )
    for idx, ticker in enumerate(extra_tickers, start=2):
        _add_open_market_with_snapshot(
            session, ticker=ticker, as_of=as_of, snap_id=f"snap-{idx}"
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


@pytest.mark.asyncio
async def test_engine_tick_second_market_hits_correlation_cap_after_first_fill(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    shared_engine = create_engine(shared_url)
    per_env_engine = create_engine(per_env_url)
    shared = sessionmaker(bind=shared_engine, expire_on_commit=False)()
    per_env = sessionmaker(bind=per_env_engine, expire_on_commit=False)()

    _seed_shared(shared, extra_tickers=("KXHIGHNY-25MAY28-T75",))
    seed_strategies_if_needed(per_env, request_id="seed-exposure-cap")

    stale_row = per_env.get(StrategyInstanceRow, "weather_stale_quote")
    assert stale_row is not None
    stale_row.config_jsonb = {
        **dict(stale_row.config_jsonb),
        "exposureCapPct": 1.0,
        "correlationCapPct": 0.02,
    }
    other = per_env.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert other is not None
    other.enabled = False
    other.bankroll_cents = 0
    per_env.flush()

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
        request_id="exposure-cap-tick",
    )

    signals = list(
        per_env.scalars(
            select(SignalRow).where(SignalRow.strategy_name == "weather_stale_quote")
        ).all()
    )
    by_ticker = {row.ticker: row.outcome for row in signals}
    assert stats["orders"] == 1
    assert by_ticker["KXHIGHNY-25MAY28-T72"] == SignalOutcome.ORDER_PLACED
    assert by_ticker["KXHIGHNY-25MAY28-T75"] == SignalOutcome.REJECTED_CORRELATION_CAP


@pytest.mark.asyncio
async def test_engine_tick_auto_pauses_strategy_breaching_drawdown_cap(
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
    seed_strategies_if_needed(per_env, request_id="seed-drawdown-pause")

    stale_row = per_env.get(StrategyInstanceRow, "weather_stale_quote")
    assert stale_row is not None
    stale_row.bankroll_hwm_cents = 10_000
    stale_row.bankroll_cents = 6_900  # 31% drawdown, config max is 30%
    other = per_env.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert other is not None
    other.enabled = False
    other.bankroll_cents = 0
    per_env.flush()
    per_env.commit()

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
        request_id="drawdown-pause-tick",
    )

    per_env.refresh(stale_row)
    assert stale_row.state == DbStrategyState.DRAWDOWN_PAUSED
    signal_count = per_env.scalar(
        select(func.count()).select_from(SignalRow).where(
            SignalRow.strategy_name == "weather_stale_quote"
        )
    )
    assert signal_count == 0
    assert stats["signals"] == 0


@pytest.mark.asyncio
async def test_engine_tick_leaves_strategy_active_below_drawdown_cap(
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
    seed_strategies_if_needed(per_env, request_id="seed-drawdown-ok")

    stale_row = per_env.get(StrategyInstanceRow, "weather_stale_quote")
    assert stale_row is not None
    stale_row.bankroll_hwm_cents = 10_000
    stale_row.bankroll_cents = 7_100  # 29% drawdown, config max is 30%
    other = per_env.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert other is not None
    other.enabled = False
    other.bankroll_cents = 0
    per_env.flush()
    per_env.commit()

    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))

    await run_engine_tick(
        settings=settings,
        clock=clock,
        shared_session=shared,
        per_env_session=per_env,
        request_id="drawdown-ok-tick",
    )

    per_env.refresh(stale_row)
    assert stale_row.state == DbStrategyState.ACTIVE
