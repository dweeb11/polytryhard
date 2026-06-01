"""Shared DB queries for feature providers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.db.shared_enums import ForecastSource
from core.db.shared_models import (
    RawForecastRunRow,
    RawMarketSnapshotRow,
    ReferenceLocationRow,
    ReferenceMarketRow,
)

TEMPERATURE_VARIABLE = "temperature_2m"


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def list_locations(session: Session) -> list[ReferenceLocationRow]:
    stmt = select(ReferenceLocationRow).order_by(ReferenceLocationRow.id)
    return list(session.scalars(stmt).all())


def list_open_markets(session: Session) -> list[ReferenceMarketRow]:
    return list(
        session.scalars(
            select(ReferenceMarketRow)
            .where(ReferenceMarketRow.status == "open")
            .order_by(ReferenceMarketRow.ticker)
        ).all()
    )


def resolve_target_valid_window(
    rows: list[RawForecastRunRow],
    *,
    as_of: datetime,
    target_window_start: datetime | None,
) -> datetime | None:
    if not rows:
        return None
    windows = {_as_utc(row.valid_window_start) for row in rows}
    if target_window_start is not None:
        target = _as_utc(target_window_start)
        return target if target in windows else None
    as_of_utc = _as_utc(as_of)
    eligible = [window for window in windows if window <= as_of_utc]
    if not eligible:
        return None
    return max(eligible)


def latest_forecast_rows(
    session: Session,
    *,
    location_id: str,
    source: ForecastSource,
    variable: str,
    as_of: datetime,
    target_window_start: datetime | None = None,
) -> list[RawForecastRunRow]:
    latest_run = session.scalar(
        select(func.max(RawForecastRunRow.run_time)).where(
            RawForecastRunRow.location_id == location_id,
            RawForecastRunRow.source == source,
            RawForecastRunRow.variable == variable,
            RawForecastRunRow.run_time <= as_of,
        )
    )
    if latest_run is None:
        return []
    stmt: Select[tuple[RawForecastRunRow]] = select(RawForecastRunRow).where(
        RawForecastRunRow.location_id == location_id,
        RawForecastRunRow.source == source,
        RawForecastRunRow.variable == variable,
        RawForecastRunRow.run_time == latest_run,
    )
    rows = list(session.scalars(stmt).all())
    window = resolve_target_valid_window(
        rows,
        as_of=as_of,
        target_window_start=target_window_start,
    )
    if window is None:
        return []
    return [row for row in rows if _as_utc(row.valid_window_start) == window]


def ensemble_mean(rows: list[RawForecastRunRow]) -> Decimal | None:
    if not rows:
        return None
    total = sum((row.value for row in rows), start=Decimal("0"))
    return total / Decimal(len(rows))


def latest_forecast_as_of(rows: list[RawForecastRunRow]) -> datetime | None:
    if not rows:
        return None
    return max(row.run_time for row in rows)


def latest_market_snapshot(
    session: Session,
    *,
    ticker: str,
    as_of: datetime,
) -> RawMarketSnapshotRow | None:
    stmt = (
        select(RawMarketSnapshotRow)
        .where(
            RawMarketSnapshotRow.ticker == ticker,
            RawMarketSnapshotRow.as_of <= as_of,
        )
        .order_by(RawMarketSnapshotRow.as_of.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()
