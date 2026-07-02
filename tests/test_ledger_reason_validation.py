import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import StrategyInstanceRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.seed import seed_strategies_if_needed


@pytest.fixture
def session(per_env_session_factory: sessionmaker[Session]) -> Session:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-reason-validation")
    return session


@pytest.mark.parametrize("reason", ["", "   "])
def test_pause_strategy_rejects_blank_reason(
    session: Session, reason: str
) -> None:
    name = "weather_ensemble_disagreement"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    assert row.state == DbStrategyState.ACTIVE

    with pytest.raises(LedgerError, match="Reason is required"):
        writer.pause_strategy(session, name, reason, AuditActor.USER, "req-pause")

    session.refresh(row)
    assert row.state == DbStrategyState.ACTIVE


@pytest.mark.parametrize("reason", ["", "   "])
def test_resume_strategy_rejects_blank_reason(
    session: Session, reason: str
) -> None:
    name = "weather_ensemble_disagreement"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    row.state = DbStrategyState.OPERATOR_PAUSED
    session.commit()

    with pytest.raises(LedgerError, match="Reason is required to resume"):
        writer.resume_strategy(session, name, reason, AuditActor.USER, "req-resume")

    session.refresh(row)
    assert row.state == DbStrategyState.OPERATOR_PAUSED


@pytest.mark.parametrize("reason", ["", "   "])
def test_decommission_strategy_rejects_blank_reason(
    session: Session, reason: str
) -> None:
    name = "weather_ensemble_disagreement"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    before_state = row.state

    with pytest.raises(LedgerError, match="Reason is required"):
        writer.decommission_strategy(session, name, reason, AuditActor.USER, "req-decom")

    session.refresh(row)
    assert row.state == before_state
    assert row.enabled is True


def test_drawdown_pause_moves_active_strategy_to_drawdown_paused(
    session: Session,
) -> None:
    name = "weather_stale_quote"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None

    writer.drawdown_pause_strategy(
        session,
        name,
        "drawdown 31.0% >= 30.0% from HWM",
        AuditActor.SCHEDULER,
        "req-1",
    )

    session.refresh(row)
    assert row.state == DbStrategyState.DRAWDOWN_PAUSED


@pytest.mark.parametrize("reason", ["", "   "])
def test_drawdown_pause_strategy_rejects_blank_reason(
    session: Session, reason: str
) -> None:
    name = "weather_stale_quote"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    assert row.state == DbStrategyState.ACTIVE

    with pytest.raises(LedgerError, match="Reason is required"):
        writer.drawdown_pause_strategy(session, name, reason, AuditActor.SCHEDULER, "req-1")

    session.refresh(row)
    assert row.state == DbStrategyState.ACTIVE


def test_drawdown_pause_strategy_rejects_from_non_active_state(
    session: Session,
) -> None:
    name = "weather_stale_quote"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    row.state = DbStrategyState.OPERATOR_PAUSED
    session.commit()

    with pytest.raises(LedgerError, match="Cannot pause from state operator_paused"):
        writer.drawdown_pause_strategy(
            session, name, "drawdown check", AuditActor.SCHEDULER, "req-1"
        )

    session.refresh(row)
    assert row.state == DbStrategyState.OPERATOR_PAUSED
