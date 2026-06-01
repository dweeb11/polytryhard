from datetime import UTC, datetime
from decimal import Decimal

from core.contracts.strategy import required_features_present
from core.domain.feature import FeatureValue

AS_OF = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
PROVIDER = "ensemble_mean_temp"
VERSION = "1.0.0"
SUBJECT_KIND = "location"
SUBJECT_ID = "loc-1"

REQUIRED = frozenset({"ensemble_mean_temp", "forecast_disagreement"})


def _present(name: str = PROVIDER) -> FeatureValue:
    return FeatureValue.present(
        provider_name=name,
        provider_version=VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("72.5"),
    )


def _missing(name: str = PROVIDER) -> FeatureValue:
    return FeatureValue.missing(
        provider_name=name,
        provider_version=VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        reason="no data",
    )


def _stale(name: str = PROVIDER) -> FeatureValue:
    return FeatureValue.stale(
        provider_name=name,
        provider_version=VERSION,
        subject_kind=SUBJECT_KIND,
        subject_id=SUBJECT_ID,
        as_of=AS_OF,
        value_numeric=Decimal("72.5"),
    )


def test_all_present() -> None:
    values = {
        "ensemble_mean_temp": _present("ensemble_mean_temp"),
        "forecast_disagreement": _present("forecast_disagreement"),
    }
    assert required_features_present(REQUIRED, values, tolerate_missing=False) is True


def test_missing_blocked_by_default() -> None:
    values = {
        "ensemble_mean_temp": _present("ensemble_mean_temp"),
        "forecast_disagreement": _missing("forecast_disagreement"),
    }
    assert required_features_present(REQUIRED, values, tolerate_missing=False) is False


def test_missing_tolerated_when_opted_in() -> None:
    values = {
        "ensemble_mean_temp": _present("ensemble_mean_temp"),
        "forecast_disagreement": _missing("forecast_disagreement"),
    }
    assert required_features_present(REQUIRED, values, tolerate_missing=True) is True


def test_absent_key_blocked_by_default() -> None:
    values = {"ensemble_mean_temp": _present("ensemble_mean_temp")}
    assert required_features_present(REQUIRED, values, tolerate_missing=False) is False


def test_absent_key_tolerated_when_opted_in() -> None:
    values = {"ensemble_mean_temp": _present("ensemble_mean_temp")}
    assert required_features_present(REQUIRED, values, tolerate_missing=True) is True


def test_stale_always_blocked() -> None:
    values = {
        "ensemble_mean_temp": _present("ensemble_mean_temp"),
        "forecast_disagreement": _stale("forecast_disagreement"),
    }
    assert required_features_present(REQUIRED, values, tolerate_missing=False) is False
    assert required_features_present(REQUIRED, values, tolerate_missing=True) is False


def test_empty_required_set() -> None:
    assert required_features_present(frozenset(), {}, tolerate_missing=False) is True
