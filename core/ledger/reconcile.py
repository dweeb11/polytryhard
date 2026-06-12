from sqlalchemy import func, select
from sqlalchemy.orm import Session

from core.db.models import CashEventRow, StrategyInstanceRow
from core.ledger.errors import LedgerError


def check_bankroll_invariant(session: Session, strategy_name: str) -> None:
    strategy = session.get(StrategyInstanceRow, strategy_name)
    if strategy is None:
        raise LedgerError(f"Strategy not found: {strategy_name}")
    total = session.scalar(
        select(func.coalesce(func.sum(CashEventRow.amount_cents), 0)).where(
            CashEventRow.strategy_name == strategy_name
        )
    )
    expected = int(total or 0)
    if strategy.bankroll_cents != expected:
        raise LedgerError(
            f"Bankroll invariant failed for {strategy_name}: "
            f"bankroll={strategy.bankroll_cents} sum(cash_event)={expected}"
        )
