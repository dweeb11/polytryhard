from datetime import UTC, datetime
from decimal import Decimal

from core.domain.feature import FeatureValue
from core.engine.markets import features_for_market, index_features


def test_features_for_market_aggregates_ensemble_parts() -> None:
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    parts = [
        FeatureValue.present(
            provider_name="ensemble_mean_temp",
            provider_version="1",
            subject_kind="location",
            subject_id="nyc:gfs",
            as_of=as_of,
            value_numeric=Decimal("90"),
        ),
        FeatureValue.present(
            provider_name="ensemble_mean_temp",
            provider_version="1",
            subject_kind="location",
            subject_id="nyc:ecmwf",
            as_of=as_of,
            value_numeric=Decimal("100"),
        ),
    ]
    indexed = index_features(parts)
    scoped = features_for_market(indexed, location_id="nyc", ticker="KXHIGHNY-25MAY28-T72")
    assert "ensemble_mean_temp" in scoped
    assert scoped["ensemble_mean_temp"].subject_id == "nyc"
    assert scoped["ensemble_mean_temp"].value_numeric == Decimal("95")


def test_features_for_market_scopes_kalshi_spread_by_ticker() -> None:
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    spread_a = FeatureValue.present(
        provider_name="kalshi_spread",
        provider_version="1",
        subject_kind="market",
        subject_id="TICK-A",
        as_of=as_of,
        value_numeric=Decimal("0.10"),
    )
    spread_b = FeatureValue.present(
        provider_name="kalshi_spread",
        provider_version="1",
        subject_kind="market",
        subject_id="TICK-B",
        as_of=as_of,
        value_numeric=Decimal("0.20"),
    )
    indexed = index_features([spread_a, spread_b])
    scoped = features_for_market(indexed, location_id="nyc", ticker="TICK-A")
    assert scoped == {"kalshi_spread": spread_a}
