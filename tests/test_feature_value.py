from datetime import UTC, datetime
from decimal import Decimal

from core.domain.feature import FeatureStatus, FeatureValue

AS_OF = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
PROVIDER_NAME = "ensemble_mean_temp"
PROVIDER_VERSION = "1.0.0"
SUBJECT_KIND = "location"
SUBJECT_ID = "loc-1"


def test_present_sets_status_and_as_of() -> None:
    value = FeatureValue.present(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("72.5"),
    )

    assert value.status == FeatureStatus.PRESENT
    assert value.as_of == AS_OF
    assert value.value_numeric == Decimal("72.5")
    assert value.reason is None


def test_missing_sets_status_and_reason() -> None:
    value = FeatureValue.missing(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        reason="no forecast data",
    )

    assert value.status == FeatureStatus.MISSING
    assert value.reason == "no forecast data"
    assert value.as_of is None
    assert value.value_numeric is None
    assert value.value_jsonb is None


def test_stale_sets_status_as_of_and_default_reason() -> None:
    value = FeatureValue.stale(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("70.0"),
    )

    assert value.status == FeatureStatus.STALE
    assert value.as_of == AS_OF
    assert value.reason == "stale"
    assert value.value_numeric == Decimal("70.0")


def test_to_snapshot_present_numeric() -> None:
    value = FeatureValue.present(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("72.5"),
    )

    assert value.to_snapshot() == {
        "status": "present",
        "asOf": AS_OF.isoformat(),
        "valueNumeric": 72.5,
    }


def test_to_snapshot_present_jsonb() -> None:
    payload: dict[str, object] = {"spread": 0.12}
    value = FeatureValue.present(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_jsonb=payload,
    )

    assert value.to_snapshot() == {
        "status": "present",
        "asOf": AS_OF.isoformat(),
        "valueJsonb": payload,
    }


def test_to_snapshot_missing() -> None:
    value = FeatureValue.missing(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        reason="upstream unavailable",
    )

    assert value.to_snapshot() == {
        "status": "missing",
        "reason": "upstream unavailable",
    }


def test_to_snapshot_stale_includes_reason() -> None:
    value = FeatureValue.stale(
        provider_name=PROVIDER_NAME,
        provider_version=PROVIDER_VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("68.0"),
        reason="forecast older than threshold",
    )

    assert value.to_snapshot() == {
        "status": "stale",
        "asOf": AS_OF.isoformat(),
        "valueNumeric": 68.0,
        "reason": "forecast older than threshold",
    }
