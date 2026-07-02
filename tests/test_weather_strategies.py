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


def _feature(name: str, subject_id: str, value: str) -> FeatureValue:
    return FeatureValue.present(
        provider_name=name,
        provider_version="1",
        subject_kind="market" if name in {"weather_model_prob", "kalshi_spread"} else "location",
        subject_id=subject_id,
        as_of=AS_OF,
        value_numeric=Decimal(value),
    )


def _market(mid: str = "0.50", bid: str = "0.48", ask: str = "0.52") -> MarketState:
    return MarketState(
        ticker="KXHIGHNY-25MAY28-T73",
        series="KXHIGHNY",
        bid_yes=Decimal(bid),
        ask_yes=Decimal(ask),
        mid_yes=Decimal(mid),
        as_of=AS_OF,
        location_id="nyc",
    )


def _features(
    prob: str, spread: str = "0.04", disagreement: str = "1.0"
) -> dict[str, FeatureValue]:
    return {
        "weather_model_prob": _feature("weather_model_prob", "KXHIGHNY-25MAY28-T73", prob),
        "kalshi_spread": _feature("kalshi_spread", "KXHIGHNY-25MAY28-T73", spread),
        "forecast_disagreement": _feature("forecast_disagreement", "nyc", disagreement),
    }


def test_weather_strategies_registered() -> None:
    names = {strategy.name for strategy in registered_strategies()}
    assert names == {"weather_ensemble_disagreement", "weather_stale_quote"}


class TestEnsembleDisagreement:
    STRATEGY = WeatherEnsembleDisagreementStrategy()
    CTX = _strategy_context("weather_ensemble_disagreement")

    def test_emits_yes_when_model_far_above_mid_and_models_agree(self) -> None:
        # model 0.70 vs mid 0.50; spread 0.04 -> threshold 0.02 + min_edge 0.05 = 0.07 < 0.20
        signal = self.STRATEGY.evaluate(_market(), _features("0.70"), self.CTX)
        assert signal is not None
        assert signal.side == PositionSide.YES
        assert signal.prob_yes == Decimal("0.70")

    def test_no_signal_when_models_disagree_too_much(self) -> None:
        assert (
            self.STRATEGY.evaluate(_market(), _features("0.70", disagreement="5.0"), self.CTX)
            is None
        )

    def test_no_signal_when_divergence_within_costs(self) -> None:
        assert self.STRATEGY.evaluate(_market(), _features("0.55"), self.CTX) is None

    def test_no_side_when_model_below_mid_emits_no(self) -> None:
        signal = self.STRATEGY.evaluate(_market(), _features("0.30"), self.CTX)
        assert signal is not None
        assert signal.side == PositionSide.NO

    def test_no_signal_when_non_weather_series(self) -> None:
        market = MarketState(
            ticker="OTHER-25MAY28-T73",
            series="OTHER",
            bid_yes=Decimal("0.48"),
            ask_yes=Decimal("0.52"),
            mid_yes=Decimal("0.50"),
            as_of=AS_OF,
            location_id="nyc",
        )
        assert self.STRATEGY.evaluate(market, _features("0.70"), self.CTX) is None

    def test_no_signal_when_features_missing(self) -> None:
        features = _features("0.70")
        features["forecast_disagreement"] = FeatureValue.missing(
            provider_name="forecast_disagreement",
            provider_version="1",
            subject_kind="location",
            subject_id="nyc",
            reason="missing",
        )
        assert self.STRATEGY.evaluate(_market(), features, self.CTX) is None


class TestStaleQuote:
    STRATEGY = WeatherStaleQuoteStrategy()
    CTX = _strategy_context("weather_stale_quote")

    def test_requires_wide_spread(self) -> None:
        # spread 0.04 < wide threshold 0.08 -> None even with huge edge
        assert self.STRATEGY.evaluate(_market(), _features("0.90", spread="0.04"), self.CTX) is None

    def test_yes_edge_measured_at_ask(self) -> None:
        # ask 0.60, model 0.70, min_edge 0.05 -> edge at ask 0.10 -> YES
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        signal = self.STRATEGY.evaluate(market, _features("0.70", spread="0.10"), self.CTX)
        assert signal is not None and signal.side == PositionSide.YES

    def test_no_signal_when_edge_dies_at_entry_price(self) -> None:
        # model 0.63 vs ask 0.60 -> edge 0.03 < min_edge 0.05 -> None
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        assert self.STRATEGY.evaluate(market, _features("0.63", spread="0.10"), self.CTX) is None

    def test_no_side_measured_at_bid(self) -> None:
        # bid 0.50, model 0.30, min_edge 0.05 -> edge at bid 0.20 -> NO
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        signal = self.STRATEGY.evaluate(market, _features("0.30", spread="0.10"), self.CTX)
        assert signal is not None
        assert signal.side == PositionSide.NO

    def test_no_signal_when_non_weather_series(self) -> None:
        market = MarketState(
            ticker="OTHER-25MAY28-T73",
            series="OTHER",
            bid_yes=Decimal("0.50"),
            ask_yes=Decimal("0.60"),
            mid_yes=Decimal("0.55"),
            as_of=AS_OF,
            location_id="nyc",
        )
        assert self.STRATEGY.evaluate(market, _features("0.90", spread="0.10"), self.CTX) is None

    def test_no_signal_when_features_missing(self) -> None:
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        features = _features("0.90", spread="0.10")
        features["weather_model_prob"] = FeatureValue.missing(
            provider_name="weather_model_prob",
            provider_version="1",
            subject_kind="market",
            subject_id="KXHIGHNY-25MAY28-T73",
            reason="missing",
        )
        assert self.STRATEGY.evaluate(market, features, self.CTX) is None
