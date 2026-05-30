from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from core.api.v1.deps import get_request_id, per_env_db, shared_db, verify_bearer_token
from core.api.v1.schemas import AmountReasonBody, ReasonBody, SetKellyBody, SourceHealthEntry
from core.domain.audit import AuditEvent
from core.domain.cash_event import CashEvent
from core.domain.enums import AuditActor
from core.domain.strategy import StrategyInstance
from core.domain.system import SystemEnvState
from core.domain.trading import PaperPositionRecord, SignalRecord
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.queries import (
    get_strategy,
    list_audit_events,
    list_cash_events,
    list_positions,
    list_signals,
    list_strategies,
    parse_before_cursor,
    strategy_instance_from_row,
)
from core.ledger.reconcile import check_bankroll_invariant
from core.settings import Settings, get_settings
from core.sources.queries import list_source_health
from core.utils.time import format_dt

router = APIRouter(prefix="/v1", dependencies=[Depends(verify_bearer_token)])


def _ledger_error(exc: LedgerError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=exc.message)


@router.get("/strategies", response_model=list[StrategyInstance])
def list_strategies_route(session: Session = Depends(per_env_db)) -> list[StrategyInstance]:
    return list_strategies(session)


@router.get("/strategies/{name}", response_model=StrategyInstance)
def get_strategy_route(name: str, session: Session = Depends(per_env_db)) -> StrategyInstance:
    row = get_strategy(session, name)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    return strategy_instance_from_row(row)


@router.get("/strategies/{name}/cash-events", response_model=list[CashEvent])
def list_cash_events_route(
    name: str,
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None),
    session: Session = Depends(per_env_db),
) -> list[CashEvent]:
    if get_strategy(session, name) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found")
    return list_cash_events(session, name, limit=limit, before=parse_before_cursor(before))


@router.post("/strategies/{name}/deposit", response_model=CashEvent)
def deposit_route(
    name: str,
    body: AmountReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> CashEvent:
    if body.amount_cents is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="amount_cents required",
        )
    try:
        event = writer.deposit(
            session,
            name,
            body.amount_cents,
            body.reason,
            AuditActor.USER,
            request_id,
        )
        check_bankroll_invariant(session, name)
        session.commit()
        return event
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/strategies/{name}/withdraw", response_model=CashEvent)
def withdraw_route(
    name: str,
    body: AmountReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> CashEvent:
    if body.amount_cents is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="amount_cents required",
        )
    try:
        event = writer.withdraw(
            session,
            name,
            body.amount_cents,
            body.reason,
            AuditActor.USER,
            request_id,
        )
        check_bankroll_invariant(session, name)
        session.commit()
        return event
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/strategies/{name}/pause", status_code=status.HTTP_204_NO_CONTENT)
def pause_route(
    name: str,
    body: ReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.pause_strategy(session, name, body.reason, AuditActor.USER, request_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/strategies/{name}/resume", status_code=status.HTTP_204_NO_CONTENT)
def resume_route(
    name: str,
    body: ReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.resume_strategy(session, name, body.reason, AuditActor.USER, request_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/strategies/{name}/set-kelly-fraction", status_code=status.HTTP_204_NO_CONTENT)
def set_kelly_route(
    name: str,
    body: SetKellyBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.set_kelly_fraction(
            session,
            name,
            body.fraction,
            body.reason,
            AuditActor.USER,
            request_id,
        )
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/strategies/{name}/decommission", status_code=status.HTTP_204_NO_CONTENT)
def decommission_route(
    name: str,
    body: ReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.decommission_strategy(session, name, body.reason, AuditActor.USER, request_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.get("/system", response_model=SystemEnvState)
def get_system_route(session: Session = Depends(per_env_db)) -> SystemEnvState:
    from core.ledger.queries import get_system_state

    return get_system_state(session)


@router.post("/system/pause", status_code=status.HTTP_204_NO_CONTENT)
def pause_system_route(
    body: ReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.apply_kill_switch(session, body.reason, AuditActor.USER, request_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.post("/system/resume", status_code=status.HTTP_204_NO_CONTENT)
def resume_system_route(
    body: ReasonBody,
    session: Session = Depends(per_env_db),
    request_id: str = Depends(get_request_id),
) -> None:
    try:
        writer.clear_kill_switch(session, body.reason, AuditActor.USER, request_id)
        session.commit()
    except LedgerError as exc:
        session.rollback()
        raise _ledger_error(exc) from exc


@router.get("/audit", response_model=list[AuditEvent])
def list_audit_route(
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    target_type: str | None = Query(default=None),
    session: Session = Depends(per_env_db),
) -> list[AuditEvent]:
    return list_audit_events(
        session,
        limit=limit,
        before=parse_before_cursor(before),
        actor=actor,
        action=action,
        target_type=target_type,
    )


@router.get("/sources", response_model=list[SourceHealthEntry])
def list_sources_route(
    session: Session = Depends(shared_db),
    settings: Settings = Depends(get_settings),
) -> list[SourceHealthEntry]:
    entries = list_source_health(session, settings)
    return [
        SourceHealthEntry(
            name=entry.name,
            enabled=entry.enabled,
            status=entry.status.value if entry.status is not None else None,
            last_run_at=format_dt(entry.last_run_at) if entry.last_run_at else None,
            last_success_at=format_dt(entry.last_success_at) if entry.last_success_at else None,
            rows_last_run=entry.rows_last_run,
            last_error=entry.last_error,
        )
        for entry in entries
    ]


@router.get("/signals", response_model=list[SignalRecord])
def list_signals_route(
    strategy_name: str | None = Query(default=None),
    ticker: str | None = Query(default=None),
    outcome: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None),
    session: Session = Depends(per_env_db),
) -> list[SignalRecord]:
    return list_signals(
        session,
        strategy_name=strategy_name,
        ticker=ticker,
        outcome=outcome,
        limit=limit,
        before=parse_before_cursor(before),
    )


@router.get("/positions", response_model=list[PaperPositionRecord])
def list_positions_route(
    strategy_name: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    before: str | None = Query(default=None),
    session: Session = Depends(per_env_db),
    shared_session: Session = Depends(shared_db),
) -> list[PaperPositionRecord]:
    return list_positions(
        session,
        shared_session=shared_session,
        strategy_name=strategy_name,
        status=status,
        limit=limit,
        before=parse_before_cursor(before),
    )
