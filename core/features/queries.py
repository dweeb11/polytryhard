"""Shared DB queries for feature providers."""

from __future__ import annotations

from datetime import datetime
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


def latest_forecast_rows(
    session: Session,
    *,
    location_id: str,
    source: ForecastSource,
    variable: str,
    as_of: datetime,
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
    return list(session.scalars(stmt).all())


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
