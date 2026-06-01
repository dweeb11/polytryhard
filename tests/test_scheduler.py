import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from core.clock import Clock, FakeClock
from core.contracts.source import FetchResult, ReferenceLocation, SourceContext
from core.db.shared_enums import SourceRunStatus
from core.db.shared_models import RawForecastRunRow, SourceRunRow
from core.scheduler import Scheduler, _cycle_interval_seconds
from core.settings import Settings
from core.sources.kalshi import KalshiMarketsSource
from core.sources.open_meteo import OpenMeteoSource
from core.sources.persistence import SourceHealthTracker
from core.sources.seed import seed_locations_if_needed

CASSETTES = Path(__file__).resolve().parent / "cassettes"
ENSEMBLE_PREFIX = "https://ensemble-api.open-meteo.com/v1/ensemble"
ROWS_PER_FETCH = 4
SEED_LOCATION_COUNT = 6
MODELS_PER_LOCATION = 2
EXPECTED_FORECAST_ROWS = SEED_LOCATION_COUNT * MODELS_PER_LOCATION * ROWS_PER_FETCH


@dataclass
class FakeResponse:
    status_code: int
    payload: dict[str, object]

    def json(self) -> dict[str, object]:
        return self.payload


class FakeHttpClient:
    def __init__(self, routes: dict[str, FakeResponse]) -> None:
        self._routes = routes

    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> FakeResponse:
        for prefix, response in self._routes.items():
            if url.startswith(prefix):
                return response
        raise AssertionError(f"unexpected url: {url}")


def _open_meteo_context(
    *,
    settings: Settings,
    http: FakeHttpClient,
    locations: tuple[ReferenceLocation, ...] = (),
) -> SourceContext:
    return SourceContext(
        request_id="test",
        settings=settings,
        locations=locations,
        markets=(),
        http=http,
    )


def _houston_location() -> ReferenceLocation:
    return ReferenceLocation(
        id="houston",
        station_code="KIAH",
        name="Houston",
        lat=Decimal("29.9844"),
        lon=Decimal("-95.3414"),
        timezone="America/Chicago",
        source="curated",
    )


@pytest.mark.asyncio
async def test_scheduler_persists_open_meteo_rows(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine(shared_url)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_locations_if_needed(session)

    ensemble = json.loads((CASSETTES / "open_meteo_ensemble.json").read_text())
    http = FakeHttpClient(
        {
            ENSEMBLE_PREFIX: FakeResponse(200, ensemble),
        }
    )
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
    source = OpenMeteoSource()

    from core.db.session import shared_session
    from core.sources.persistence import load_locations, load_markets

    with shared_session(settings) as db:
        ctx = SourceContext(
            request_id="test_tick",
            settings=settings,
            locations=load_locations(db),
            markets=load_markets(db),
            http=http,
        )
        result = await source.fetch(clock, ctx)
        assert result.rows_written == EXPECTED_FORECAST_ROWS
        assert len(result.forecast_runs) == EXPECTED_FORECAST_ROWS

        from core.sources.persistence import persist_fetch_result

        persist_fetch_result(
            db,
            source_name=source.name,
            request_id="test_tick",
            started_at=clock.now(),
            finished_at=clock.now(),
            result=result,
        )
        run_count = db.scalar(select(func.count()).select_from(SourceRunRow))
        assert run_count == 1
        forecast_count = db.scalar(select(func.count()).select_from(RawForecastRunRow))
        assert forecast_count == EXPECTED_FORECAST_ROWS


@dataclass
class _StubSource:
    name: str
    schedule_seconds: int = 300

    def is_enabled(self, _settings: Settings) -> bool:
        return True

    async def fetch(self, _clock: Clock, _ctx: SourceContext) -> FetchResult:
        return FetchResult()


@pytest.mark.asyncio
async def test_run_cycle_invokes_engine_tick_once(
    per_env_sqlite_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    tick_calls: list[str] = []

    async def track_tick(**kwargs: object) -> dict[str, int]:
        request_id = kwargs.get("request_id")
        assert isinstance(request_id, str)
        tick_calls.append(request_id)
        return {"features": 0, "signals": 0, "orders": 0}

    monkeypatch.setattr("core.engine.tick.run_engine_tick", track_tick)
    monkeypatch.setattr(
        "core.scheduler.enabled_sources",
        lambda _settings: [_StubSource(name="stub_a"), _StubSource(name="stub_b")],
    )

    scheduler = Scheduler.create(
        settings,
        clock=FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
    )
    await scheduler.run_cycle()

    assert len(tick_calls) == 1
    assert tick_calls[0].startswith("cycle_")


@pytest.mark.asyncio
async def test_ingest_source_records_failure_on_fetch_error(
    per_env_sqlite_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )

    async def fail_fetch(
        _self: OpenMeteoSource, _clock: FakeClock, _ctx: SourceContext
    ) -> FetchResult:
        raise RuntimeError("fetch failed")

    monkeypatch.setattr(OpenMeteoSource, "fetch", fail_fetch)

    scheduler = Scheduler.create(
        settings,
        clock=FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
    )
    await scheduler._ingest_source(OpenMeteoSource())

    health = scheduler.health.get("open_meteo")
    assert health.status == SourceRunStatus.ERROR
    assert health.last_error is not None
    assert "fetch failed" in health.last_error
    assert health.last_success_at is None


@pytest.mark.asyncio
async def test_run_cycle_keeps_source_health_when_engine_tick_raises(
    per_env_sqlite_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )

    async def fake_fetch(
        _self: OpenMeteoSource, _clock: FakeClock, _ctx: SourceContext
    ) -> FetchResult:
        return FetchResult()

    async def fail_tick(**_kwargs: object) -> None:
        raise RuntimeError("engine tick failed")

    monkeypatch.setattr(OpenMeteoSource, "fetch", fake_fetch)
    monkeypatch.setattr("core.engine.tick.run_engine_tick", fail_tick)
    monkeypatch.setattr(
        "core.scheduler.enabled_sources",
        lambda _settings: [OpenMeteoSource()],
    )

    scheduler = Scheduler.create(
        settings,
        clock=FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
    )
    with pytest.raises(RuntimeError, match="engine tick failed"):
        await scheduler.run_cycle()

    health = scheduler.health.get("open_meteo")
    assert health.status == SourceRunStatus.OK
    assert health.last_success_at is not None
    assert scheduler.cycle_health.last_cycle_error == "engine tick failed"
    assert scheduler.cycle_health.last_cycle_at is not None


@pytest.mark.asyncio
async def test_run_cycle_records_cycle_health_on_success(
    per_env_sqlite_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )

    async def ok_tick(**_kwargs: object) -> dict[str, int]:
        return {"features": 0, "signals": 0, "orders": 0}

    monkeypatch.setattr("core.engine.tick.run_engine_tick", ok_tick)
    monkeypatch.setattr(
        "core.scheduler.enabled_sources",
        lambda _settings: [_StubSource(name="stub_a")],
    )

    scheduler = Scheduler.create(
        settings,
        clock=FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC)),
    )
    await scheduler.run_cycle()

    assert scheduler.cycle_health.last_cycle_error is None
    assert scheduler.cycle_health.last_cycle_success_at is not None


def test_cycle_interval_uses_slowest_source_schedule() -> None:
    fast = _StubSource(name="fast", schedule_seconds=60)
    slow = _StubSource(name="slow", schedule_seconds=3600)
    assert _cycle_interval_seconds([fast, slow]) == 3600.0


def test_health_tracker_marks_degraded_after_threshold() -> None:
    tracker = SourceHealthTracker(failure_threshold=2)
    finished = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    tracker.record_failure("open_meteo", finished_at=finished, error="boom")
    assert tracker.get("open_meteo").status == SourceRunStatus.ERROR
    tracker.record_failure("open_meteo", finished_at=finished, error="boom")
    assert tracker.get("open_meteo").status == SourceRunStatus.DEGRADED


@pytest.mark.asyncio
async def test_open_meteo_empty_locations_reports_degraded() -> None:
    source = OpenMeteoSource()
    settings = Settings(REQUIRE_DBS=False, SCHEDULER_ENABLED=False)
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
    ctx = _open_meteo_context(settings=settings, http=FakeHttpClient({}))
    result = await source.fetch(clock, ctx)
    assert result.status == SourceRunStatus.DEGRADED
    assert result.error_text == "No reference locations seeded"


@pytest.mark.asyncio
async def test_open_meteo_http_404_reports_degraded() -> None:
    source = OpenMeteoSource()
    settings = Settings(REQUIRE_DBS=False, SCHEDULER_ENABLED=False)
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
    http = FakeHttpClient({ENSEMBLE_PREFIX: FakeResponse(404, {})})
    ctx = _open_meteo_context(
        settings=settings,
        http=http,
        locations=(_houston_location(),),
    )
    result = await source.fetch(clock, ctx)
    assert result.status == SourceRunStatus.DEGRADED
    assert result.error_text == "Open-Meteo HTTP 404 for houston"


@pytest.mark.asyncio
async def test_open_meteo_empty_hourly_reports_degraded() -> None:
    source = OpenMeteoSource()
    settings = Settings(REQUIRE_DBS=False, SCHEDULER_ENABLED=False)
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
    http = FakeHttpClient(
        {ENSEMBLE_PREFIX: FakeResponse(200, {"hourly": {"time": []}})}
    )
    ctx = _open_meteo_context(
        settings=settings,
        http=http,
        locations=(_houston_location(),),
    )
    result = await source.fetch(clock, ctx)
    assert result.status == SourceRunStatus.DEGRADED
    assert result.error_text == "Open-Meteo returned no forecast rows"


@pytest.mark.asyncio
async def test_kalshi_unconfigured_reports_degraded() -> None:
    source = KalshiMarketsSource()
    settings = Settings(REQUIRE_DBS=False, SCHEDULER_ENABLED=False)
    clock = FakeClock(start=datetime(2026, 5, 28, 12, 0, tzinfo=UTC))
    ctx = SourceContext(
        request_id="test",
        settings=settings,
        locations=(),
        markets=(),
        http=FakeHttpClient({}),
    )
    result = await source.fetch(clock, ctx)
    assert result.status == SourceRunStatus.DEGRADED
