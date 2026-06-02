from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import PositionStatus
from core.db.models import CashEventRow, PaperFillRow, PaperPositionRow, SignalRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow
from core.eval.metrics import Trade

_WINDOW_DAYS: dict[str, int] = {"7d": 7, "30d": 30}


def _window_cutoff(window: str, now: datetime) -> datetime | None:
    days = _WINDOW_DAYS.get(window)
    return None if days is None else now - timedelta(days=days)


def resolved_trades(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    window: str,
    now: datetime,
) -> list[Trade]:
    """Resolved, signal-linked, non-void trades for a strategy in a window.

    prob_yes comes from the originating signal (per-env); outcome_yes comes from
    the shared contract_resolution. Positions without a signal, or whose market
    voided / has no resolution row, are excluded (design §5/§10).
    """
    cutoff = _window_cutoff(window, now)
    stmt = (
        select(PaperPositionRow, SignalRow.prob_yes)
        .join(PaperFillRow, PaperFillRow.position_id == PaperPositionRow.id)
        .join(SignalRow, SignalRow.id == PaperFillRow.signal_id)
        .where(
            PaperPositionRow.strategy_name == strategy_name,
            PaperPositionRow.status == PositionStatus.RESOLVED,
        )
    )
    if cutoff is not None:
        stmt = stmt.where(PaperPositionRow.closed_at >= cutoff)
    rows = per_env_session.execute(stmt).all()
    if not rows:
        return []

    tickers = {pos.ticker for pos, _ in rows}
    resolutions = {
        r.ticker: ContractResolution(r.resolution)
        for r in shared_session.scalars(
            select(ContractResolutionRow).where(ContractResolutionRow.ticker.in_(tickers))
        ).all()
    }

    trades: list[Trade] = []
    seen: set[str] = set()
    for pos, prob_yes in rows:
        if pos.id in seen:
            continue
        seen.add(pos.id)
        resolution = resolutions.get(pos.ticker)
        if resolution is None or resolution == ContractResolution.VOID:
            continue
        trades.append(
            Trade(
                prob_yes=float(prob_yes),
                outcome_yes=1 if resolution == ContractResolution.YES else 0,
                realized_pnl_cents=pos.realized_pnl_cents or 0,
                cost_basis_cents=pos.cost_basis_cents,
            )
        )
    return trades


def bankroll_balance_series(
    *,
    per_env_session: Session,
    strategy_name: str,
    window: str,
    now: datetime,
) -> list[int]:
    cutoff = _window_cutoff(window, now)
    stmt = (
        select(CashEventRow.balance_after_cents)
        .where(CashEventRow.strategy_name == strategy_name)
        .order_by(CashEventRow.occurred_at)
    )
    if cutoff is not None:
        stmt = stmt.where(CashEventRow.occurred_at >= cutoff)
    return [int(balance) for balance in per_env_session.scalars(stmt).all()]
