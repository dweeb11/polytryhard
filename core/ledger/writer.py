from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import PositionSide as DbPositionSide
from core.db.enums import PositionStatus as DbPositionStatus
from core.db.enums import SignalOutcome as DbSignalOutcome
from core.db.enums import StrategyState as DbStrategyState
from core.db.enums import SystemState as DbSystemState
from core.db.models import (
    AuditEventRow,
    CashEventRow,
    PaperFillRow,
    PaperPositionRow,
    SignalRow,
    StrategyInstanceRow,
    SystemStateRow,
)
from core.domain.cash_event import CashEvent
from core.domain.enums import (
    AuditActor,
    CashEventKind,
    PositionSide,
    SignalOutcome,
    StrategyState,
    SystemState,
)
from core.domain.market import MarketState, SignalDraft
from core.domain.state_machine import (
    DEPOSIT_BLOCKED_STATES,
    can_activate,
    can_pause,
    can_resume,
    pause_target_state,
    resume_target_state,
    should_auto_resume_on_deposit,
)
from core.domain.strategy import StrategyConfig
from core.ledger.errors import LedgerError
from core.ledger.queries import (
    cash_event_from_row,
    free_cash_cents,
    free_cash_for_strategy,
    get_system_state,
)
from core.utils.time import utc_now


def _new_id() -> str:
    return str(uuid4())


def _append_audit(
    session: Session,
    *,
    actor: AuditActor,
    action: str,
    target_type: str,
    target_id: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    reason: str,
    request_id: str,
) -> None:
    now = utc_now()
    session.add(
        AuditEventRow(
            id=_new_id(),
            occurred_at=now,
            actor=actor.value,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_state=before_state,
            after_state=after_state,
            reason=reason,
            request_id=request_id,
        )
    )


def _require_system_active(session: Session) -> None:
    if get_system_state(session).state == SystemState.PAUSED:
        raise LedgerError("System kill switch is active")


def _get_strategy_row(session: Session, strategy_name: str) -> StrategyInstanceRow:
    row = session.get(StrategyInstanceRow, strategy_name)
    if row is None:
        raise LedgerError("Strategy not found")
    return row


def _lock_strategy_row(session: Session, strategy_name: str) -> StrategyInstanceRow:
    row = session.execute(
        select(StrategyInstanceRow)
        .where(StrategyInstanceRow.name == strategy_name)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise LedgerError("Strategy not found")
    return row


def _expected_cost_basis_cents(qty: int, price: Decimal) -> int:
    total = (Decimal(qty) * price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(total)


def _touch_strategy(row: StrategyInstanceRow, *, state: StrategyState | None = None) -> None:
    now = utc_now()
    row.updated_at = now
    row.last_state_change_at = now
    if state is not None:
        row.state = DbStrategyState(state)


def _write_bankroll_event(
    session: Session,
    *,
    strategy: StrategyInstanceRow,
    kind: CashEventKind,
    amount_cents: int,
    balance_after_cents: int,
    reason: str,
    actor: AuditActor,
    request_id: str,
    audit_action: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    ref_position_id: str | None = None,
) -> CashEvent:
    now = utc_now()
    event_row = CashEventRow(
        id=_new_id(),
        strategy_name=strategy.name,
        occurred_at=now,
        kind=kind.value,
        amount_cents=amount_cents,
        balance_after_cents=balance_after_cents,
        reason=reason,
        ref_position_id=ref_position_id,
    )
    session.add(event_row)
    strategy.bankroll_cents = balance_after_cents
    _touch_strategy(strategy)
    _append_audit(
        session,
        actor=actor,
        action=audit_action,
        target_type="strategy",
        target_id=strategy.name,
        before_state=before_state,
        after_state=after_state,
        reason=reason,
        request_id=request_id,
    )
    session.flush()
    return cash_event_from_row(event_row)


def deposit(
    session: Session,
    strategy_name: str,
    amount_cents: int,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> CashEvent:
    _require_system_active(session)
    if amount_cents <= 0:
        raise LedgerError("Amount must be positive")
    strategy = _get_strategy_row(session, strategy_name)
    state = StrategyState(strategy.state)
    if state in DEPOSIT_BLOCKED_STATES:
        raise LedgerError("Cannot deposit to decommissioned strategy")

    before = {"bankrollCents": strategy.bankroll_cents, "state": strategy.state}
    new_bankroll = strategy.bankroll_cents + amount_cents
    config = StrategyConfig.model_validate(strategy.config_jsonb)
    new_state = state
    if should_auto_resume_on_deposit(
        current_state=state,
        auto_resume_on_deposit=config.auto_resume_on_deposit,
        new_bankroll_cents=new_bankroll,
        min_bankroll_cents=config.min_bankroll_cents,
    ):
        new_state = resume_target_state()
        strategy.state = DbStrategyState(new_state)

    after = {"bankrollCents": new_bankroll, "state": strategy.state}
    return _write_bankroll_event(
        session,
        strategy=strategy,
        kind=CashEventKind.DEPOSIT,
        amount_cents=amount_cents,
        balance_after_cents=new_bankroll,
        reason=reason,
        actor=actor,
        request_id=request_id,
        audit_action="deposit",
        before_state=before,
        after_state=after,
    )


def withdraw(
    session: Session,
    strategy_name: str,
    amount_cents: int,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> CashEvent:
    _require_system_active(session)
    if amount_cents <= 0:
        raise LedgerError("Amount must be positive")
    strategy = _get_strategy_row(session, strategy_name)
    free = free_cash_cents(session, strategy_name)
    if amount_cents > free:
        raise LedgerError(f"Withdrawal exceeds free cash ({free} cents available)")

    before = {"bankrollCents": strategy.bankroll_cents}
    new_bankroll = strategy.bankroll_cents - amount_cents
    after = {"bankrollCents": new_bankroll}
    return _write_bankroll_event(
        session,
        strategy=strategy,
        kind=CashEventKind.WITHDRAW,
        amount_cents=-amount_cents,
        balance_after_cents=new_bankroll,
        reason=reason,
        actor=actor,
        request_id=request_id,
        audit_action="withdraw",
        before_state=before,
        after_state=after,
    )


def record_realized_pnl(
    session: Session,
    strategy_name: str,
    amount_cents: int,
    reason: str,
    actor: AuditActor,
    request_id: str,
    *,
    ref_position_id: str | None = None,
) -> CashEvent:
    raise NotImplementedError("record_realized_pnl is reserved for M5 resolution")


def record_signal(
    session: Session,
    *,
    strategy_name: str,
    signal: SignalDraft,
    market: MarketState,
    features_snapshot: dict[str, object],
    outcome: SignalOutcome,
    rejection_reason: str | None,
    actor: AuditActor,
    request_id: str,
) -> SignalRow:
    _require_system_active(session)
    now = utc_now()
    signal_id = _new_id()
    row = SignalRow(
        id=signal_id,
        strategy_name=strategy_name,
        ticker=signal.ticker,
        evaluated_at=now,
        prob_yes=signal.prob_yes,
        confidence=signal.confidence,
        features_snapshot_jsonb=features_snapshot,
        market_state_jsonb=market.to_json(),
        outcome=DbSignalOutcome(outcome),
        rejection_reason=rejection_reason,
    )
    session.add(row)
    session.flush()
    _append_audit(
        session,
        actor=actor,
        action="record_signal",
        target_type="signal",
        target_id=signal_id,
        before_state={},
        after_state={
            "signalId": signal_id,
            "strategyName": strategy_name,
            "ticker": signal.ticker,
            "outcome": outcome.value,
        },
        reason=rejection_reason or f"signal outcome={outcome.value}",
        request_id=request_id,
    )
    session.flush()
    return row


def open_paper_position(
    session: Session,
    *,
    strategy_name: str,
    order_ticker: str,
    side: PositionSide,
    qty: int,
    price: Decimal,
    cost_basis_cents: int,
    signal_id: str | None,
    fees_cents: int,
    simulator_assumptions: dict[str, object],
    actor: AuditActor,
    request_id: str,
) -> tuple[PaperPositionRow, PaperFillRow]:
    _require_system_active(session)
    if qty <= 0:
        raise LedgerError("Quantity must be positive")
    if cost_basis_cents <= 0:
        raise LedgerError("Cost basis must be positive")
    if fees_cents < 0:
        raise LedgerError("Fees must be non-negative")
    expected_cost = _expected_cost_basis_cents(qty, price)
    if cost_basis_cents != expected_cost:
        raise LedgerError(
            f"Cost basis {cost_basis_cents} does not match qty×price ({expected_cost} cents)"
        )
    if signal_id is not None:
        signal_row = session.get(SignalRow, signal_id)
        if signal_row is None:
            raise LedgerError("Signal not found")
        if signal_row.strategy_name != strategy_name:
            raise LedgerError("Signal does not belong to strategy")

    strategy = _lock_strategy_row(session, strategy_name)
    free = free_cash_for_strategy(session, strategy)
    total_cost = cost_basis_cents + fees_cents
    if total_cost > free:
        raise LedgerError(f"Position exceeds free cash ({free} cents available)")

    now = utc_now()
    position = PaperPositionRow(
        id=_new_id(),
        strategy_name=strategy_name,
        ticker=order_ticker,
        side=DbPositionSide(side),
        opened_at=now,
        closed_at=None,
        open_avg_price=price,
        qty=qty,
        cost_basis_cents=cost_basis_cents,
        realized_pnl_cents=None,
        unrealized_pnl_cents=0,
        status=DbPositionStatus.OPEN,
    )
    session.add(position)
    session.flush()
    fill = PaperFillRow(
        id=_new_id(),
        position_id=position.id,
        signal_id=signal_id,
        filled_at=now,
        side=DbPositionSide(side),
        qty=qty,
        price=price,
        fees_cents=fees_cents,
        simulator_assumptions_jsonb=simulator_assumptions,
    )
    session.add(fill)
    session.flush()
    _append_audit(
        session,
        actor=actor,
        action="open_paper_position",
        target_type="paper_position",
        target_id=position.id,
        before_state={},
        after_state={
            "positionId": position.id,
            "fillId": fill.id,
            "costBasisCents": cost_basis_cents,
            "feesCents": fees_cents,
        },
        reason=f"paper fill position={position.id}",
        request_id=request_id,
    )
    if fees_cents > 0:
        before = {"bankrollCents": strategy.bankroll_cents}
        new_bankroll = strategy.bankroll_cents - fees_cents
        _write_bankroll_event(
            session,
            strategy=strategy,
            kind=CashEventKind.FEE,
            amount_cents=-fees_cents,
            balance_after_cents=new_bankroll,
            reason=f"paper fill fee position={position.id}",
            actor=actor,
            request_id=request_id,
            audit_action="paper_fill_fee",
            before_state=before,
            after_state={"bankrollCents": new_bankroll},
            ref_position_id=position.id,
        )
    return position, fill


def apply_kill_switch(
    session: Session,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required")
    row = session.get(SystemStateRow, 1)
    if row is None:
        raise LedgerError("system_state row missing")
    before = {
        "state": row.state,
        "killSwitchReason": row.kill_switch_reason,
        "killSwitchTrippedAt": (
            row.kill_switch_tripped_at.isoformat() if row.kill_switch_tripped_at else None
        ),
    }
    now = utc_now()
    row.state = DbSystemState.PAUSED
    row.kill_switch_reason = reason
    row.kill_switch_tripped_at = now
    row.updated_at = now
    after = {
        "state": row.state,
        "killSwitchReason": row.kill_switch_reason,
        "killSwitchTrippedAt": now.isoformat(),
    }
    _append_audit(
        session,
        actor=actor,
        action="trip_kill_switch",
        target_type="system",
        target_id="global",
        before_state=before,
        after_state=after,
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def clear_kill_switch(
    session: Session,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required to resume")
    row = session.get(SystemStateRow, 1)
    if row is None:
        raise LedgerError("system_state row missing")
    before = {
        "state": row.state,
        "killSwitchReason": row.kill_switch_reason,
        "killSwitchTrippedAt": (
            row.kill_switch_tripped_at.isoformat() if row.kill_switch_tripped_at else None
        ),
    }
    now = utc_now()
    row.state = DbSystemState.ACTIVE
    row.kill_switch_reason = None
    row.kill_switch_tripped_at = None
    row.updated_at = now
    after = {"state": row.state, "killSwitchReason": None, "killSwitchTrippedAt": None}
    _append_audit(
        session,
        actor=actor,
        action="resume_kill_switch",
        target_type="system",
        target_id="global",
        before_state=before,
        after_state=after,
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def set_kelly_fraction(
    session: Session,
    strategy_name: str,
    fraction: float,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    _require_system_active(session)
    strategy = _get_strategy_row(session, strategy_name)
    if StrategyState(strategy.state) == StrategyState.DECOMMISSIONED:
        raise LedgerError("Strategy is decommissioned")
    value = max(0.0, min(1.0, fraction))
    before = {"kellyFraction": float(strategy.kelly_fraction)}
    strategy.kelly_fraction = Decimal(str(value))
    _touch_strategy(strategy)
    after = {"kellyFraction": value}
    _append_audit(
        session,
        actor=actor,
        action="set_kelly_fraction",
        target_type="strategy",
        target_id=strategy_name,
        before_state=before,
        after_state=after,
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def activate_strategy(
    session: Session,
    strategy_name: str,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required")
    strategy = _get_strategy_row(session, strategy_name)
    state = StrategyState(strategy.state)
    if not can_activate(state):
        raise LedgerError(f"Cannot activate from state {state.value}")
    before = {"state": strategy.state}
    target = StrategyState.ACTIVE
    _touch_strategy(strategy, state=target)
    _append_audit(
        session,
        actor=actor,
        action="activate_strategy",
        target_type="strategy",
        target_id=strategy_name,
        before_state=before,
        after_state={"state": target.value},
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def pause_strategy(
    session: Session,
    strategy_name: str,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required")
    _require_system_active(session)
    strategy = _get_strategy_row(session, strategy_name)
    state = StrategyState(strategy.state)
    if not can_pause(state):
        raise LedgerError(f"Cannot pause from state {state.value}")
    before = {"state": strategy.state}
    target = pause_target_state()
    strategy.state = DbStrategyState(target)
    _touch_strategy(strategy, state=target)
    _append_audit(
        session,
        actor=actor,
        action="pause_strategy",
        target_type="strategy",
        target_id=strategy_name,
        before_state=before,
        after_state={"state": target.value},
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def resume_strategy(
    session: Session,
    strategy_name: str,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required to resume")
    _require_system_active(session)
    strategy = _get_strategy_row(session, strategy_name)
    state = StrategyState(strategy.state)
    if not can_resume(state):
        raise LedgerError(f"Cannot resume from state {state.value}")
    before = {"state": strategy.state}
    target = resume_target_state()
    strategy.state = DbStrategyState(target)
    _touch_strategy(strategy, state=target)
    _append_audit(
        session,
        actor=actor,
        action="resume_strategy",
        target_type="strategy",
        target_id=strategy_name,
        before_state=before,
        after_state={"state": target.value},
        reason=reason,
        request_id=request_id,
    )
    session.flush()


def decommission_strategy(
    session: Session,
    strategy_name: str,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    if not reason.strip():
        raise LedgerError("Reason is required")
    _require_system_active(session)
    strategy = _get_strategy_row(session, strategy_name)
    before = {"state": strategy.state, "enabled": strategy.enabled}
    strategy.enabled = False
    strategy.state = DbStrategyState(StrategyState.DECOMMISSIONED)
    _touch_strategy(strategy, state=StrategyState.DECOMMISSIONED)
    _append_audit(
        session,
        actor=actor,
        action="decommission",
        target_type="strategy",
        target_id=strategy_name,
        before_state=before,
        after_state={"state": StrategyState.DECOMMISSIONED.value, "enabled": False},
        reason=reason,
        request_id=request_id,
    )
    session.flush()
