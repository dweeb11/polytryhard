"""Pure domain logic for Kalshi weather bracket markets.

Bracket semantics — EMPIRICALLY VERIFIED against 66 recorded settlement
resolutions with observed temperatures, 0 mismatches, 2026-07-02
(see scripts/verify_bracket_semantics.py):
  greater  -> value strictly greater than floor_strike (markets carry only
              floor_strike for this type; there is no cap_strike)
  less     -> value strictly less than cap_strike (markets carry only
              cap_strike for this type; there is no floor_strike)
  between  -> floor_strike <= value <= cap_strike (inclusive both ends)
Unknown strike types return None -> callers fail closed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

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

_DATE_SEGMENT = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Some Kalshi payloads deliver implausibly-scaled strike metadata (e.g. a
# floor_strike ~1e-5, the true strike x 1e-6). Legitimate Kalshi temperature
# strikes are always integers or x.5 and never fall strictly between 0 and 1
# in absolute value, so that band is also implausible. We do not normalize
# heuristically — fail closed instead of trading on garbage metadata.
_PLAUSIBLE_STRIKE_MIN = Decimal("-50")
_PLAUSIBLE_STRIKE_MAX = Decimal("150")


def plausible_temperature_strike(value: Decimal | None) -> bool:
    """Whether `value` looks like a real Kalshi temperature strike.

    A `None` strike is not this guard's business — missing-strike handling
    lives elsewhere, so `None` is considered plausible here.
    """
    if value is None:
        return True
    if not (_PLAUSIBLE_STRIKE_MIN <= value <= _PLAUSIBLE_STRIKE_MAX):
        return False
    if 0 < abs(value) < 1:
        return False
    return True


def weather_series(series: str) -> bool:
    return bool(WEATHER_SERIES_PATTERN.match(series))


def location_for_series(series: str) -> str | None:
    upper = series.upper()
    for prefix, location_id in SERIES_TO_LOCATION.items():
        if upper.startswith(prefix):
            return location_id
    return None


def target_local_date(ticker: str) -> date | None:
    parts = ticker.upper().split("-")
    if len(parts) < 2:
        return None
    match = _DATE_SEGMENT.match(parts[1])
    if match is None:
        return None
    yy, mon, dd = match.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        return date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None


def bracket_satisfied(
    value: Decimal,
    *,
    strike_type: str,
    floor_strike: Decimal | None,
    cap_strike: Decimal | None,
) -> bool | None:
    kind = strike_type.lower()
    if kind == "greater":
        if floor_strike is None:
            return None
        return value > floor_strike
    if kind == "less":
        if cap_strike is None:
            return None
        return value < cap_strike
    if kind == "between":
        if floor_strike is None or cap_strike is None:
            return None
        return floor_strike <= value <= cap_strike
    return None


def bracket_probability(
    daily_maxes: Sequence[Decimal],
    *,
    strike_type: str,
    floor_strike: Decimal | None,
    cap_strike: Decimal | None,
) -> Decimal | None:
    if not daily_maxes:
        return None
    hits = 0
    for value in daily_maxes:
        satisfied = bracket_satisfied(
            value, strike_type=strike_type, floor_strike=floor_strike, cap_strike=cap_strike
        )
        if satisfied is None:
            return None
        if satisfied:
            hits += 1
    n = len(daily_maxes)
    return (Decimal(hits) + Decimal(1)) / (Decimal(n) + Decimal(2))
