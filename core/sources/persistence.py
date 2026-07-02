from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.contracts.source import (
    FetchResult,
    ReferenceLocation,
    ReferenceMarketUpsert,
)
from core.db.shared_enums import SourceRunStatus
from core.db.shared_models import (
    ContractResolutionRow,
    RawForecastRunRow,
    RawMarketSnapshotRow,
    ReferenceLocationRow,
    ReferenceMarketRow,
    SourceRunRow,
)


def _new_id() -> str:
    return str(uuid4())


def load_locations(session: Session) -> tuple[ReferenceLocation, ...]:
    rows = session.scalars(select(ReferenceLocationRow).order_by(ReferenceLocationRow.id)).all()
    return tuple(
        ReferenceLocation(
            id=row.id,
            station_code=row.station_code,
            name=row.name,
            lat=row.lat,
            lon=row.lon,
            timezone=row.timezone,
            source=row.source,
        )
        for row in rows
    )


def load_resolved_tickers(session: Session) -> frozenset[str]:
    rows = session.scalars(select(ContractResolutionRow.ticker)).all()
    return frozenset(rows)


def load_markets(session: Session) -> tuple[ReferenceMarketUpsert, ...]:
    rows = session.scalars(select(ReferenceMarketRow).order_by(ReferenceMarketRow.ticker)).all()
    return tuple(
        ReferenceMarketUpsert(
            ticker=row.ticker,
            series=row.series,
            title=row.title,
            status=row.status,
            settlement_source=row.settlement_source,
            settlement_ref=row.settlement_ref,
            open_time=row.open_time,
            close_time=row.close_time,
            settlement_time=row.settlement_time,
            strike_type=row.strike_type,
            floor_strike=row.floor_strike,
            cap_strike=row.cap_strike,
            raw_jsonb=row.raw_jsonb,
        )
        for row in rows
    )


def persist_fetch_result(
    session: Session,
    *,
    source_name: str,
    request_id: str,
    started_at: datetime,
    finished_at: datetime,
    result: FetchResult,
) -> SourceRunRow:
    source_run_id = _new_id()
    run_row = SourceRunRow(
        id=source_run_id,
        source_name=source_name,
        started_at=started_at,
        finished_at=finished_at,
        status=result.status,
        rows_written=result.rows_written,
        error_text=result.error_text,
        request_id=request_id,
    )
    session.add(run_row)

    for upsert in result.market_upserts:
        existing = session.get(ReferenceMarketRow, upsert.ticker)
        if existing is None:
            session.add(
                ReferenceMarketRow(
                    ticker=upsert.ticker,
                    series=upsert.series,
                    title=upsert.title,
                    settlement_source=upsert.settlement_source,
                    settlement_ref=upsert.settlement_ref,
                    open_time=upsert.open_time,
                    close_time=upsert.close_time,
                    settlement_time=upsert.settlement_time,
                    status=upsert.status,
                    strike_type=upsert.strike_type,
                    floor_strike=upsert.floor_strike,
                    cap_strike=upsert.cap_strike,
                    raw_jsonb=upsert.raw_jsonb,
                )
            )
        else:
            existing.series = upsert.series
            existing.title = upsert.title
            existing.settlement_source = upsert.settlement_source
            existing.settlement_ref = upsert.settlement_ref
            existing.open_time = upsert.open_time
            existing.close_time = upsert.close_time
            existing.settlement_time = upsert.settlement_time
            existing.status = upsert.status
            existing.strike_type = upsert.strike_type
            existing.floor_strike = upsert.floor_strike
            existing.cap_strike = upsert.cap_strike
            existing.raw_jsonb = upsert.raw_jsonb

    session.flush()

    for resolution in result.resolutions:
        if session.get(ContractResolutionRow, resolution.ticker) is not None:
            continue
        session.add(
            ContractResolutionRow(
                ticker=resolution.ticker,
                resolved_at=resolution.resolved_at,
                resolution=resolution.resolution,
                settlement_value=resolution.settlement_value,
                source_evidence_jsonb=resolution.source_evidence_jsonb,
            )
        )

    for snapshot in result.market_snapshots:
        session.add(
            RawMarketSnapshotRow(
                id=_new_id(),
                ticker=snapshot.ticker,
                as_of=snapshot.as_of,
                bid_yes=snapshot.bid_yes,
                ask_yes=snapshot.ask_yes,
                mid_yes=snapshot.mid_yes,
                bid_size=snapshot.bid_size,
                ask_size=snapshot.ask_size,
                last_trade_price=snapshot.last_trade_price,
                last_trade_size=snapshot.last_trade_size,
                source_run_id=source_run_id,
                raw_jsonb=snapshot.raw_jsonb,
            )
        )

    for forecast in result.forecast_runs:
        session.add(
            RawForecastRunRow(
                id=_new_id(),
                source=forecast.source,
                run_time=forecast.run_time,
                ingested_at=forecast.ingested_at,
                location_id=forecast.location_id,
                valid_window_start=forecast.valid_window_start,
                valid_window_end=forecast.valid_window_end,
                variable=forecast.variable,
                value=forecast.value,
                ensemble_member=forecast.ensemble_member,
                raw_jsonb=forecast.raw_jsonb,
            )
        )

    session.commit()
    return run_row


@dataclass
class SourceHealthSnapshot:
    name: str
    enabled: bool
    status: SourceRunStatus
    last_run_at: datetime | None
    last_success_at: datetime | None
    rows_last_run: int | None
    last_error: str | None
    consecutive_failures: int


@dataclass
class _RuntimeHealth:
    status: SourceRunStatus = SourceRunStatus.OK
    last_run_at: datetime | None = None
    last_success_at: datetime | None = None
    rows_last_run: int | None = None
    last_error: str | None = None
    consecutive_failures: int = 0


class SourceHealthTracker:
    def __init__(self, *, failure_threshold: int) -> None:
        self._failure_threshold = failure_threshold
        self._health: dict[str, _RuntimeHealth] = {}

    def record_success(
        self,
        source_name: str,
        *,
        finished_at: datetime,
        rows_written: int,
        run_status: SourceRunStatus,
        error_text: str | None,
    ) -> None:
        health = self._health.setdefault(source_name, _RuntimeHealth())
        health.last_run_at = finished_at
        health.rows_last_run = rows_written
        health.last_error = error_text
        if run_status == SourceRunStatus.OK:
            health.status = SourceRunStatus.OK
            health.last_success_at = finished_at
            health.consecutive_failures = 0
        elif run_status == SourceRunStatus.DEGRADED:
            health.status = SourceRunStatus.DEGRADED
            health.consecutive_failures = 0
        else:
            health.consecutive_failures += 1
            health.status = (
                SourceRunStatus.DEGRADED
                if health.consecutive_failures >= self._failure_threshold
                else SourceRunStatus.ERROR
            )

    def record_failure(self, source_name: str, *, finished_at: datetime, error: str) -> None:
        health = self._health.setdefault(source_name, _RuntimeHealth())
        health.last_run_at = finished_at
        health.rows_last_run = None
        health.last_error = error
        health.consecutive_failures += 1
        health.status = (
            SourceRunStatus.DEGRADED
            if health.consecutive_failures >= self._failure_threshold
            else SourceRunStatus.ERROR
        )

    def get(self, source_name: str) -> _RuntimeHealth:
        return self._health.setdefault(source_name, _RuntimeHealth())
