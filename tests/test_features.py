from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.contracts.feature import FeatureContext
from core.db.shared_enums import ForecastSource
from core.db.shared_models import RawForecastRunRow, ReferenceMarketRow
from core.features.ensemble_mean_temp import EnsembleMeanTempProvider
from core.features.forecast_disagreement import ForecastDisagreementProvider
from core.features.kalshi_spread import KalshiSpreadProvider
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def _insert_forecast_rows(
    session: Session,
    location_id: str,
    run_time: datetime,
    *,
    ecmwf_values: tuple[Decimal, Decimal] | None = None,
) -> None:
    ecmwf = ecmwf_values or (Decimal("68"), Decimal("74"))
    for source, values in (
        (ForecastSource.GFS, [Decimal("70"), Decimal("72")]),
        (ForecastSource.ECMWF, list(ecmwf)),
    ):
        for idx, value in enumerate(values, start=1):
            session.add(
                RawForecastRunRow(
                    id=f"{location_id}-{source.value}-{idx}",
                    source=source,
                    run_time=run_time,
                    ingested_at=run_time,
                    location_id=location_id,
                    valid_window_start=run_time,
                    valid_window_end=run_time,
                    variable="temperature_2m",
                    value=value,
                    ensemble_member=idx,
                    raw_jsonb={},
                )
            )


@pytest.mark.asyncio
async def test_ensemble_mean_temp_computes_location_mean(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    from sqlalchemy import create_engine

    engine = create_engine(shared_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
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
    values = await provider.compute(run_time, ctx)
    houston = next(item for item in values if item.subject_id == "houston")
    assert houston.status.value == "present"
    assert houston.value_numeric == Decimal("71")


@pytest.mark.asyncio
async def test_forecast_disagreement_is_model_spread(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    from sqlalchemy import create_engine

    engine = create_engine(shared_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
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
    shared_url, _ = per_env_sqlite_urls
    from sqlalchemy import create_engine

    engine = create_engine(shared_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
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
