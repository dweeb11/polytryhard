from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.contracts.feature import FeatureContext
from core.db.shared_enums import ForecastSource
from core.db.shared_models import (
    RawForecastRunRow,
    ReferenceLocationRow,
    ReferenceMarketRow,
)
from core.domain.feature import FeatureStatus
from core.features.queries import TEMPERATURE_VARIABLE, daily_max_by_member
from core.features.weather_model_prob import WeatherModelProbProvider
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def _session_from_shared_url(shared_url: str) -> Session:
    engine = create_engine(shared_url)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _forecast_row(
    *,
    id_: str,
    source: ForecastSource,
    run_time: datetime,
    location_id: str,
    valid_window_start: datetime,
    value: Decimal,
    ensemble_member: int | None,
    variable: str = TEMPERATURE_VARIABLE,
) -> RawForecastRunRow:
    return RawForecastRunRow(
        id=id_,
        source=source,
        run_time=run_time,
        ingested_at=run_time,
        location_id=location_id,
        valid_window_start=valid_window_start,
        valid_window_end=valid_window_start,
        variable=variable,
        value=value,
        ensemble_member=ensemble_member,
        raw_jsonb={},
    )


def test_daily_max_by_member_takes_max_per_member_within_window(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    run_time = datetime(2025, 5, 28, 0, tzinfo=UTC)

    session.add_all(
        [
            _forecast_row(
                id_="nyc-gfs-m0-10z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 10, tzinfo=UTC),
                value=Decimal("70"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-gfs-m0-18z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("74"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-gfs-m0-20z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 20, tzinfo=UTC),
                value=Decimal("72"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-gfs-m1-18z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("71"),
                ensemble_member=1,
            ),
            _forecast_row(
                id_="nyc-gfs-m1-20z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 20, tzinfo=UTC),
                value=Decimal("69"),
                ensemble_member=1,
            ),
            # Outside the (exclusive-end) window used in this test: proves exclusion.
            _forecast_row(
                id_="nyc-gfs-m0-next-day-02z",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 29, 2, tzinfo=UTC),
                value=Decimal("99"),
                ensemble_member=0,
            ),
        ]
    )
    session.commit()

    result = daily_max_by_member(
        session,
        location_id="nyc",
        source=ForecastSource.GFS,
        variable=TEMPERATURE_VARIABLE,
        as_of=datetime(2025, 5, 28, 12, tzinfo=UTC),
        day_start_utc=datetime(2025, 5, 28, 0, tzinfo=UTC),
        day_end_utc=datetime(2025, 5, 29, 0, tzinfo=UTC),
    )

    assert result == {0: Decimal("74"), 1: Decimal("71")}


def test_daily_max_by_member_only_uses_latest_run(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    older_run = datetime(2025, 5, 27, 0, tzinfo=UTC)
    newer_run = datetime(2025, 5, 28, 0, tzinfo=UTC)

    session.add_all(
        [
            _forecast_row(
                id_="nyc-gfs-old-m0",
                source=ForecastSource.GFS,
                run_time=older_run,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 10, tzinfo=UTC),
                value=Decimal("50"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-gfs-new-m0",
                source=ForecastSource.GFS,
                run_time=newer_run,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 10, tzinfo=UTC),
                value=Decimal("80"),
                ensemble_member=0,
            ),
        ]
    )
    session.commit()

    result = daily_max_by_member(
        session,
        location_id="nyc",
        source=ForecastSource.GFS,
        variable=TEMPERATURE_VARIABLE,
        as_of=datetime(2025, 5, 28, 12, tzinfo=UTC),
        day_start_utc=datetime(2025, 5, 28, 0, tzinfo=UTC),
        day_end_utc=datetime(2025, 5, 29, 0, tzinfo=UTC),
    )

    assert result == {0: Decimal("80")}


def test_daily_max_by_member_empty_when_no_run_at_or_before_as_of(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    future_run = datetime(2025, 5, 29, 0, tzinfo=UTC)

    session.add(
        _forecast_row(
            id_="nyc-gfs-future-m0",
            source=ForecastSource.GFS,
            run_time=future_run,
            location_id="nyc",
            valid_window_start=datetime(2025, 5, 29, 10, tzinfo=UTC),
            value=Decimal("80"),
            ensemble_member=0,
        )
    )
    session.commit()

    result = daily_max_by_member(
        session,
        location_id="nyc",
        source=ForecastSource.GFS,
        variable=TEMPERATURE_VARIABLE,
        as_of=datetime(2025, 5, 28, 12, tzinfo=UTC),
        day_start_utc=datetime(2025, 5, 28, 0, tzinfo=UTC),
        day_end_utc=datetime(2025, 5, 29, 0, tzinfo=UTC),
    )

    assert result == {}


def _seed_nyc_market(
    session: Session,
    *,
    ticker: str = "KXHIGHNY-25MAY28-T73",
    strike_type: str | None = "greater",
    floor_strike: Decimal | None = None,
    cap_strike: Decimal | None = Decimal("73"),
) -> None:
    seed_locations_if_needed(session)
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="KXHIGHNY",
            title="test",
            status="open",
            strike_type=strike_type,
            floor_strike=floor_strike,
            cap_strike=cap_strike,
            raw_jsonb={},
        )
    )
    session.commit()


def _seed_nyc_members(session: Session, run_time: datetime) -> None:
    # NYC local midnight on 2025-05-28 is 2025-05-28T04:00Z (EDT, UTC-4).
    # Daily maxes vs "greater than 73": 74 (hit), 75 (hit), 71 (miss), 70 (miss).
    session.add_all(
        [
            _forecast_row(
                id_="nyc-gfs-m0",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("74"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-gfs-m1",
                source=ForecastSource.GFS,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("71"),
                ensemble_member=1,
            ),
            _forecast_row(
                id_="nyc-ecmwf-m0",
                source=ForecastSource.ECMWF,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("75"),
                ensemble_member=0,
            ),
            _forecast_row(
                id_="nyc-ecmwf-m1",
                source=ForecastSource.ECMWF,
                run_time=run_time,
                location_id="nyc",
                valid_window_start=datetime(2025, 5, 28, 18, tzinfo=UTC),
                value=Decimal("70"),
                ensemble_member=1,
            ),
        ]
    )
    session.commit()


@pytest.mark.asyncio
async def test_weather_model_prob_present(per_env_sqlite_urls: tuple[str, str]) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    _seed_nyc_market(session)
    run_time = datetime(2025, 5, 28, 6, tzinfo=UTC)
    _seed_nyc_members(session, run_time)

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-25MAY28-T73"]

    assert fv.status == FeatureStatus.PRESENT
    assert fv.value_numeric == (Decimal(2) + 1) / (Decimal(4) + 2)
    assert fv.value_jsonb is not None
    assert fv.value_jsonb["nMembers"] == 4
    assert fv.value_jsonb["gfsMembers"] == 2
    assert fv.value_jsonb["ecmwfMembers"] == 2
    assert fv.value_jsonb["gfsMeanMax"] == pytest.approx(72.5)
    assert fv.value_jsonb["ecmwfMeanMax"] == pytest.approx(72.5)


@pytest.mark.asyncio
async def test_weather_model_prob_missing_without_strikes(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    _seed_nyc_market(
        session,
        ticker="KXHIGHNY-25MAY28-T73",
        strike_type=None,
        floor_strike=None,
        cap_strike=None,
    )
    run_time = datetime(2025, 5, 28, 6, tzinfo=UTC)
    _seed_nyc_members(session, run_time)

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-25MAY28-T73"]

    assert fv.status == FeatureStatus.MISSING
    assert fv.reason == "no strike metadata"


@pytest.mark.asyncio
async def test_weather_model_prob_missing_without_ensemble_members(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    _seed_nyc_market(session)

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-25MAY28-T73"]

    assert fv.status == FeatureStatus.MISSING
    assert fv.reason == "no ensemble members for target day"


@pytest.mark.asyncio
async def test_weather_model_prob_missing_unparsable_ticker_date(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    _seed_nyc_market(session, ticker="KXHIGHNY-BOGUS-T73")

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-BOGUS-T73"]

    assert fv.status == FeatureStatus.MISSING
    assert fv.reason == "unparsable target date"


@pytest.mark.asyncio
async def test_weather_model_prob_missing_unknown_location(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    ticker = "KXHIGHZZZ-25MAY28-T73"
    session.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="KXHIGHZZZ",
            title="test",
            status="open",
            strike_type="greater",
            cap_strike=Decimal("73"),
            raw_jsonb={},
        )
    )
    session.commit()

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject[ticker]

    assert fv.status == FeatureStatus.MISSING
    assert fv.reason == "unknown location"


@pytest.mark.asyncio
async def test_weather_model_prob_missing_invalid_timezone(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    seed_locations_if_needed(session)
    nyc = session.get(ReferenceLocationRow, "nyc")
    assert nyc is not None
    nyc.timezone = "Not/AZone"
    session.add(nyc)
    _seed_nyc_market(session)
    session.commit()

    provider = WeatherModelProbProvider()
    ctx = FeatureContext(
        request_id="test",
        settings=Settings(REQUIRE_DBS=False),
        session=session,
    )
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-25MAY28-T73"]

    assert fv.status == FeatureStatus.MISSING
    assert fv.reason == "invalid timezone"
