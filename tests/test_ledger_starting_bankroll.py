from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import AuditEventRow, CashEventRow, SignalRow, StrategyInstanceRow
from core.domain.enums import AuditActor, SignalOutcome
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.seed import seed_strategies_if_needed
from core.utils.time import utc_now


def _seeded_session(factory: sessionmaker[Session]) -> Session:
    session = factory()
    seed_strategies_if_needed(session, request_id="seed")
    return session


def test_set_starting_bankroll_writes_delta_and_baseline(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = _seeded_session(per_env_session_factory)
    writer.set_starting_bankroll(
        session,
        "weather_ensemble_disagreement",
        25_000,
        "pre-soak bankroll",
        AuditActor.USER,
        "rq-start",
    )
    session.commit()

    strategy = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert strategy is not None
    assert strategy.bankroll_cents == 25_000
    assert strategy.initial_deposit_cents == 25_000
    assert strategy.bankroll_hwm_cents == 25_000

    events = session.scalars(
        select(CashEventRow)
        .where(CashEventRow.strategy_name == "weather_ensemble_disagreement")
        .order_by(CashEventRow.occurred_at)
    ).all()
    assert [event.amount_cents for event in events] == [10_000, 15_000]
    assert [event.balance_after_cents for event in events] == [10_000, 25_000]

    actions = session.scalars(
        select(AuditEventRow.action).where(
            AuditEventRow.target_id == "weather_ensemble_disagreement"
        )
    ).all()
    assert "set_starting_bankroll_deposit" in actions
    assert "set_starting_bankroll" in actions
    session.close()


def test_set_starting_bankroll_can_correct_hwm_without_delta(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = _seeded_session(per_env_session_factory)
    writer.set_starting_bankroll(
        session,
        "weather_stale_quote",
        10_000,
        "baseline correction",
        AuditActor.USER,
        "rq-start",
    )
    session.commit()

    strategy = session.get(StrategyInstanceRow, "weather_stale_quote")
    assert strategy is not None
    assert strategy.bankroll_cents == 10_000
    assert strategy.initial_deposit_cents == 10_000
    assert strategy.bankroll_hwm_cents == 10_000
    event_count = session.scalar(
        select(func.count())
        .select_from(CashEventRow)
        .where(CashEventRow.strategy_name == "weather_stale_quote")
    )
    assert event_count == 1
    session.close()


def test_set_starting_bankroll_rejects_after_signal(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = _seeded_session(per_env_session_factory)
    session.add(
        SignalRow(
            id="signal-1",
            strategy_name="weather_ensemble_disagreement",
            ticker="KXTEST",
            evaluated_at=utc_now(),
            prob_yes=Decimal("0.55"),
            confidence=Decimal("0.55"),
            features_snapshot_jsonb={},
            market_state_jsonb={},
            outcome=SignalOutcome.REJECTED_STALE_INPUTS,
            rejection_reason="test",
        )
    )
    session.commit()

    with pytest.raises(LedgerError, match="before signals"):
        writer.set_starting_bankroll(
            session,
            "weather_ensemble_disagreement",
            25_000,
            "too late",
            AuditActor.USER,
            "rq-start",
        )
    session.close()
