from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.db.shared_enums import FeatureSubjectKind
from core.db.shared_models import FeatureValueRow
from core.migrations import run_upgrade

EXPECTED_TABLES = {
    "reference_location",
    "reference_market",
    "raw_market_snapshot",
    "raw_forecast_run",
    "source_run",
    "feature_value",
}


def test_shared_migration_creates_expected_tables(tmp_path: Path) -> None:
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
    feature_value_indexes = {ix["name"] for ix in inspector.get_indexes("feature_value")}

    assert "ix_raw_market_snapshot_ticker_as_of" in snapshot_indexes
    assert "ix_raw_forecast_run_source_loc_var_run" in forecast_indexes
    assert "ix_source_run_source_started" in source_run_indexes
    assert "ix_feature_value_provider_subject_as_of" in feature_value_indexes


def test_feature_value_unique_constraint_present(tmp_path: Path) -> None:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    run_upgrade("shared", shared_url)

    engine = create_engine(shared_url)
    unique_constraints = inspect(engine).get_unique_constraints("feature_value")
    constraint_names = {uc["name"] for uc in unique_constraints}

    assert "uq_feature_value_provider_subject_as_of" in constraint_names


def test_feature_value_unique_constraint_enforced(tmp_path: Path) -> None:
    shared_url = f"sqlite:///{tmp_path / 'shared.db'}"
    run_upgrade("shared", shared_url)

    session = sessionmaker(bind=create_engine(shared_url), expire_on_commit=False)()
    as_of = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    row_kwargs = {
        "provider_name": "ensemble_mean_temp",
        "provider_version": "1.0.0",
        "subject_kind": FeatureSubjectKind.LOCATION,
        "subject_id": "loc-1",
        "as_of": as_of,
        "value_numeric": Decimal("72.500000"),
        "input_hash": "a" * 64,
        "computed_at": as_of,
    }

    session.add(FeatureValueRow(id="00000000-0000-4000-8000-000000000001", **row_kwargs))
    session.commit()

    session.add(FeatureValueRow(id="00000000-0000-4000-8000-000000000002", **row_kwargs))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
