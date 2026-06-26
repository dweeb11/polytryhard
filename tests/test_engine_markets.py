from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import patch

from core.domain.feature import FeatureValue
from core.engine.markets import index_features, strategy_features_for_market


def test_strategy_features_for_market_aggregates_ensemble_parts() -> None:
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
    scoped = strategy_features_for_market(indexed, location_id="nyc", ticker="KXHIGHNY-25MAY28-T72")
    assert "ensemble_mean_temp" in scoped
    assert scoped["ensemble_mean_temp"].subject_id == "nyc"
    assert scoped["ensemble_mean_temp"].value_numeric == Decimal("95")


def test_strategy_features_for_market_scopes_kalshi_spread_by_ticker() -> None:
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
    scoped = strategy_features_for_market(indexed, location_id="nyc", ticker="TICK-A")
    assert scoped == {"kalshi_spread": spread_a}


def test_strategy_features_for_market_prefers_location_rollup_over_model_parts() -> None:
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    rollup = FeatureValue.present(
        provider_name="ensemble_mean_temp",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc",
        as_of=as_of,
        value_numeric=Decimal("50"),
    )
    part = FeatureValue.present(
        provider_name="ensemble_mean_temp",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc:gfs",
        as_of=as_of,
        value_numeric=Decimal("90"),
    )
    indexed = index_features([rollup, part])
    scoped = strategy_features_for_market(indexed, location_id="nyc", ticker="TICK-A")
    assert scoped["ensemble_mean_temp"].value_numeric == Decimal("50")


def test_strategy_features_for_market_warns_on_unrecognized_subject_kind() -> None:
    as_of = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    article = FeatureValue.present(
        provider_name="news_sentiment",
        provider_version="1",
        subject_kind="article",
        subject_id="article-123",
        as_of=as_of,
        value_numeric=Decimal("0.5"),
    )
    indexed = index_features([article])
    with patch("core.engine.markets.logger.warning") as warning:
        scoped = strategy_features_for_market(indexed, location_id="nyc", ticker="TICK-A")
    assert scoped == {}
    warning.assert_called_once()
    assert "article" in str(warning.call_args)
