from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from core.contracts.feature import FeatureContext, FeatureProvider
from core.db.shared_enums import FeatureSubjectKind, ForecastSource
from core.domain.feature import FeatureValue
from core.domain.weather_markets import (
    bracket_probability,
    location_for_series,
    target_local_date,
    weather_series,
)
from core.features.queries import (
    TEMPERATURE_VARIABLE,
    daily_max_by_member,
    list_locations,
    list_open_markets,
)
from core.settings import Settings

_UTC = ZoneInfo("UTC")

# Some Kalshi payloads deliver micro-scaled strikes (e.g. floor_strike ~ 1e-5,
# the true strike x 1e-6). We do not normalize heuristically — fail closed
# with MISSING instead of trading on garbage metadata.
_PLAUSIBLE_STRIKE_MIN = Decimal("-50")
_PLAUSIBLE_STRIKE_MAX = Decimal("150")


def _implausible_strike(strike: Decimal | None) -> bool:
    if strike is None:
        return False
    return not (_PLAUSIBLE_STRIKE_MIN <= strike <= _PLAUSIBLE_STRIKE_MAX)


def _mean(values: list[Decimal]) -> float | None:
    return float(sum(values) / len(values)) if values else None


class WeatherModelProbProvider(FeatureProvider):
    """P(market bracket satisfied) from pooled GFS+ECMWF ensemble daily maxes."""

    @property
    def name(self) -> str:
        return "weather_model_prob"

    @property
    def version(self) -> str:
        return "1"

    def is_enabled(self, settings: Settings) -> bool:
        return True

    def _missing(self, ticker: str, reason: str) -> FeatureValue:
        return FeatureValue.missing(
            provider_name=self.name,
            provider_version=self.version,
            subject_kind=FeatureSubjectKind.MARKET.value,
            subject_id=ticker,
            reason=reason,
        )

    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        results: list[FeatureValue] = []
        subject_kind = FeatureSubjectKind.MARKET.value
        locations = {loc.id: loc for loc in list_locations(ctx.session)}

        for market in list_open_markets(ctx.session, as_of=as_of):
            if not weather_series(market.series):
                continue
            location_id = location_for_series(market.series)
            if location_id is None or location_id not in locations:
                results.append(self._missing(market.ticker, "unknown location"))
                continue
            if market.strike_type is None:
                results.append(self._missing(market.ticker, "no strike metadata"))
                continue
            if _implausible_strike(market.floor_strike) or _implausible_strike(
                market.cap_strike
            ):
                results.append(self._missing(market.ticker, "implausible strike metadata"))
                continue
            target_day = target_local_date(market.ticker)
            if target_day is None:
                results.append(self._missing(market.ticker, "unparsable target date"))
                continue

            try:
                tz = ZoneInfo(locations[location_id].timezone)
            except (ZoneInfoNotFoundError, ValueError):
                results.append(self._missing(market.ticker, "invalid timezone"))
                continue
            day_start = datetime.combine(target_day, time.min, tzinfo=tz)
            day_start_utc = day_start.astimezone(_UTC)
            day_end_utc = (day_start + timedelta(days=1)).astimezone(_UTC)

            per_source: dict[ForecastSource, list[Decimal]] = {}
            for source in (ForecastSource.GFS, ForecastSource.ECMWF):
                maxes = daily_max_by_member(
                    ctx.session,
                    location_id=location_id,
                    source=source,
                    variable=TEMPERATURE_VARIABLE,
                    as_of=as_of,
                    day_start_utc=day_start_utc,
                    day_end_utc=day_end_utc,
                )
                per_source[source] = list(maxes.values())
            pooled = per_source[ForecastSource.GFS] + per_source[ForecastSource.ECMWF]
            prob = bracket_probability(
                pooled,
                strike_type=market.strike_type,
                floor_strike=market.floor_strike,
                cap_strike=market.cap_strike,
            )
            if prob is None:
                results.append(
                    self._missing(market.ticker, "no ensemble members for target day")
                )
                continue

            results.append(
                FeatureValue.present(
                    provider_name=self.name,
                    provider_version=self.version,
                    subject_kind=subject_kind,
                    subject_id=market.ticker,
                    as_of=as_of,
                    value_numeric=prob,
                    value_jsonb={
                        "nMembers": len(pooled),
                        "gfsMembers": len(per_source[ForecastSource.GFS]),
                        "ecmwfMembers": len(per_source[ForecastSource.ECMWF]),
                        "gfsMeanMax": _mean(per_source[ForecastSource.GFS]),
                        "ecmwfMeanMax": _mean(per_source[ForecastSource.ECMWF]),
                    },
                )
            )
        return results
