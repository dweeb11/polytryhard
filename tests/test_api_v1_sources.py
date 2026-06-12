from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from core.api.main import create_app
from core.db.session import shared_session
from core.db.shared_enums import SourceRunStatus
from core.db.shared_models import SourceRunRow
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def test_list_sources_requires_auth(api_client: TestClient) -> None:
    response = api_client.get("/v1/sources")
    assert response.status_code == 401


def test_list_sources_invalid_token_rejected(api_client: TestClient) -> None:
    response = api_client.get(
        "/v1/sources",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_list_sources_returns_registered_sources(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get("/v1/sources", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    names = {entry["name"] for entry in body}
    assert names == {"kalshi_markets", "kalshi_resolution", "open_meteo"}
    kalshi = next(entry for entry in body if entry["name"] == "kalshi_markets")
    assert kalshi["enabled"] is False
    assert kalshi["status"] is None
    assert kalshi["rowsLastRun"] is None


def test_list_sources_reads_latest_source_run(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    with shared_session(settings) as session:
        seed_locations_if_needed(session)
        now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
        session.add(
            SourceRunRow(
                id=str(uuid4()),
                source_name="open_meteo",
                started_at=now,
                finished_at=now,
                status=SourceRunStatus.OK,
                rows_written=42,
                error_text=None,
                request_id="req_test",
            )
        )
        session.commit()

    client = TestClient(create_app(settings))
    response = client.get("/v1/sources", headers={"Authorization": "Bearer dev-token"})
    assert response.status_code == 200
    open_meteo = next(entry for entry in response.json() if entry["name"] == "open_meteo")
    assert open_meteo["status"] == "ok"
    assert open_meteo["rowsLastRun"] == 42


def test_list_sources_latest_error_preserves_last_success_at(
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
    ok_at = datetime(2026, 5, 28, 10, 0, tzinfo=UTC)
    error_at = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    with shared_session(settings) as session:
        seed_locations_if_needed(session)
        session.add(
            SourceRunRow(
                id=str(uuid4()),
                source_name="open_meteo",
                started_at=ok_at,
                finished_at=ok_at,
                status=SourceRunStatus.OK,
                rows_written=42,
                error_text=None,
                request_id="req_ok",
            )
        )
        session.add(
            SourceRunRow(
                id=str(uuid4()),
                source_name="open_meteo",
                started_at=error_at,
                finished_at=error_at,
                status=SourceRunStatus.ERROR,
                rows_written=0,
                error_text="fetch failed",
                request_id="req_error",
            )
        )
        session.commit()

    client = TestClient(create_app(settings))
    response = client.get("/v1/sources", headers={"Authorization": "Bearer dev-token"})
    assert response.status_code == 200
    open_meteo = next(entry for entry in response.json() if entry["name"] == "open_meteo")
    assert open_meteo["status"] == "error"
    assert open_meteo["lastSuccessAt"] == "2026-05-28T10:00:00.000Z"
    assert open_meteo["lastRunAt"] == "2026-05-28T12:00:00.000Z"
    assert open_meteo["lastError"] == "fetch failed"
