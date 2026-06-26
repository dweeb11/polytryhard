"""Engine→strategy feature bundle seam (APP-294 slice 1).

Proves ``strategy_features_for_market`` is the final dict strategies should
receive — legacy ``scoped_features`` is a no-op on its output.
"""

from datetime import UTC, datetime
from decimal import Decimal

from core.contracts.strategy import StrategyContext
from core.domain.feature import FeatureValue
from core.domain.market import MarketState
from core.engine.markets import index_features, strategy_features_for_market
from core.strategies.weather_ensemble_disagreement.strategy import (
    WeatherEnsembleDisagreementStrategy,
)
from core.strategies.weather_stale_quote.strategy import WeatherStaleQuoteStrategy
from core.strategies.weather_utils import scoped_features

AS_OF = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
TICKER = "KXHIGHNY-25MAY28-T72"
LOCATION_ID = "nyc"


def _provider_index(**overrides: Decimal) -> dict[str, FeatureValue]:
    """Simulate indexed provider output for NYC weather + one Kalshi market."""
    defaults = {
        "ensemble_mean_temp": Decimal("90"),
        "forecast_disagreement": Decimal("5"),
        "kalshi_spread": Decimal("0.15"),
    }
    defaults.update(overrides)
    rows: list[FeatureValue] = []
    for name, value in defaults.items():
        if name == "kalshi_spread":
            rows.append(
                FeatureValue.present(
                    provider_name=name,
                    provider_version="1",
                    subject_kind="market",
                    subject_id=TICKER,
                    as_of=AS_OF,
                    value_numeric=value,
                )
            )
            rows.append(
                FeatureValue.present(
                    provider_name=name,
                    provider_version="1",
                    subject_kind="market",
                    subject_id="KXHIGHCHI-25MAY28-T72",
                    as_of=AS_OF,
                    value_numeric=Decimal("0.99"),
                )
            )
        else:
            rows.append(
                FeatureValue.present(
                    provider_name=name,
                    provider_version="1",
                    subject_kind="location",
                    subject_id=LOCATION_ID,
                    as_of=AS_OF,
                    value_numeric=value,
                )
            )
            rows.append(
                FeatureValue.present(
                    provider_name=name,
                    provider_version="1",
                    subject_kind="location",
                    subject_id="chicago",
                    as_of=AS_OF,
                    value_numeric=Decimal("99"),
                )
            )
    return index_features(rows)


def _market(**overrides: object) -> MarketState:
    base = {
        "ticker": TICKER,
        "series": "KXHIGHNY",
        "bid_yes": Decimal("0.40"),
        "ask_yes": Decimal("0.55"),
        "mid_yes": Decimal("0.10"),
        "as_of": AS_OF,
        "location_id": LOCATION_ID,
    }
    base.update(overrides)
    return MarketState(**base)  # type: ignore[arg-type]


def _strategy_context(strategy_name: str) -> StrategyContext:
    return StrategyContext(
        strategy_name=strategy_name,
        config_jsonb={
            "min_bankroll_cents": 10_000,
            "min_tradeable_bankroll_cents": 5_000,
            "max_drawdown_pct_from_hwm": 30,
            "auto_resume_on_deposit": True,
            "max_input_age_seconds": 900,
        },
    )


def test_engine_delivered_features_are_identity_under_legacy_scoped_filter() -> None:
    indexed = _provider_index()
    delivered = strategy_features_for_market(
        indexed, location_id=LOCATION_ID, ticker=TICKER
    )
    refiltered = scoped_features(delivered, LOCATION_ID, TICKER)
    assert refiltered == delivered
    assert set(delivered) == {"ensemble_mean_temp", "forecast_disagreement", "kalshi_spread"}
    assert delivered["kalshi_spread"].subject_id == TICKER
    assert delivered["ensemble_mean_temp"].subject_id == LOCATION_ID


def test_weather_strategies_accept_engine_delivered_features() -> None:
    indexed = _provider_index()
    delivered = strategy_features_for_market(
        indexed, location_id=LOCATION_ID, ticker=TICKER
    )
    ensemble = WeatherEnsembleDisagreementStrategy()
    stale = WeatherStaleQuoteStrategy()

    ensemble_signal = ensemble.evaluate(
        _market(), delivered, _strategy_context(ensemble.name)
    )
    stale_signal = stale.evaluate(
        _market(mid_yes=Decimal("0.50")),
        delivered,
        _strategy_context(stale.name),
    )

    assert ensemble_signal is not None
    assert stale_signal is not None
