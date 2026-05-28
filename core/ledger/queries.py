from datetime import datetime

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.db.models import (
    AuditEventRow,
    CashEventRow,
    PaperPositionRow,
    StrategyInstanceRow,
    SystemStateRow,
)
from core.domain.audit import AuditEvent
from core.domain.cash_event import CashEvent
from core.domain.enums import AuditActor, CashEventKind, StrategyState, SystemState
from core.domain.strategy import StrategyConfig, StrategyInstance
from core.domain.system import SystemEnvState
from core.utils.time import format_dt, parse_iso


def _strategy_config(row: StrategyInstanceRow) -> StrategyConfig:
    raw = row.config_jsonb
    return StrategyConfig.model_validate(raw)


def strategy_instance_from_row(row: StrategyInstanceRow) -> StrategyInstance:
    return StrategyInstance(
        name=row.name,
        enabled=row.enabled,
        state=StrategyState(row.state),
        bankroll_cents=row.bankroll_cents,
        bankroll_hwm_cents=row.bankroll_hwm_cents,
        initial_deposit_cents=row.initial_deposit_cents,
        kelly_fraction=float(row.kelly_fraction),
        config=_strategy_config(row),
        last_state_change_at=format_dt(row.last_state_change_at),
        today_pnl_cents=0,
    )


def cash_event_from_row(row: CashEventRow) -> CashEvent:
    return CashEvent(
        id=row.id,
        strategy_name=row.strategy_name,
        occurred_at=format_dt(row.occurred_at),
        kind=CashEventKind(row.kind),
        amount_cents=row.amount_cents,
        balance_after_cents=row.balance_after_cents,
        reason=row.reason,
        ref_position_id=row.ref_position_id,
    )


def audit_event_from_row(row: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        id=row.id,
        occurred_at=format_dt(row.occurred_at),
        actor=AuditActor(row.actor),
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        before_state=row.before_state,
        after_state=row.after_state,
        reason=row.reason,
        request_id=row.request_id,
    )


def system_state_from_row(row: SystemStateRow) -> SystemEnvState:
    return SystemEnvState(
        state=SystemState(row.state),
        kill_switch_reason=row.kill_switch_reason,
        kill_switch_tripped_at=(
            format_dt(row.kill_switch_tripped_at) if row.kill_switch_tripped_at else None
        ),
    )


def get_strategy(session: Session, name: str) -> StrategyInstanceRow | None:
    return session.get(StrategyInstanceRow, name)


def list_strategies(session: Session) -> list[StrategyInstance]:
    rows = session.scalars(select(StrategyInstanceRow).order_by(StrategyInstanceRow.name)).all()
    return [strategy_instance_from_row(row) for row in rows]


def get_system_state(session: Session) -> SystemEnvState:
    row = session.get(SystemStateRow, 1)
    if row is None:
        raise RuntimeError("system_state row missing")
    return system_state_from_row(row)


def free_cash_cents(session: Session, strategy_name: str) -> int:
    strategy = session.get(StrategyInstanceRow, strategy_name)
    if strategy is None:
        return 0
    reserved = session.scalar(
        select(func.coalesce(func.sum(PaperPositionRow.cost_basis_cents), 0)).where(
            PaperPositionRow.strategy_name == strategy_name,
            PaperPositionRow.status == "open",
        )
    )
    reserved_int = int(reserved or 0)
    return max(0, strategy.bankroll_cents - reserved_int)


def list_cash_events(
    session: Session,
    strategy_name: str,
    *,
    limit: int = 50,
    before: datetime | None = None,
) -> list[CashEvent]:
    stmt: Select[tuple[CashEventRow]] = (
        select(CashEventRow)
        .where(CashEventRow.strategy_name == strategy_name)
        .order_by(CashEventRow.occurred_at.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(CashEventRow.occurred_at < before)
    rows = session.scalars(stmt).all()
    return [cash_event_from_row(row) for row in rows]


def list_audit_events(
    session: Session,
    *,
    limit: int = 50,
    before: datetime | None = None,
    actor: str | None = None,
    action: str | None = None,
    target_type: str | None = None,
) -> list[AuditEvent]:
    stmt = select(AuditEventRow).order_by(AuditEventRow.occurred_at.desc()).limit(limit)
    if before is not None:
        stmt = stmt.where(AuditEventRow.occurred_at < before)
    if actor is not None:
        stmt = stmt.where(AuditEventRow.actor == actor)
    if action is not None:
        stmt = stmt.where(AuditEventRow.action == action)
    if target_type is not None:
        stmt = stmt.where(AuditEventRow.target_type == target_type)
    rows = session.scalars(stmt).all()
    return [audit_event_from_row(row) for row in rows]


def parse_before_cursor(before: str | None) -> datetime | None:
    if before is None or not before.strip():
        return None
    return parse_iso(before)
