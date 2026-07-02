"""Engine→strategy feature bundle seam (APP-294).

Proves ``strategy_features_for_market`` is the final dict strategies receive.
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

AS_OF = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
TICKER = "KXHIGHNY-25MAY28-T72"
LOCATION_ID = "nyc"


def _provider_index(**overrides: Decimal) -> dict[str, FeatureValue]:
    """Simulate indexed provider output for NYC weather + one Kalshi market."""
    market_defaults = {
        "weather_model_prob": Decimal("0.90"),
        "kalshi_spread": Decimal("0.15"),
    }
    location_defaults = {
        "forecast_disagreement": Decimal("1.0"),
    }
    market_defaults.update({k: v for k, v in overrides.items() if k in market_defaults})
    location_defaults.update({k: v for k, v in overrides.items() if k in location_defaults})
    rows: list[FeatureValue] = []
    for name, value in market_defaults.items():
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
    for name, value in location_defaults.items():
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


def test_engine_delivered_features_scope_to_market() -> None:
    indexed = _provider_index()
    delivered = strategy_features_for_market(
        indexed, location_id=LOCATION_ID, ticker=TICKER
    )
    assert set(delivered) == {"weather_model_prob", "forecast_disagreement", "kalshi_spread"}
    assert delivered["kalshi_spread"].subject_id == TICKER
    assert delivered["weather_model_prob"].subject_id == TICKER
    assert delivered["forecast_disagreement"].subject_id == LOCATION_ID
    assert delivered["kalshi_spread"].value_numeric == Decimal("0.15")
    assert delivered["weather_model_prob"].value_numeric == Decimal("0.90")


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
