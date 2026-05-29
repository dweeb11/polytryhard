import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import AuditEventRow, PaperPositionRow, StrategyInstanceRow
from core.domain.enums import AuditActor, StrategyState
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.reconcile import check_bankroll_invariant
from core.ledger.seed import INITIAL_DEPOSIT_CENTS, seed_strategies_if_needed
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
    writer.deposit(session, name, 50_000, "initial", AuditActor.USER, "req-0")
    writer.activate_strategy(session, name, "test setup", AuditActor.USER, "req-0")
    session.commit()


def test_seed_is_idempotent(per_env_session_factory: sessionmaker[Session]) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-1")

    names = {row.name for row in session.scalars(select(StrategyInstanceRow)).all()}
    assert "weather_ensemble_disagreement" in names
    count_after_first = session.scalar(select(func.count()).select_from(StrategyInstanceRow))
    seed_strategies_if_needed(session, request_id="seed-2")
    count_after_second = session.scalar(select(func.count()).select_from(StrategyInstanceRow))
    assert count_after_second == count_after_first
    row = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert row is not None
    assert row.state == DbStrategyState.ACTIVE
    assert row.bankroll_cents == INITIAL_DEPOSIT_CENTS
    check_bankroll_invariant(session, row.name)
    activation = session.scalars(
        select(AuditEventRow).where(
            AuditEventRow.target_id == "weather_ensemble_disagreement",
            AuditEventRow.action == "activate_strategy",
        )
    ).first()
    assert activation is not None
    assert activation.before_state == {"state": StrategyState.SEEDED.value}
    assert activation.after_state == {"state": StrategyState.ACTIVE.value}
    session.close()


def test_deposit_does_not_raise_hwm(per_env_session_factory: sessionmaker[Session]) -> None:
    session = per_env_session_factory()
    _create_strategy(session, "hwm_strategy")
    row = session.get(StrategyInstanceRow, "hwm_strategy")
    assert row is not None
    row.bankroll_cents = 60_000
    row.bankroll_hwm_cents = 100_000
    session.commit()

    writer.deposit(
        session,
        "hwm_strategy",
        50_000,
        "top up bleeding strategy",
        AuditActor.USER,
        "req-hwm",
    )
    session.commit()

    row = session.get(StrategyInstanceRow, "hwm_strategy")
    assert row is not None
    assert row.bankroll_cents == 110_000
    assert row.bankroll_hwm_cents == 100_000
    session.close()


def test_deposit_and_withdraw_invariant(per_env_session_factory: sessionmaker[Session]) -> None:
    session = per_env_session_factory()
    _create_strategy(session, "test_strategy")
    writer.deposit(session, "test_strategy", 5_000, "top up", AuditActor.USER, "req-1")
    check_bankroll_invariant(session, "test_strategy")
    session.commit()

    session.add(
        PaperPositionRow(
            id="pos-1",
            strategy_name="test_strategy",
            ticker="TICK",
            side="yes",
            opened_at=utc_now(),
            closed_at=None,
            open_avg_price=0.5,
            qty=10,
            cost_basis_cents=20_000,
            realized_pnl_cents=None,
            unrealized_pnl_cents=0,
            status="open",
        )
    )
    session.commit()

    with pytest.raises(LedgerError, match="free cash"):
        writer.withdraw(session, "test_strategy", 50_000, "too much", AuditActor.USER, "req-2")

    writer.withdraw(session, "test_strategy", 1_000, "partial", AuditActor.USER, "req-3")
    check_bankroll_invariant(session, "test_strategy")
    session.commit()
    session.close()
