from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from core.db.models import AuditEventRow, CashEventRow, StrategyInstanceRow, SystemStateRow
from core.domain.cash_event import CashEvent
from core.domain.enums import AuditActor, CashEventKind, StrategyState, SystemState
from core.domain.state_machine import (
    can_activate,
    can_pause,
    can_resume,
    deposit_blocked_states,
    pause_target_state,
    resume_target_state,
    should_auto_resume_on_deposit,
)
from core.domain.strategy import StrategyConfig
from core.ledger.errors import LedgerError
from core.ledger.queries import cash_event_from_row, free_cash_cents, get_system_state
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


def _touch_strategy(row: StrategyInstanceRow, *, state: StrategyState | None = None) -> None:
    now = utc_now()
    row.updated_at = now
    row.last_state_change_at = now
    if state is not None:
        row.state = state.value


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
    if state in deposit_blocked_states():
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
        strategy.state = new_state.value

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
    raise NotImplementedError("record_realized_pnl is reserved for the paper executor")


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
    row.state = SystemState.PAUSED.value
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
    row.state = SystemState.ACTIVE.value
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
    strategy.state = target.value
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
    strategy.state = target.value
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
    strategy.state = StrategyState.DECOMMISSIONED.value
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
