import re

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
