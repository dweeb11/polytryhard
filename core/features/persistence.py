from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import uuid4

from sqlalchemy.dialects.postgresql import Insert as PgInsert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import Insert as SqliteInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from core.db.shared_enums import FeatureSubjectKind
from core.db.shared_models import FeatureValueRow
from core.domain.feature import FeatureStatus, FeatureValue
from core.utils.time import utc_now

_CONFLICT_COLUMNS = (
    "provider_name",
    "provider_version",
    "subject_kind",
    "subject_id",
    "as_of",
)


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


def _upsert_feature_values(session: Session, rows: list[dict[str, object]]) -> None:
    dialect_name = session.get_bind().dialect.name
    stmt: PgInsert | SqliteInsert
    if dialect_name == "postgresql":
        stmt = pg_insert(FeatureValueRow)
    elif dialect_name == "sqlite":
        stmt = sqlite_insert(FeatureValueRow)
    else:
        msg = f"unsupported dialect for feature upsert: {dialect_name}"
        raise RuntimeError(msg)

    # Postgres rejects ON CONFLICT updates that touch the same row twice in one
    # statement, so collapse duplicate keys within the batch (last write wins).
    deduped = list({tuple(row[col] for col in _CONFLICT_COLUMNS): row for row in rows}.values())
    session.execute(
        stmt.values(deduped).on_conflict_do_update(
            index_elements=list(_CONFLICT_COLUMNS),
            set_={
                "value_numeric": stmt.excluded.value_numeric,
                "value_jsonb": stmt.excluded.value_jsonb,
                "input_hash": stmt.excluded.input_hash,
                "computed_at": stmt.excluded.computed_at,
            },
        )
    )


def persist_feature_values(session: Session, features: list[FeatureValue]) -> int:
    now = utc_now()
    rows = [
        _row_values(feature, computed_at=now)
        for feature in features
        if feature.status is not FeatureStatus.MISSING and feature.as_of is not None
    ]
    if rows:
        _upsert_feature_values(session, rows)
    session.flush()
    return len(rows)
