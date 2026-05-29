import random

from sqlalchemy.orm import Session, sessionmaker

from core.db.models import StrategyInstanceRow
from core.domain.enums import AuditActor, StrategyState
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.reconcile import check_bankroll_invariant
from core.utils.time import utc_now


def _create_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name,
            enabled=True,
            state=StrategyState.SEEDED.value,
            bankroll_cents=0,
            initial_deposit_cents=0,
            bankroll_hwm_cents=0,
            hwm_reset_at=None,
            kelly_fraction=0.25,
            config_jsonb={
                "min_bankroll_cents": 1,
                "min_tradeable_bankroll_cents": 1,
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


def test_random_deposit_withdraw_sequences_keep_invariant(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    name = "prop_strategy"
    _create_strategy(session, name)
    rng = random.Random(42)
    req = 0
    for _ in range(20):
        amount = rng.randint(1, 5_000)
        if rng.random() < 0.6:
            writer.deposit(session, name, amount, "dep", AuditActor.USER, f"req-{req}")
            req += 1
            check_bankroll_invariant(session, name)
            session.commit()
        else:
            try:
                writer.withdraw(session, name, amount, "wd", AuditActor.USER, f"req-{req}")
                req += 1
                check_bankroll_invariant(session, name)
                session.commit()
            except LedgerError:
                session.rollback()
    session.close()
