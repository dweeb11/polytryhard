from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from core.clock import Clock
from core.contracts.source import FetchResult, IngestionSource, RawForecastRunDraft, SourceContext
from core.db.shared_enums import ForecastSource, SourceRunStatus
from core.settings import Settings

ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
HOURLY_VARIABLE = "temperature_2m"
FORECAST_HOURS = 168


class OpenMeteoSource(IngestionSource):
    @property
    def name(self) -> str:
        return "open_meteo"

    @property
    def schedule_seconds(self) -> int:
        return 3600

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def fetch(self, clock: Clock, ctx: SourceContext) -> FetchResult:
        if not ctx.locations:
            return FetchResult(
                status=SourceRunStatus.DEGRADED,
                error_text="No reference locations seeded",
            )

        result = FetchResult()
        ingested_at = clock.now()
        for location in ctx.locations:
            for model, source in (
                ("gfs_seamless", ForecastSource.GFS),
                ("ecmwf_ifs025", ForecastSource.ECMWF),
            ):
                query = urlencode(
                    {
                        "latitude": str(location.lat),
                        "longitude": str(location.lon),
                        "hourly": HOURLY_VARIABLE,
                        "models": model,
                        "forecast_hours": str(FORECAST_HOURS),
                        "timezone": location.timezone,
                    }
                )
                url = f"{ENSEMBLE_API}?{query}"
                response = await ctx.http.get(url)
                if response.status_code >= 400:
                    return FetchResult(
                        status=SourceRunStatus.DEGRADED,
                        error_text=f"Open-Meteo HTTP {response.status_code} for {location.id}",
                    )
                rows = parse_ensemble_response(
                    payload=response.json(),
                    source=source,
                    location_id=location.id,
                    ingested_at=ingested_at,
                    timezone=location.timezone,
                )
                result.forecast_runs.extend(rows)

        if not result.forecast_runs:
            return FetchResult(
                status=SourceRunStatus.DEGRADED,
                error_text="Open-Meteo returned no forecast rows",
            )
        return result


def parse_ensemble_response(
    *,
    payload: dict[str, Any],
    source: ForecastSource,
    location_id: str,
    ingested_at: datetime,
    timezone: str,
) -> list[RawForecastRunDraft]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    if not times:
        return []

    # Open-Meteo ensemble API does not expose model run init time; use ingested_at until a better field is identified.
    run_time = ingested_at

    rows: list[RawForecastRunDraft] = []
    member_keys = [
        key
        for key in hourly
        if key.startswith(f"{HOURLY_VARIABLE}_") and key != HOURLY_VARIABLE
    ]
    if not member_keys:
        member_keys = [HOURLY_VARIABLE]

    for member_index, member_key in enumerate(member_keys):
        values = hourly.get(member_key) or []
        for time_raw, value_raw in zip(times, values, strict=False):
            if value_raw is None:
                continue
            valid_start = _parse_time(time_raw, timezone)
            valid_end = valid_start + timedelta(hours=1)
            rows.append(
                RawForecastRunDraft(
                    source=source,
                    run_time=run_time,
                    ingested_at=ingested_at,
                    location_id=location_id,
                    valid_window_start=valid_start,
                    valid_window_end=valid_end,
                    variable=HOURLY_VARIABLE,
                    value=Decimal(str(value_raw)),
                    ensemble_member=member_index if len(member_keys) > 1 else None,
                    raw_jsonb={
                        "member_key": member_key,
                        "time": time_raw,
                        "value": value_raw,
                    },
                )
            )
    return rows


def _parse_time(value: str, timezone: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed.astimezone(UTC)
