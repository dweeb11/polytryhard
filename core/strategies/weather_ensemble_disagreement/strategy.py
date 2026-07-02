from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.weather_markets import weather_series
from core.settings import Settings
from core.strategies.weather_utils import numeric_feature

REQUIRED_FEATURES = frozenset({"weather_model_prob", "kalshi_spread", "forecast_disagreement"})


class WeatherEnsembleDisagreementStrategy(Strategy):
    """Value trade on the ensemble bracket probability, gated by model agreement.

    High GFS/ECMWF disagreement means the forecast is uncertain -> stand down.
    Trade only when models agree AND the market mid diverges from the model
    probability by more than half the spread plus a configured edge margin.
    """

    @property
    def name(self) -> str:
        return "weather_ensemble_disagreement"

    @property
    def required_features(self) -> frozenset[str]:
        return REQUIRED_FEATURES

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
        if not required_features_present(
            self.required_features,
            features,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        model_prob = numeric_feature(features.get("weather_model_prob"))
        spread = numeric_feature(features.get("kalshi_spread"))
        disagreement = numeric_feature(features.get("forecast_disagreement"))
        mid = market.mid_yes
        if model_prob is None or spread is None or disagreement is None or mid is None:
            return None

        config = ctx.effective_config()
        if disagreement > Decimal(str(config.max_disagreement_f)):
            return None

        divergence = model_prob - mid
        threshold = spread / Decimal("2") + Decimal(str(config.min_edge))
        if abs(divergence) <= threshold:
            return None

        side = PositionSide.YES if divergence > 0 else PositionSide.NO
        confidence = min(Decimal("1"), abs(divergence) / Decimal("0.15"))
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=model_prob,
            confidence=confidence,
            side=side,
        )
