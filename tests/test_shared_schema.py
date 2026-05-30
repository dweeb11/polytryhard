from pathlib import Path

from sqlalchemy import create_engine, inspect

from core.migrations import run_upgrade

EXPECTED_TABLES = {
    "reference_location",
    "reference_market",
    "raw_market_snapshot",
    "raw_forecast_run",
    "source_run",
    "feature_value",
}


def test_shared_migration_creates_ingestion_tables(tmp_path: Path) -> None:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    run_upgrade("shared", shared_url)

    engine = create_engine(shared_url)
    table_names = set(inspect(engine).get_table_names())

    assert EXPECTED_TABLES <= table_names


def test_shared_migration_indexes_present(tmp_path: Path) -> None:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    run_upgrade("shared", shared_url)

    engine = create_engine(shared_url)
    inspector = inspect(engine)
    snapshot_indexes = {ix["name"] for ix in inspector.get_indexes("raw_market_snapshot")}
    forecast_indexes = {ix["name"] for ix in inspector.get_indexes("raw_forecast_run")}
    source_run_indexes = {ix["name"] for ix in inspector.get_indexes("source_run")}

    assert "ix_raw_market_snapshot_ticker_as_of" in snapshot_indexes
    assert "ix_raw_forecast_run_source_loc_var_run" in forecast_indexes
    assert "ix_source_run_source_started" in source_run_indexes
