from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.contracts.feature import FeatureContext
from core.db.shared_enums import ForecastSource
from core.db.shared_models import RawForecastRunRow, ReferenceMarketRow
from core.engine.markets import build_market_states
from core.features.ensemble_mean_temp import EnsembleMeanTempProvider
from core.features.forecast_disagreement import ForecastDisagreementProvider
from core.features.kalshi_spread import KalshiSpreadProvider
from core.features.registry import registered_feature_providers
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def _insert_forecast_rows(
    session: Session,
    location_id: str,
    run_time: datetime,
    *,
    gfs_values: tuple[Decimal, Decimal] | None = None,
    ecmwf_values: tuple[Decimal, Decimal] | None = None,
    valid_window_start: datetime | None = None,
) -> None:
    window_start = valid_window_start or run_time
    window_end = window_start + timedelta(hours=1)
    gfs = gfs_values or (Decimal("70"), Decimal("72"))
    ecmwf = ecmwf_values or (Decimal("68"), Decimal("74"))
    for source, values in (
        (ForecastSource.GFS, list(gfs)),
        (ForecastSource.ECMWF, list(ecmwf)),
    ):
        for idx, value in enumerate(values, start=1):
            session.add(
                RawForecastRunRow(
                    id=f"{location_id}-{source.value}-{window_start.isoformat()}-{idx}",
                    source=source,
                    run_time=run_time,
                    ingested_at=run_time,
                    location_id=location_id,
                    valid_window_start=window_start,
                    valid_window_end=window_end,
                    variable="temperature_2m",
                    value=value,
                    ensemble_member=idx,
                    raw_jsonb={},
                )
            )


def _session_from_shared_url(shared_url: str) -> Session:
    from sqlalchemy import create_engine

    engine = create_engine(shared_url)
    return sessionmaker(bind=engine, expire_on_commit=False)()


@pytest.mark.asyncio
async def test_ensemble_mean_temp_computes_per_model_means(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    run_time = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    _insert_forecast_rows(session, "houston", run_time)
    session.commit()

    provider = EnsembleMeanTempProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    features = await provider.compute(run_time, ctx)
    gfs = next(item for item in features if item.subject_id == "houston:gfs")
    ecmwf = next(item for item in features if item.subject_id == "houston:ecmwf")
    assert gfs.status.value == "present"
    assert ecmwf.status.value == "present"
    assert gfs.value_numeric == Decimal("71")
    assert ecmwf.value_numeric == Decimal("71")
    assert gfs.value_jsonb == {"source": "gfs"}
    assert ecmwf.value_jsonb == {"source": "ecmwf"}


@pytest.mark.asyncio
async def test_ensemble_mean_temp_scopes_to_latest_valid_window(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    run_time = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    earlier_window = run_time - timedelta(hours=2)
    _insert_forecast_rows(
        session,
        "houston",
        run_time,
        valid_window_start=earlier_window,
        gfs_values=(Decimal("50"), Decimal("52")),
        ecmwf_values=(Decimal("50"), Decimal("52")),
    )
    for source, values in (
        (ForecastSource.GFS, [Decimal("70"), Decimal("72")]),
        (ForecastSource.ECMWF, [Decimal("68"), Decimal("74")]),
    ):
        for idx, value in enumerate(values, start=1):
            session.add(
                RawForecastRunRow(
                    id=f"houston-{source.value}-latest-{idx}",
                    source=source,
                    run_time=run_time,
                    ingested_at=run_time,
                    location_id="houston",
                    valid_window_start=run_time,
                    valid_window_end=run_time + timedelta(hours=1),
                    variable="temperature_2m",
                    value=value,
                    ensemble_member=idx,
                    raw_jsonb={},
                )
            )
    session.commit()

    provider = EnsembleMeanTempProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    features = await provider.compute(run_time, ctx)
    gfs = next(item for item in features if item.subject_id == "houston:gfs")
    assert gfs.status.value == "present"
    assert gfs.value_numeric == Decimal("71")


@pytest.mark.asyncio
async def test_ensemble_mean_temp_honors_explicit_target_window(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    run_time = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    earlier_window = run_time - timedelta(hours=2)
    _insert_forecast_rows(
        session,
        "houston",
        run_time,
        valid_window_start=earlier_window,
        gfs_values=(Decimal("50"), Decimal("52")),
        ecmwf_values=(Decimal("50"), Decimal("52")),
    )
    for source, values in (
        (ForecastSource.GFS, [Decimal("70"), Decimal("72")]),
        (ForecastSource.ECMWF, [Decimal("68"), Decimal("74")]),
    ):
        for idx, value in enumerate(values, start=1):
            session.add(
                RawForecastRunRow(
                    id=f"houston-{source.value}-latest-{idx}",
                    source=source,
                    run_time=run_time,
                    ingested_at=run_time,
                    location_id="houston",
                    valid_window_start=run_time,
                    valid_window_end=run_time + timedelta(hours=1),
                    variable="temperature_2m",
                    value=value,
                    ensemble_member=idx,
                    raw_jsonb={},
                )
            )
    session.commit()

    provider = EnsembleMeanTempProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
        target_window_start=earlier_window,
    )
    features = await provider.compute(run_time, ctx)
    gfs = next(item for item in features if item.subject_id == "houston:gfs")
    assert gfs.status.value == "present"
    assert gfs.value_numeric == Decimal("51")


@pytest.mark.asyncio
async def test_forecast_disagreement_is_model_spread(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    run_time = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    _insert_forecast_rows(
        session,
        "houston",
        run_time,
        ecmwf_values=(Decimal("66"), Decimal("70")),
    )
    session.commit()

    provider = ForecastDisagreementProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(run_time, ctx)
    houston = next(item for item in values if item.subject_id == "houston")
    assert houston.status.value == "present"
    assert houston.value_numeric == Decimal("3")


@pytest.mark.asyncio
async def test_kalshi_spread_from_snapshot(per_env_sqlite_urls: tuple[str, str]) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    session.add(
        ReferenceMarketRow(
            ticker="KXHIGHNY-25MAY28-T72",
            series="KXHIGHNY",
            title="test",
            status="open",
            raw_jsonb={},
        )
    )
    session.flush()
    from core.db.shared_models import RawMarketSnapshotRow

    session.add(
        RawMarketSnapshotRow(
            id="snap-1",
            ticker="KXHIGHNY-25MAY28-T72",
            as_of=as_of,
            bid_yes=Decimal("0.40"),
            ask_yes=Decimal("0.55"),
            mid_yes=Decimal("0.475"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    session.commit()

    provider = KalshiSpreadProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(as_of, ctx)
    spread = next(item for item in values if item.subject_id == "KXHIGHNY-25MAY28-T72")
    assert spread.status.value == "present"
    assert spread.value_numeric == Decimal("0.15")


@pytest.mark.asyncio
async def test_kalshi_spread_treats_active_market_as_tradable(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    ticker = "KXHIGHNY-26JUN08-B72.5"
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="KXHIGHNY",
            title="live active market",
            status="active",
            raw_jsonb={},
        )
    )
    session.flush()
    from core.db.shared_models import RawMarketSnapshotRow

    session.add(
        RawMarketSnapshotRow(
            id="snap-active",
            ticker=ticker,
            as_of=as_of,
            bid_yes=Decimal("0.40"),
            ask_yes=Decimal("0.55"),
            mid_yes=Decimal("0.475"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    session.commit()

    provider = KalshiSpreadProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(as_of, ctx)

    spread = next(item for item in values if item.subject_id == ticker)
    assert spread.status.value == "present"
    assert spread.value_numeric == Decimal("0.15")


def test_build_market_states_treats_active_market_with_blank_series_as_tradable(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    ticker = "KXHIGHNY-26JUN08-B72.5"
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="",
            title="live active market",
            status="active",
            strike_type="between",
            floor_strike=Decimal("72"),
            cap_strike=Decimal("73"),
            raw_jsonb={},
        )
    )
    session.flush()
    from core.db.shared_models import RawMarketSnapshotRow

    session.add(
        RawMarketSnapshotRow(
            id="snap-active-blank-series",
            ticker=ticker,
            as_of=as_of,
            bid_yes=Decimal("0.40"),
            ask_yes=Decimal("0.55"),
            mid_yes=Decimal("0.475"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    session.commit()

    markets = build_market_states(session, as_of)

    assert len(markets) == 1
    assert markets[0].ticker == ticker
    assert markets[0].series == "KXHIGHNY"
    assert markets[0].location_id == "nyc"
    assert markets[0].strike_type == "between"
    assert markets[0].floor_strike == Decimal("72")
    assert markets[0].cap_strike == Decimal("73")


def test_build_market_states_skips_expired_active_market(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    ticker = "KXHIGHNY-26JUN08-B72.5"
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="KXHIGHNY",
            title="expired active market",
            status="active",
            close_time=as_of - timedelta(minutes=1),
            raw_jsonb={},
        )
    )
    session.flush()
    from core.db.shared_models import RawMarketSnapshotRow

    session.add(
        RawMarketSnapshotRow(
            id="snap-expired-active",
            ticker=ticker,
            as_of=as_of - timedelta(minutes=2),
            bid_yes=Decimal("0.40"),
            ask_yes=Decimal("0.55"),
            mid_yes=Decimal("0.475"),
            bid_size=10,
            ask_size=10,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    session.commit()

    assert build_market_states(session, as_of) == []


def test_feature_providers_are_registered() -> None:
    names = {provider.name for provider in registered_feature_providers()}
    assert names == {
        "ensemble_mean_temp",
        "forecast_disagreement",
        "kalshi_spread",
        "weather_model_prob",
    }
