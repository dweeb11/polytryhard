from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.settings import Settings
from core.strategies.weather_utils import location_for_series, weather_series

REQUIRED_FEATURES = frozenset({"ensemble_mean_temp", "kalshi_spread"})


def _config_float(config: dict[str, object], key: str, default: float) -> float:
    raw = config.get(key, default)
    if isinstance(raw, (int, float)):
        return float(raw)
    return default


def _numeric(feature: FeatureValue | None) -> Decimal | None:
    if feature is None or feature.status.value != "present":
        return None
    return feature.value_numeric


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
        scoped = _scoped_features(features, location_id, market.ticker)
        if not required_features_present(
            self.required_features,
            scoped,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        disagreement = _numeric(scoped.get("forecast_disagreement"))
        spread = _numeric(scoped.get("kalshi_spread"))
        ensemble_mean = _numeric(scoped.get("ensemble_mean_temp"))
        mid = market.mid_yes
        if disagreement is None or spread is None or ensemble_mean is None or mid is None:
            return None

        disagreement_threshold = Decimal(
            str(_config_float(ctx.config_jsonb, "disagreementThreshold", 2.0))
        )
        spread_margin = Decimal(
            str(_config_float(ctx.config_jsonb, "spreadMarginMultiplier", 1.5))
        )
        confidence_floor = Decimal(
            str(_config_float(ctx.config_jsonb, "confidenceFloor", 0.55))
        )

        if disagreement < disagreement_threshold:
            return None

        divergence = abs(mid - _ensemble_to_prob(ensemble_mean))
        if divergence <= spread * spread_margin:
            return None

        side = PositionSide.YES if ensemble_mean >= _prob_to_temp(mid) else PositionSide.NO
        prob_yes = mid if side == PositionSide.YES else (Decimal("1") - mid)
        confidence = min(
            Decimal("1"),
            confidence_floor + (disagreement / Decimal("10")) + (divergence / Decimal("0.2")),
        )
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=prob_yes,
            confidence=confidence,
            side=side,
        )


def _scoped_features(
    features: dict[str, FeatureValue],
    location_id: str,
    ticker: str,
) -> dict[str, FeatureValue]:
    scoped: dict[str, FeatureValue] = {}
    for name, feature in features.items():
        if name == "kalshi_spread":
            if feature.subject_id == ticker:
                scoped[name] = feature
        elif feature.subject_id == location_id:
            scoped[name] = feature
    return scoped


def _ensemble_to_prob(temp_f: Decimal) -> Decimal:
    return max(Decimal("0.05"), min(Decimal("0.95"), (temp_f - Decimal("32")) / Decimal("100")))


def _prob_to_temp(prob: Decimal) -> Decimal:
    return prob * Decimal("100") + Decimal("32")
