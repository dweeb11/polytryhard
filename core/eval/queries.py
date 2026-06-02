from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow, PositionStatus
from core.db.models import CashEventRow, PaperFillRow, PaperPositionRow, SignalRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow
from core.eval.metrics import Trade

_WINDOW_DAYS: dict[EvalWindow, int | None] = {
    EvalWindow.D7: 7,
    EvalWindow.D30: 30,
    EvalWindow.ALL: None,
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _window_cutoff(window: EvalWindow, now: datetime) -> datetime | None:
    days = _WINDOW_DAYS[window]
    return None if days is None else _as_utc(now) - timedelta(days=days)


@dataclass(frozen=True)
class ResolvedTradeRecord:
    trade: Trade
    closed_at: datetime


def trades_for_window(
    records: list[ResolvedTradeRecord],
    window: EvalWindow,
    now: datetime,
) -> list[Trade]:
    cutoff = _window_cutoff(window, now)
    if cutoff is None:
        return [record.trade for record in records]
    return [record.trade for record in records if _as_utc(record.closed_at) >= cutoff]


def resolved_trade_records(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    now: datetime,
) -> list[ResolvedTradeRecord]:
    """Resolved, signal-linked, non-void trades for a strategy (all-time fetch).

    prob_yes comes from the originating signal (per-env); outcome_yes comes from
    the shared contract_resolution. Positions without a signal, or whose market
    voided / has no resolution row, are excluded (design §5/§10).
    """
    stmt = (
        select(PaperPositionRow, SignalRow.prob_yes)
        .join(PaperFillRow, PaperFillRow.position_id == PaperPositionRow.id)
        .join(SignalRow, SignalRow.id == PaperFillRow.signal_id)
        .where(
            PaperPositionRow.strategy_name == strategy_name,
            PaperPositionRow.status == PositionStatus.RESOLVED,
        )
    )
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

    records: list[ResolvedTradeRecord] = []
    # Join through paper_fill yields one row per fill; a position may have
    # multiple fills — dedupe so each position contributes one Trade.
    seen: set[str] = set()
    for pos, prob_yes in rows:
        if pos.id in seen:
            continue
        seen.add(pos.id)
        if pos.closed_at is None:
            continue
        resolution = resolutions.get(pos.ticker)
        if resolution is None or resolution == ContractResolution.VOID:
            continue
        records.append(
            ResolvedTradeRecord(
                trade=Trade(
                    prob_yes=float(prob_yes),
                    outcome_yes=1 if resolution == ContractResolution.YES else 0,
                    realized_pnl_cents=pos.realized_pnl_cents or 0,
                    cost_basis_cents=pos.cost_basis_cents,
                ),
                closed_at=pos.closed_at,
            )
        )
    return records


def resolved_trades(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    window: EvalWindow,
    now: datetime,
) -> list[Trade]:
    records = resolved_trade_records(
        per_env_session=per_env_session,
        shared_session=shared_session,
        strategy_name=strategy_name,
        now=now,
    )
    return trades_for_window(records, window, now)


def bankroll_cash_events(
    *,
    per_env_session: Session,
    strategy_name: str,
) -> list[tuple[datetime, int]]:
    stmt = (
        select(CashEventRow.occurred_at, CashEventRow.balance_after_cents)
        .where(CashEventRow.strategy_name == strategy_name)
        .order_by(CashEventRow.occurred_at)
    )
    return [
        (occurred_at, int(balance))
        for occurred_at, balance in per_env_session.execute(stmt).all()
    ]


def balances_for_window(
    events: list[tuple[datetime, int]],
    window: EvalWindow,
    now: datetime,
) -> list[int]:
    cutoff = _window_cutoff(window, now)
    if cutoff is None:
        return [balance for _, balance in events]
    return [balance for occurred_at, balance in events if _as_utc(occurred_at) >= cutoff]


def bankroll_balance_series(
    *,
    per_env_session: Session,
    strategy_name: str,
    window: EvalWindow,
    now: datetime,
) -> list[int]:
    events = bankroll_cash_events(per_env_session=per_env_session, strategy_name=strategy_name)
    return balances_for_window(events, window, now)
