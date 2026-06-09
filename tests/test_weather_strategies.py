from datetime import UTC, datetime
from decimal import Decimal

from core.contracts.strategy import StrategyContext
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState
from core.strategies.registry import registered_strategies
from core.strategies.weather_ensemble_disagreement.strategy import (
    WeatherEnsembleDisagreementStrategy,
)
from core.strategies.weather_stale_quote.strategy import WeatherStaleQuoteStrategy

AS_OF = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)


def _market(**overrides: object) -> MarketState:
    base = {
        "ticker": "KXHIGHNY-25MAY28-T72",
        "series": "KXHIGHNY",
        "bid_yes": Decimal("0.40"),
        "ask_yes": Decimal("0.55"),
        "mid_yes": Decimal("0.10"),
        "as_of": AS_OF,
        "location_id": "nyc",
    }
    base.update(overrides)
    return MarketState(**base)  # type: ignore[arg-type]


def _features(**overrides: Decimal) -> dict[str, FeatureValue]:
    defaults = {
        "ensemble_mean_temp": Decimal("90"),
        "forecast_disagreement": Decimal("5"),
        "kalshi_spread": Decimal("0.15"),
    }
    defaults.update(overrides)
    result: dict[str, FeatureValue] = {}
    for name, value in defaults.items():
        subject_id = "KXHIGHNY-25MAY28-T72" if name == "kalshi_spread" else "nyc"
        subject_kind = "market" if name == "kalshi_spread" else "location"
        result[name] = FeatureValue.present(
            provider_name=name,
            provider_version="1",
            subject_kind=subject_kind,
            subject_id=subject_id,
            as_of=AS_OF,
            value_numeric=value,
        )
    return result


def _baseline_config_jsonb(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "min_bankroll_cents": 10_000,
        "min_tradeable_bankroll_cents": 5_000,
        "max_drawdown_pct_from_hwm": 30,
        "auto_resume_on_deposit": True,
        "max_input_age_seconds": 900,
    }
    config.update(overrides)
    return config


def _strategy_context(strategy_name: str, **config_overrides: object) -> StrategyContext:
    return StrategyContext(
        strategy_name=strategy_name,
        config_jsonb=_baseline_config_jsonb(**config_overrides),
    )


def test_weather_strategies_registered() -> None:
    names = {strategy.name for strategy in registered_strategies()}
    assert names == {"weather_ensemble_disagreement", "weather_stale_quote"}


def test_weather_ensemble_disagreement_emits_on_divergence() -> None:
    strategy = WeatherEnsembleDisagreementStrategy()
    signal = strategy.evaluate(
        _market(),
        _features(),
        _strategy_context(strategy.name),
    )
    assert signal is not None
    assert signal.side in {PositionSide.YES, PositionSide.NO}
    assert signal.prob_yes == Decimal("0.58")


def test_weather_ensemble_disagreement_rejects_low_disagreement() -> None:
    strategy = WeatherEnsembleDisagreementStrategy()
    signal = strategy.evaluate(
        _market(),
        _features(forecast_disagreement=Decimal("0.5")),
        _strategy_context(strategy.name),
    )
    assert signal is None


def test_weather_ensemble_disagreement_rejects_insufficient_divergence() -> None:
    strategy = WeatherEnsembleDisagreementStrategy()
    # ensemble 72°F -> prob 0.40; mid aligned -> divergence 0 <= spread × 1.5
    signal = strategy.evaluate(
        _market(mid_yes=Decimal("0.40")),
        _features(
            ensemble_mean_temp=Decimal("72"),
            forecast_disagreement=Decimal("5"),
            kalshi_spread=Decimal("0.15"),
        ),
        _strategy_context(strategy.name),
    )
    assert signal is None


def test_weather_ensemble_disagreement_rejects_missing_features() -> None:
    strategy = WeatherEnsembleDisagreementStrategy()
    features = _features()
    features["forecast_disagreement"] = FeatureValue.missing(
        provider_name="forecast_disagreement",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc",
        reason="missing",
    )
    signal = strategy.evaluate(
        _market(),
        features,
        _strategy_context(strategy.name),
    )
    assert signal is None


def test_weather_stale_quote_emits_on_wide_spread() -> None:
    strategy = WeatherStaleQuoteStrategy()
    signal = strategy.evaluate(
        _market(mid_yes=Decimal("0.50")),
        _features(kalshi_spread=Decimal("0.12")),
        _strategy_context(strategy.name),
    )
    assert signal is not None
    assert signal.prob_yes == Decimal("0.58")


def test_weather_stale_quote_no_side_keeps_yes_probability() -> None:
    strategy = WeatherStaleQuoteStrategy()
    signal = strategy.evaluate(
        _market(mid_yes=Decimal("0.38")),
        _features(
            ensemble_mean_temp=Decimal("20"),
            kalshi_spread=Decimal("0.12"),
        ),
        _strategy_context(strategy.name),
    )
    assert signal is not None
    assert signal.side == PositionSide.NO
    assert signal.prob_yes == Decimal("0.05")


def test_weather_stale_quote_rejects_tight_spread() -> None:
    strategy = WeatherStaleQuoteStrategy()
    signal = strategy.evaluate(
        _market(mid_yes=Decimal("0.50")),
        _features(kalshi_spread=Decimal("0.02")),
        _strategy_context(strategy.name),
    )
    assert signal is None
