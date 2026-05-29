from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.db.shared_enums import SourceRunStatus
from core.db.shared_models import SourceRunRow
from core.settings import Settings
from core.sources.registry import registered_sources


@dataclass(frozen=True)
class SourceHealthRecord:
    name: str
    enabled: bool
    status: SourceRunStatus | None
    last_run_at: datetime | None
    last_success_at: datetime | None
    rows_last_run: int | None
    last_error: str | None


def _latest_runs(session: Session) -> dict[str, SourceRunRow]:
    subq = (
        select(
            SourceRunRow.source_name,
            func.max(SourceRunRow.started_at).label("max_started"),
        )
        .group_by(SourceRunRow.source_name)
        .subquery()
    )
    stmt: Select[tuple[SourceRunRow]] = select(SourceRunRow).join(
        subq,
        (SourceRunRow.source_name == subq.c.source_name)
        & (SourceRunRow.started_at == subq.c.max_started),
    )
    rows = session.scalars(stmt).all()
    return {row.source_name: row for row in rows}


def _last_success_at(session: Session, source_name: str) -> SourceRunRow | None:
    stmt = (
        select(SourceRunRow)
        .where(
            SourceRunRow.source_name == source_name,
            SourceRunRow.status == SourceRunStatus.OK,
        )
        .order_by(SourceRunRow.started_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def list_source_health(session: Session, settings: Settings) -> list[SourceHealthRecord]:
    latest = _latest_runs(session)
    entries: list[SourceHealthRecord] = []
    for source in registered_sources():
        run = latest.get(source.name)
        success = _last_success_at(session, source.name)
        entries.append(
            SourceHealthRecord(
                name=source.name,
                enabled=source.is_enabled(settings),
                status=run.status if run is not None else None,
                last_run_at=run.started_at if run is not None else None,
                last_success_at=success.started_at if success is not None else None,
                rows_last_run=run.rows_written if run is not None else None,
                last_error=run.error_text if run is not None else None,
            )
        )
    return entries
