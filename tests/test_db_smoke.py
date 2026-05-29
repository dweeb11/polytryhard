from pathlib import Path
from shutil import which

import psycopg
import pytest
from sqlalchemy import BigInteger, text
from testcontainers.postgres import PostgresContainer

from core.api.main import create_app
from core.db.types import Cents
from core.migrations import run_upgrade
from core.settings import Settings


def test_cents_uses_bigint() -> None:
    assert isinstance(Cents().type, BigInteger)


def test_migrations_apply_to_fresh_sqlite_databases(tmp_path: Path) -> None:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    per_env_url = f"sqlite:///{tmp_path / 'per_env.db'}"

    run_upgrade("shared", shared_url)
    run_upgrade("per_env", per_env_url)

    from sqlalchemy import create_engine

    shared_engine = create_engine(shared_url)
    with shared_engine.connect() as conn:
        shared_rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('reference_location', 'reference_market', 'source_run') "
                "ORDER BY name"
            )
        ).all()

    assert [tuple(row) for row in shared_rows] == [
        ("reference_location",),
        ("reference_market",),
        ("source_run",),
    ]

    per_env_engine = create_engine(per_env_url)
    with per_env_engine.connect() as conn:
        per_env_rows = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name IN ('audit_event', 'strategy_instance', 'system_state') "
                "ORDER BY name"
            )
        ).all()

    assert [tuple(row) for row in per_env_rows] == [
        ("audit_event",),
        ("strategy_instance",),
        ("system_state",),
    ]


@pytest.mark.skipif(which("docker") is None, reason="Docker is required for Testcontainers")
def test_migrations_and_healthz_run_against_postgres() -> None:
    with PostgresContainer(
        image="postgres:16",
        username="polytryhard",
        password="polytryhard",
        dbname="polytryhard_shared",
        driver="psycopg",
    ) as postgres:
        shared_url = postgres.get_connection_url()
        admin_url = shared_url.replace("+psycopg", "")
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute("CREATE DATABASE polytryhard_staging")

        per_env_url = shared_url.replace("polytryhard_shared", "polytryhard_staging")
        run_upgrade("shared", shared_url)
        run_upgrade("per_env", per_env_url)

        from fastapi.testclient import TestClient

        settings = Settings(
            REQUIRE_DBS=False,
            APP_VERSION="test",
            GIT_SHA="test-sha",
            DATABASE_URL_SHARED=shared_url,
            DATABASE_URL_PER_ENV=per_env_url,
            CONTROL_PLANE_TOKEN="test-token",
            SCHEDULER_ENABLED=False,
        )
        response = TestClient(create_app(settings)).get("/healthz")

    assert response.status_code == 200
    assert response.json()["db_shared"] == "ok"
    assert response.json()["db_per_env"] == "ok"
