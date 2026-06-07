from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.settings import Settings
from core.strategies.weather_utils import (
    location_for_series,
    numeric_feature,
    prob_to_temp,
    scoped_features,
    weather_series,
)

REQUIRED_FEATURES = frozenset({"ensemble_mean_temp", "kalshi_spread"})


class WeatherStaleQuoteStrategy(Strategy):
    """Detect stale Kalshi quotes via unusually wide spreads.

    MVP: compares spread to a static ``wideSpreadThreshold`` from strategy config.
    Design doc (m4-engine.md) also describes spread vs recent history; that needs
    a history feature and is deferred to a follow-up slice.
    """

    @property
    def name(self) -> str:
        return "weather_stale_quote"

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

        spread = numeric_feature(scoped.get("kalshi_spread"))
        ensemble_mean = numeric_feature(scoped.get("ensemble_mean_temp"))
        mid = market.mid_yes
        if spread is None or ensemble_mean is None or mid is None:
            return None

        config = ctx.effective_config()
        wide_spread_threshold = Decimal(str(config.wide_spread_threshold))
        confidence_floor = Decimal(str(config.confidence_floor))

        if spread < wide_spread_threshold:
            return None

        side = PositionSide.YES if ensemble_mean >= prob_to_temp(mid) else PositionSide.NO
        prob_yes = mid if side == PositionSide.YES else (Decimal("1") - mid)
        confidence = min(Decimal("1"), confidence_floor + spread)
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=prob_yes,
            confidence=confidence,
            side=side,
        )
