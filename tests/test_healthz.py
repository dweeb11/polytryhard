import os
from pathlib import Path

from fastapi.testclient import TestClient

from core.api.main import create_app
from core.settings import Settings


def test_healthz_reports_version_request_id_and_database_status() -> None:
    os.environ["REQUIRE_DBS"] = "0"
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
    os.environ["REQUIRE_DBS"] = "0"
    missing_parent = tmp_path / "missing" / "shared.db"
    settings = Settings(
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
