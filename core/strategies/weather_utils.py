from __future__ import annotations

import re
from decimal import Decimal

from core.domain.feature import FeatureValue

WEATHER_SERIES_PATTERN = re.compile(r"^KXHIGH", re.IGNORECASE)

# Ticker like KXHIGHNY-25MAY28-T72 -> location slug nyc (Kalshi NY = NYC metro)
SERIES_TO_LOCATION: dict[str, str] = {
    "KXHIGHNY": "nyc",
    "KXHIGHCHI": "chicago",
    "KXHIGHLAX": "la",
    "KXHIGHMIA": "miami",
    "KXHIGHHOU": "houston",
    "KXHIGHAUS": "austin",
}


def weather_series(series: str) -> bool:
    return bool(WEATHER_SERIES_PATTERN.match(series))


def location_for_series(series: str) -> str | None:
    upper = series.upper()
    for prefix, location_id in SERIES_TO_LOCATION.items():
        if upper.startswith(prefix):
            return location_id
    return None


def ensemble_to_prob(temp_f: Decimal) -> Decimal:
    return max(Decimal("0.05"), min(Decimal("0.95"), (temp_f - Decimal("32")) / Decimal("100")))


def prob_to_temp(prob: Decimal) -> Decimal:
    return prob * Decimal("100") + Decimal("32")


def numeric_feature(feature: FeatureValue | None) -> Decimal | None:
    if feature is None or feature.status.value != "present":
        return None
    return feature.value_numeric
