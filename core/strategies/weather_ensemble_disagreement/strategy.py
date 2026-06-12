from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.settings import Settings
from core.strategies.weather_utils import (
    ensemble_to_prob,
    location_for_series,
    numeric_feature,
    prob_to_temp,
    scoped_features,
    weather_series,
)

REQUIRED_FEATURES = frozenset({"ensemble_mean_temp", "kalshi_spread"})


class WeatherEnsembleDisagreementStrategy(Strategy):
    @property
    def name(self) -> str:
        return "weather_ensemble_disagreement"

    @property
    def required_features(self) -> frozenset[str]:
        return REQUIRED_FEATURES | frozenset({"forecast_disagreement"})

    def is_enabled(self, settings: Settings) -> bool:
        return True

    def evaluate(
        self,
        market: MarketState,
        features: dict[str, FeatureValue],
        ctx: StrategyContext,
    ) -> SignalDraft | None:
        if not weather_series(market.series):
            return None
        location_id = location_for_series(market.series)
        if location_id is None:
            return None
        scoped = scoped_features(features, location_id, market.ticker)
        if not required_features_present(
            self.required_features,
            scoped,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        disagreement = numeric_feature(scoped.get("forecast_disagreement"))
        spread = numeric_feature(scoped.get("kalshi_spread"))
        ensemble_mean = numeric_feature(scoped.get("ensemble_mean_temp"))
        mid = market.mid_yes
        if disagreement is None or spread is None or ensemble_mean is None or mid is None:
            return None

        config = ctx.effective_config()
        disagreement_threshold = Decimal(str(config.disagreement_threshold))
        spread_margin = Decimal(str(config.spread_margin_multiplier))
        confidence_floor = Decimal(str(config.confidence_floor))

        if disagreement < disagreement_threshold:
            return None

        model_prob_yes = ensemble_to_prob(ensemble_mean)
        divergence = abs(mid - model_prob_yes)
        if divergence <= spread * spread_margin:
            return None

        side = PositionSide.YES if ensemble_mean >= prob_to_temp(mid) else PositionSide.NO
        confidence = min(
            Decimal("1"),
            confidence_floor + (disagreement / Decimal("10")) + (divergence / Decimal("0.2")),
        )
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=model_prob_yes,
            confidence=confidence,
            side=side,
        )
