from collections.abc import Generator
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import CashEventRow, PaperPositionRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.domain.enums import AuditActor, CashEventKind, PositionSide
from core.ledger import writer
from core.ledger.queries import free_cash_cents
from core.utils.time import utc_now


def _create_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name,
            enabled=True,
            state=DbStrategyState.SEEDED,
            bankroll_cents=0,
            initial_deposit_cents=0,
            bankroll_hwm_cents=0,
            hwm_reset_at=None,
            kelly_fraction=0.25,
            config_jsonb={
                "min_bankroll_cents": 10_000,
                "min_tradeable_bankroll_cents": 5_000,
                "max_drawdown_pct_from_hwm": 30,
                "auto_resume_on_deposit": True,
                "max_input_age_seconds": 900,
            },
            consecutive_min_position_rejections=0,
            last_state_change_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "req-seed")
    writer.activate_strategy(session, name, "test setup", AuditActor.USER, "req-seed")
    session.commit()


@pytest.fixture
def session(per_env_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    s = per_env_session_factory()
    yield s
    s.close()


def _open(
    session: Session, *, name: str, side: PositionSide, qty: int, price: str
) -> PaperPositionRow:
    cost = int((Decimal(qty) * Decimal(price) * 100).to_integral_value())
    pos, _ = writer.open_paper_position(
        session,
        strategy_name=name,
        order_ticker="KXT",
        side=side,
        qty=qty,
        price=Decimal(price),
        cost_basis_cents=cost,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="req-open",
    )
    return pos


def test_resolve_yes_position_wins(session: Session) -> None:
    name = "strat_a"
    _create_strategy(session, name)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    assert free_cash_cents(session, name) == 100_00 - 400

    writer.resolve_position(
        session,
        position=pos,
        resolution=ContractResolution.YES,
        settlement_value=Decimal("1"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res",
    )
    session.flush()
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 1000 - 400
    strat = session.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00 + 600
    assert strat.bankroll_hwm_cents == 100_00 + 600
    pnl_events = [
        e
        for e in session.query(CashEventRow).all()
        if e.kind == CashEventKind.REALIZED_PNL.value and e.ref_position_id == pos.id
    ]
    assert len(pnl_events) == 1 and pnl_events[0].amount_cents == 600


def test_resolve_yes_position_loses(session: Session) -> None:
    name = "strat_b"
    _create_strategy(session, name)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    writer.resolve_position(
        session,
        position=pos,
        resolution=ContractResolution.NO,
        settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res",
    )
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    assert refreshed.realized_pnl_cents == -400
    strat = session.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00 - 400


def test_resolve_void_refunds(session: Session) -> None:
    name = "strat_c"
    _create_strategy(session, name)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    writer.resolve_position(
        session,
        position=pos,
        resolution=ContractResolution.VOID,
        settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res",
    )
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 0
    strat = session.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00
    assert free_cash_cents(session, name) == 100_00


def test_resolve_void_emits_single_zero_realized_pnl_event(session: Session) -> None:
    name = "strat_void_pnl"
    _create_strategy(session, name)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    writer.resolve_position(
        session,
        position=pos,
        resolution=ContractResolution.VOID,
        settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res",
    )
    session.flush()
    pnl_events = [
        e
        for e in session.query(CashEventRow).all()
        if e.kind == CashEventKind.REALIZED_PNL.value and e.ref_position_id == pos.id
    ]
    assert len(pnl_events) == 1
    assert pnl_events[0].amount_cents == 0


def test_resolve_is_idempotent(session: Session) -> None:
    name = "strat_d"
    _create_strategy(session, name)
    pos = _open(session, name=name, side=PositionSide.NO, qty=5, price="0.30")
    writer.resolve_position(
        session,
        position=pos,
        resolution=ContractResolution.NO,
        settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res",
    )
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    writer.resolve_position(
        session,
        position=refreshed,
        resolution=ContractResolution.NO,
        settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="req-res-2",
    )
    strat = session.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00 + 350
