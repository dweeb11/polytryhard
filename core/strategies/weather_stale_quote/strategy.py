from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.weather_markets import weather_series
from core.settings import Settings
from core.strategies.weather_utils import numeric_feature

REQUIRED_FEATURES = frozenset({"weather_model_prob", "kalshi_spread"})


class WeatherStaleQuoteStrategy(Strategy):
    """Trade wide-spread (possibly stale) books only when the model edge
    survives the actual crossing price, not the mid."""

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
        if not required_features_present(
            self.required_features,
            features,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        model_prob = numeric_feature(features.get("weather_model_prob"))
        spread = numeric_feature(features.get("kalshi_spread"))
        if model_prob is None or spread is None:
            return None
        if market.ask_yes is None or market.bid_yes is None:
            return None

        config = ctx.effective_config()
        if spread < Decimal(str(config.wide_spread_threshold)):
            return None
        min_edge = Decimal(str(config.min_edge))

        yes_edge = model_prob - market.ask_yes
        no_edge = market.bid_yes - model_prob
        if yes_edge >= no_edge and yes_edge > min_edge:
            side, edge = PositionSide.YES, yes_edge
        elif no_edge > min_edge:
            side, edge = PositionSide.NO, no_edge
        else:
            return None

        confidence = min(Decimal("1"), edge / Decimal("0.15"))
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=model_prob,
            confidence=confidence,
            side=side,
        )
