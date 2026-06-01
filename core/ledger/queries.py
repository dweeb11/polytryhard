from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from core.db.models import (
    AuditEventRow,
    CashEventRow,
    PaperPositionRow,
    SignalRow,
    StrategyInstanceRow,
    SystemStateRow,
)
from core.domain.audit import AuditEvent
from core.domain.cash_event import CashEvent
from core.domain.enums import (
    AuditActor,
    CashEventKind,
    PositionSide,
    SignalOutcome,
    StrategyState,
    SystemState,
)
from core.domain.strategy import StrategyConfig, StrategyInstance
from core.domain.system import SystemEnvState
from core.domain.trading import PaperPositionRecord, SignalRecord
from core.features.queries import latest_market_snapshot
from core.utils.time import format_dt, parse_iso, utc_now


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


def reserved_open_cost_basis_cents(session: Session, strategy_name: str) -> int:
    reserved = session.scalar(
        select(func.coalesce(func.sum(PaperPositionRow.cost_basis_cents), 0)).where(
            PaperPositionRow.strategy_name == strategy_name,
            PaperPositionRow.status == "open",
        )
    )
    return int(reserved or 0)


def free_cash_for_strategy(session: Session, strategy: StrategyInstanceRow) -> int:
    reserved = reserved_open_cost_basis_cents(session, strategy.name)
    return max(0, strategy.bankroll_cents - reserved)


def free_cash_cents(session: Session, strategy_name: str) -> int:
    strategy = session.get(StrategyInstanceRow, strategy_name)
    if strategy is None:
        return 0
    return free_cash_for_strategy(session, strategy)


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


def signal_from_row(row: SignalRow) -> SignalRecord:
    return SignalRecord(
        id=row.id,
        strategy_name=row.strategy_name,
        ticker=row.ticker,
        evaluated_at=format_dt(row.evaluated_at),
        prob_yes=float(row.prob_yes),
        confidence=float(row.confidence),
        features_snapshot=row.features_snapshot_jsonb,
        market_state=row.market_state_jsonb,
        outcome=SignalOutcome(row.outcome),
        rejection_reason=row.rejection_reason,
    )


def list_signals(
    session: Session,
    *,
    strategy_name: str | None = None,
    ticker: str | None = None,
    outcome: str | None = None,
    limit: int = 50,
    before: datetime | None = None,
) -> list[SignalRecord]:
    stmt = select(SignalRow).order_by(SignalRow.evaluated_at.desc()).limit(limit)
    if strategy_name is not None:
        stmt = stmt.where(SignalRow.strategy_name == strategy_name)
    if ticker is not None:
        stmt = stmt.where(SignalRow.ticker == ticker)
    if outcome is not None:
        stmt = stmt.where(SignalRow.outcome == outcome)
    if before is not None:
        stmt = stmt.where(SignalRow.evaluated_at < before)
    rows = session.scalars(stmt).all()
    return [signal_from_row(row) for row in rows]


def position_from_row(
    row: PaperPositionRow,
    *,
    unrealized_pnl_cents: int | None = None,
) -> PaperPositionRecord:
    unrealized = (
        unrealized_pnl_cents
        if unrealized_pnl_cents is not None
        else row.unrealized_pnl_cents
    )
    status = row.status.value if hasattr(row.status, "value") else str(row.status)
    return PaperPositionRecord(
        id=row.id,
        strategy_name=row.strategy_name,
        ticker=row.ticker,
        side=row.side,
        opened_at=format_dt(row.opened_at),
        closed_at=format_dt(row.closed_at) if row.closed_at else None,
        open_avg_price=float(row.open_avg_price),
        qty=row.qty,
        cost_basis_cents=row.cost_basis_cents,
        realized_pnl_cents=row.realized_pnl_cents,
        unrealized_pnl_cents=unrealized,
        status=status,
    )


def _utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _max_input_age_seconds(config_jsonb: dict[str, object]) -> int:
    raw = config_jsonb.get("maxInputAgeSeconds", config_jsonb.get("max_input_age_seconds", 900))
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    return 900


def _mark_price_for_side(side: PositionSide, mid_yes: Decimal) -> Decimal:
    if side == PositionSide.YES:
        return mid_yes
    return Decimal("1") - mid_yes


def _unrealized_pnl_cents(
    *,
    side: PositionSide,
    open_avg_price: Decimal,
    qty: int,
    mid_yes: Decimal,
) -> int:
    mark = _mark_price_for_side(side, mid_yes)
    pnl = (mark - open_avg_price) * Decimal(qty) * Decimal("100")
    return int(pnl.to_integral_value(rounding=ROUND_HALF_UP))


def _open_position_unrealized_pnl_cents(
    row: PaperPositionRow,
    *,
    shared_session: Session,
    strategy_configs: dict[str, dict[str, object]],
    now: datetime,
) -> int:
    config = strategy_configs.get(row.strategy_name, {})
    snapshot = latest_market_snapshot(
        shared_session,
        ticker=row.ticker,
        as_of=now,
    )
    if snapshot is None or snapshot.mid_yes is None:
        return 0
    max_age = _max_input_age_seconds(config)
    snapshot_as_of = _utc_aware(snapshot.as_of)
    as_of_cutoff = _utc_aware(now) - timedelta(seconds=max_age)
    if snapshot_as_of < as_of_cutoff:
        return 0
    side = PositionSide(row.side.value if hasattr(row.side, "value") else row.side)
    return _unrealized_pnl_cents(
        side=side,
        open_avg_price=row.open_avg_price,
        qty=row.qty,
        mid_yes=snapshot.mid_yes,
    )


def list_positions(
    session: Session,
    *,
    shared_session: Session | None = None,
    strategy_name: str | None = None,
    status: str | None = None,
    limit: int = 50,
    before: datetime | None = None,
) -> list[PaperPositionRecord]:
    stmt = select(PaperPositionRow).order_by(PaperPositionRow.opened_at.desc()).limit(limit)
    if strategy_name is not None:
        stmt = stmt.where(PaperPositionRow.strategy_name == strategy_name)
    if status is not None:
        stmt = stmt.where(PaperPositionRow.status == status)
    if before is not None:
        stmt = stmt.where(PaperPositionRow.opened_at < before)
    rows = session.scalars(stmt).all()

    strategy_configs: dict[str, dict[str, object]] = {}
    if shared_session is not None:
        names = {row.strategy_name for row in rows if row.status.value == "open"}
        if names:
            strategy_rows = session.scalars(
                select(StrategyInstanceRow).where(StrategyInstanceRow.name.in_(names))
            ).all()
            strategy_configs = {row.name: row.config_jsonb for row in strategy_rows}
        now = utc_now()

    results: list[PaperPositionRecord] = []
    for row in rows:
        unrealized: int | None = None
        if (
            shared_session is not None
            and row.status.value == "open"
        ):
            unrealized = _open_position_unrealized_pnl_cents(
                row,
                shared_session=shared_session,
                strategy_configs=strategy_configs,
                now=now,
            )
        results.append(position_from_row(row, unrealized_pnl_cents=unrealized))
    return results
