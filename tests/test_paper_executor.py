from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.contracts.executor import ExecutorContext
from core.db.models import PaperFillRow, PaperPositionRow, StrategyInstanceRow
from core.domain.enums import PositionSide
from core.domain.trading import Order
from core.executors.paper.executor import PaperExecutor
from core.ledger.seed import seed_strategies_if_needed


@pytest.mark.asyncio
async def test_paper_executor_writes_position_and_fill(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
    assert strategy is not None
    bankroll_before = strategy.bankroll_cents

    executor = PaperExecutor()
    order = Order(
        ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=5,
        limit_price=Decimal("0.55"),
        cost_basis_cents=275,
    )
    fill = await executor.place(
        order,
        ExecutorContext(
            request_id="exec-test",
            session=session,
            strategy_name=strategy.name,
            signal_id=None,
            fees_cents=0,
        ),
    )
    session.commit()

    position = session.get(PaperPositionRow, fill.position_id)
    paper_fill = session.get(PaperFillRow, fill.fill_id)
    strategy = session.get(StrategyInstanceRow, strategy.name)
    assert position is not None
    assert paper_fill is not None
    assert position.status.value == "open"
    assert position.cost_basis_cents == 275
    assert strategy is not None
    assert strategy.bankroll_cents == bankroll_before
