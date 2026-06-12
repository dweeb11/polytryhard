from pathlib import Path

from fastapi.testclient import TestClient

from core.api.main import create_app
from core.scheduler import CycleHealth, Scheduler
from core.settings import Settings


def test_healthz_reports_version_request_id_and_database_status() -> None:
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["version"]
    assert data["git_sha"]
    assert data["request_id"].startswith("req_")
    assert data["db_shared"] == "unconfigured"
    assert data["db_per_env"] == "unconfigured"
    assert response.headers["x-request-id"] == data["request_id"]


def test_healthz_returns_json_and_request_id_when_database_is_down(tmp_path: Path) -> None:
    missing_parent = tmp_path / "missing" / "shared.db"
    settings = Settings(
        REQUIRE_DBS=False,
        DATABASE_URL_SHARED=f"sqlite:///{missing_parent}",
        DATABASE_URL_PER_ENV=None,
    )
    client = TestClient(create_app(settings))

    response = client.get("/healthz")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db_shared"] == "down"
    assert data["db_per_env"] == "unconfigured"
    assert data["request_id"].startswith("req_")
    assert response.headers["x-request-id"] == data["request_id"]


def test_healthz_reports_pending_scheduler_cycle_when_scheduler_has_not_run(
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
    app = create_app(settings)
    app.state.scheduler = Scheduler.create(settings)
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["scheduler_cycle"] == {
        "status": "pending",
        "last_error": None,
        "last_cycle_at": None,
        "last_success_at": None,
    }


def test_healthz_degrades_when_scheduler_cycle_has_error(
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
    app = create_app(settings)
    app.state.scheduler = Scheduler.create(settings)
    app.state.scheduler.cycle_health = CycleHealth(last_cycle_error="engine tick failed")
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["scheduler_cycle"]["status"] == "error"
    assert data["scheduler_cycle"]["last_error"] == "scheduler cycle failed"


def test_healthz_degrades_when_scheduler_cycle_is_pending_and_enabled(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=True,
    )
    app = create_app(settings)
    app.state.scheduler = Scheduler.create(settings)
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["scheduler_cycle"]["status"] == "pending"


def test_healthz_openapi_schema_includes_scheduler_cycle() -> None:
    schema = create_app(Settings(REQUIRE_DBS=False)).openapi()
    response_schema = schema["paths"]["/healthz"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert response_schema["$ref"] == "#/components/schemas/HealthzResponse"
    degraded_response_schema = schema["paths"]["/healthz"]["get"]["responses"]["503"]["content"][
        "application/json"
    ]["schema"]
    assert degraded_response_schema["$ref"] == "#/components/schemas/HealthzResponse"
    healthz_schema = schema["components"]["schemas"]["HealthzResponse"]
    assert "scheduler_cycle" in healthz_schema["properties"]
