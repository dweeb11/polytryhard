from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import cast
from uuid import uuid4

from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core.db.shared_enums import FeatureSubjectKind
from core.db.shared_models import FeatureValueRow
from core.domain.feature import FeatureValue
from core.utils.time import utc_now


def _new_id() -> str:
    return str(uuid4())


def _input_hash(feature: FeatureValue) -> str:
    payload = {
        "provider": feature.provider_name,
        "version": feature.provider_version,
        "subjectKind": feature.subject_kind,
        "subjectId": feature.subject_id,
        "status": feature.status.value,
        "asOf": feature.as_of.isoformat() if feature.as_of else None,
        "valueNumeric": str(feature.value_numeric) if feature.value_numeric is not None else None,
        "valueJsonb": feature.value_jsonb,
        "reason": feature.reason,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _row_values(feature: FeatureValue, *, computed_at: datetime) -> dict[str, object]:
    return {
        "id": _new_id(),
        "provider_name": feature.provider_name,
        "provider_version": feature.provider_version,
        "subject_kind": FeatureSubjectKind(feature.subject_kind),
        "subject_id": feature.subject_id,
        "as_of": feature.as_of,
        "value_numeric": feature.value_numeric,
        "value_jsonb": feature.value_jsonb,
        "input_hash": _input_hash(feature),
        "computed_at": computed_at,
    }


def _upsert_feature_value(session: Session, row: dict[str, object]) -> None:
    table = cast(Table, FeatureValueRow.__table__)
    update_cols = {
        "value_numeric": row["value_numeric"],
        "value_jsonb": row["value_jsonb"],
        "input_hash": row["input_hash"],
        "computed_at": row["computed_at"],
    }
    dialect_name = session.get_bind().dialect.name

    if dialect_name == "postgresql":
        session.execute(
            pg_insert(table).values(**row).on_conflict_do_update(
                constraint="uq_feature_value_provider_subject_as_of",
                set_=update_cols,
            )
        )
    elif dialect_name == "sqlite":
        session.execute(
            sqlite_insert(table).values(**row).on_conflict_do_update(
                index_elements=[
                    "provider_name",
                    "provider_version",
                    "subject_kind",
                    "subject_id",
                    "as_of",
                ],
                set_=update_cols,
            )
        )
    else:
        msg = f"unsupported dialect for feature upsert: {dialect_name}"
        raise RuntimeError(msg)


def persist_feature_values(session: Session, features: list[FeatureValue]) -> int:
    now = utc_now()
    written = 0
    for feature in features:
        if feature.status.value == "missing" or feature.as_of is None:
            continue
        _upsert_feature_value(session, _row_values(feature, computed_at=now))
        written += 1
    session.flush()
    return written
