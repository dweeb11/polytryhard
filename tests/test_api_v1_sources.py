from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from core.api.main import create_app
from core.db.session import shared_session
from core.db.shared_enums import SourceRunStatus
from core.db.shared_models import SourceRunRow
from core.settings import Settings
from core.sources.seed import seed_locations_if_needed


def test_list_sources_returns_registered_sources(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = api_client.get("/v1/sources", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    names = {entry["name"] for entry in body}
    assert names == {"kalshi_markets", "open_meteo"}
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
