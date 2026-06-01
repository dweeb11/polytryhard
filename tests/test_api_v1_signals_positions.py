from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import StrategyInstanceRow
from core.db.shared_models import RawMarketSnapshotRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide
from core.ledger import writer
from core.ledger.seed import seed_strategies_if_needed
from core.utils.time import utc_now


def test_list_signals_empty(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    response = api_client.get("/v1/signals", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_positions_empty(api_client: TestClient, auth_headers: dict[str, str]) -> None:
    response = api_client.get("/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_positions_unrealized_from_snapshot_mid(
    per_env_sqlite_urls: tuple[str, str],
    auth_headers: dict[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    from core.api.main import create_app
    from core.settings import Settings

    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    shared = sessionmaker(bind=create_engine(shared_url), expire_on_commit=False)()

    seed_strategies_if_needed(per_env, request_id="seed-positions-api")
    now = utc_now()
    writer.open_paper_position(
        per_env,
        strategy_name="weather_ensemble_disagreement",
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=50,
        price=Decimal("0.42"),
        cost_basis_cents=2_100,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted"},
        actor=AuditActor.USER,
        request_id="open-yes",
    )
    writer.open_paper_position(
        per_env,
        strategy_name="weather_stale_quote",
        order_ticker="KXHIGHCHI-25MAY28-T68",
        side=PositionSide.NO,
        qty=30,
        price=Decimal("0.38"),
        cost_basis_cents=1_140,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted"},
        actor=AuditActor.USER,
        request_id="open-no",
    )
    per_env.commit()

    for ticker, series in (
        ("KXHIGHNY-25MAY28-T72", "KXHIGHNY"),
        ("KXHIGHCHI-25MAY28-T68", "KXHIGHCHI"),
    ):
        shared.add(
            ReferenceMarketRow(
                ticker=ticker,
                series=series,
                title="test",
                status="open",
                raw_jsonb={},
            )
        )
    shared.add(
        RawMarketSnapshotRow(
            id="snap-ny",
            ticker="KXHIGHNY-25MAY28-T72",
            as_of=now,
            bid_yes=Decimal("0.43"),
            ask_yes=Decimal("0.45"),
            mid_yes=Decimal("0.44"),
            bid_size=None,
            ask_size=None,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    shared.add(
        RawMarketSnapshotRow(
            id="snap-chi",
            ticker="KXHIGHCHI-25MAY28-T68",
            as_of=now,
            bid_yes=Decimal("0.60"),
            ask_yes=Decimal("0.62"),
            mid_yes=Decimal("0.61"),
            bid_size=None,
            ask_size=None,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    shared.commit()
    per_env.close()
    shared.close()

    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    by_ticker = {row["ticker"]: row for row in response.json()}
    assert by_ticker["KXHIGHNY-25MAY28-T72"]["unrealizedPnlCents"] == 100
    assert by_ticker["KXHIGHCHI-25MAY28-T68"]["unrealizedPnlCents"] == 30


def test_list_positions_unrealized_fail_closed_without_snapshot(
    per_env_sqlite_urls: tuple[str, str],
    auth_headers: dict[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    from core.api.main import create_app
    from core.settings import Settings

    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    seed_strategies_if_needed(per_env, request_id="seed-positions-missing")
    writer.open_paper_position(
        per_env,
        strategy_name="weather_ensemble_disagreement",
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.50"),
        cost_basis_cents=500,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted"},
        actor=AuditActor.USER,
        request_id="open-missing-snapshot",
    )
    per_env.commit()
    per_env.close()

    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["unrealizedPnlCents"] == 0


def test_list_positions_unrealized_fail_closed_when_snapshot_stale(
    per_env_sqlite_urls: tuple[str, str],
    auth_headers: dict[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    from core.api.main import create_app
    from core.settings import Settings

    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    shared = sessionmaker(bind=create_engine(shared_url), expire_on_commit=False)()
    seed_strategies_if_needed(per_env, request_id="seed-positions-stale")
    writer.open_paper_position(
        per_env,
        strategy_name="weather_ensemble_disagreement",
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.50"),
        cost_basis_cents=500,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted"},
        actor=AuditActor.USER,
        request_id="open-stale-snapshot",
    )
    per_env.commit()
    stale_as_of = utc_now() - timedelta(hours=2)
    shared.add(
        ReferenceMarketRow(
            ticker="KXHIGHNY-25MAY28-T72",
            series="KXHIGHNY",
            title="test",
            status="open",
            raw_jsonb={},
        )
    )
    shared.add(
        RawMarketSnapshotRow(
            id="snap-stale",
            ticker="KXHIGHNY-25MAY28-T72",
            as_of=stale_as_of,
            bid_yes=Decimal("0.70"),
            ask_yes=Decimal("0.72"),
            mid_yes=Decimal("0.71"),
            bid_size=None,
            ask_size=None,
            last_trade_price=None,
            last_trade_size=None,
            source_run_id=None,
            raw_jsonb={},
        )
    )
    shared.commit()
    per_env.close()
    shared.close()

    with TestClient(create_app(settings)) as client:
        response = client.get("/v1/positions", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()[0]["unrealizedPnlCents"] == 0


def test_seed_includes_strategy_threshold_keys(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-thresholds")
    ensemble = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    stale = session.get(StrategyInstanceRow, "weather_stale_quote")
    assert ensemble is not None
    assert stale is not None
    assert ensemble.config_jsonb["disagreementThreshold"] == 2.0
    assert ensemble.config_jsonb["spreadMarginMultiplier"] == 1.5
    assert ensemble.config_jsonb["confidenceFloor"] == 0.55
    assert stale.config_jsonb["wideSpreadThreshold"] == 0.08
    assert stale.config_jsonb["confidenceFloor"] == 0.55
    session.close()
