from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.db.shared_enums import FeatureSubjectKind
from core.db.shared_models import FeatureValueRow
from core.domain.feature import FeatureValue
from core.features.persistence import persist_feature_values

AS_OF = datetime(2026, 6, 10, 15, 46, 48, 455191, tzinfo=UTC)
UPDATED_AT = datetime(2026, 6, 10, 16, 0, 0, tzinfo=UTC)


def _session_from_shared_url(shared_url: str) -> Session:
    from sqlalchemy import create_engine

    engine = create_engine(shared_url)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def _kalshi_spread_feature(*, value: Decimal, as_of: datetime = AS_OF) -> FeatureValue:
    return FeatureValue.present(
        provider_name="kalshi_spread",
        provider_version="1",
        subject_kind="market",
        subject_id="KXHIGHNY-26JUN10-T82",
        as_of=as_of,
        value_numeric=value,
    )


def test_persist_feature_values_writes_present_feature(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    feature = _kalshi_spread_feature(value=Decimal("0.15"))

    written = persist_feature_values(session, [feature])
    session.commit()

    assert written == 1
    row = session.scalar(
        select(FeatureValueRow).where(
            FeatureValueRow.provider_name == "kalshi_spread",
            FeatureValueRow.subject_id == "KXHIGHNY-26JUN10-T82",
        )
    )
    assert row is not None
    assert row.value_numeric == Decimal("0.15")
    assert row.subject_kind == FeatureSubjectKind.MARKET


def test_persist_feature_values_skips_missing(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    feature = FeatureValue.missing(
        provider_name="kalshi_spread",
        provider_version="1",
        subject_kind="market",
        subject_id="KXHIGHNY-26JUN10-T82",
        reason="no snapshot",
    )

    written = persist_feature_values(session, [feature])
    session.commit()

    assert written == 0
    assert session.scalars(select(FeatureValueRow)).all() == []


def test_persist_feature_values_is_idempotent_on_duplicate_key(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session_from_shared_url(per_env_sqlite_urls[0])
    feature = _kalshi_spread_feature(value=Decimal("0.15"))

    persist_feature_values(session, [feature])
    session.commit()

    written = persist_feature_values(session, [feature])
    session.commit()

    assert written == 1
    rows = session.scalars(select(FeatureValueRow)).all()
    assert len(rows) == 1


def test_persist_feature_values_updates_value_on_conflict(
    per_env_sqlite_urls: tuple[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.features import persistence as persistence_module

    session = _session_from_shared_url(per_env_sqlite_urls[0])
    original_id = "00000000-0000-4000-8000-000000000001"
    monkeypatch.setattr(persistence_module, "_new_id", lambda: original_id)

    first = _kalshi_spread_feature(value=Decimal("0.15"))
    persist_feature_values(session, [first])
    session.commit()

    second_id = "00000000-0000-4000-8000-000000000002"
    monkeypatch.setattr(persistence_module, "_new_id", lambda: second_id)
    monkeypatch.setattr(persistence_module, "utc_now", lambda: UPDATED_AT)

    updated = _kalshi_spread_feature(value=Decimal("0.20"))
    persist_feature_values(session, [updated])
    session.commit()

    row = session.scalar(select(FeatureValueRow))
    assert row is not None
    assert row.id == original_id
    assert row.value_numeric == Decimal("0.20")
    assert row.computed_at.replace(tzinfo=UTC) == UPDATED_AT
