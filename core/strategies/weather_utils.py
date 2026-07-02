from __future__ import annotations

from decimal import Decimal

from core.domain.feature import FeatureValue
from core.domain.weather_markets import SERIES_TO_LOCATION as SERIES_TO_LOCATION
from core.domain.weather_markets import WEATHER_SERIES_PATTERN as WEATHER_SERIES_PATTERN
from core.domain.weather_markets import location_for_series as location_for_series
from core.domain.weather_markets import weather_series as weather_series


def ensemble_to_prob(temp_f: Decimal) -> Decimal:
    return max(Decimal("0.05"), min(Decimal("0.95"), (temp_f - Decimal("32")) / Decimal("100")))


def prob_to_temp(prob: Decimal) -> Decimal:
    return prob * Decimal("100") + Decimal("32")


def numeric_feature(feature: FeatureValue | None) -> Decimal | None:
    if feature is None or feature.status.value != "present":
        return None
    return feature.value_numeric
