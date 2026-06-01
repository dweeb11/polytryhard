import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.api.main import create_app
from core.migrations import run_upgrade
from core.settings import Settings

# Tests run without real Postgres unless Testcontainers provides URLs.
os.environ.setdefault("REQUIRE_DBS", "0")
os.environ.setdefault("CONTROL_PLANE_TOKEN", "dev-token")


@event.listens_for(Engine, "connect")
def _sqlite_enable_foreign_keys(dbapi_connection, connection_record) -> None:
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


@pytest.fixture
def per_env_sqlite_urls(tmp_path: Path) -> tuple[str, str]:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    per_env_url = f"sqlite:///{tmp_path / 'per_env.db'}"
    run_upgrade("shared", shared_url)
    run_upgrade("per_env", per_env_url)
    return shared_url, per_env_url


@pytest.fixture
def per_env_session_factory(per_env_sqlite_urls: tuple[str, str]) -> sessionmaker[Session]:
    _, per_env_url = per_env_sqlite_urls
    engine = create_engine(per_env_url)
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def api_settings(per_env_sqlite_urls: tuple[str, str]) -> Settings:
    shared_url, per_env_url = per_env_sqlite_urls
    return Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )


@pytest.fixture
def api_client(api_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(create_app(api_settings)) as client:
        yield client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer dev-token"}
