from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import EVAL_WINDOWS, EvalWindow
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.domain.eval import CalibrationBin, EvalRosterEntry, EvalSnapshot, StrategyEval
from core.utils.time import format_dt

_ROSTER_WINDOW = EvalWindow.ALL


def _latest_row(
    session: Session, strategy_name: str, window: EvalWindow
) -> EvalMetricSnapshotRow | None:
    stmt = (
        select(EvalMetricSnapshotRow)
        .where(
            EvalMetricSnapshotRow.strategy_name == strategy_name,
            EvalMetricSnapshotRow.window == window,
        )
        .order_by(EvalMetricSnapshotRow.computed_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def latest_snapshots(session: Session, strategy_name: str) -> list[EvalMetricSnapshotRow]:
    """Most recent snapshot row per window for one strategy (omits windows with no rows)."""
    rows = []
    for window in EVAL_WINDOWS:
        row = _latest_row(session, strategy_name, window)
        if row is not None:
            rows.append(row)
    return rows


def snapshot_from_row(row: EvalMetricSnapshotRow) -> EvalSnapshot:
    return EvalSnapshot(
        window=row.window.value,
        computed_at=format_dt(row.computed_at),
        n_trades=row.n_trades,
        n_wins=row.n_wins,
        hit_rate=row.hit_rate,
        brier_score=row.brier_score,
        log_loss=row.log_loss,
        pnl_cents=row.pnl_cents,
        sharpe_proxy=row.sharpe_proxy,
        max_drawdown_cents=row.max_drawdown_cents,
        posterior_edge_mean=row.posterior_edge_mean,
        posterior_edge_ci_low=row.posterior_edge_ci_low,
        posterior_edge_ci_high=row.posterior_edge_ci_high,
        calibration_bins=[CalibrationBin(**b) for b in (row.calibration_bins_jsonb or [])],
    )


def strategy_eval(session: Session, strategy_name: str) -> StrategyEval:
    rows = latest_snapshots(session, strategy_name)
    return StrategyEval(
        strategy_name=strategy_name,
        windows=[snapshot_from_row(r) for r in rows],
    )


def _roster_entry(strategy_name: str, row: EvalMetricSnapshotRow | None) -> EvalRosterEntry:
    return EvalRosterEntry(
        strategy_name=strategy_name,
        n_trades=0 if row is None else row.n_trades,
        hit_rate=None if row is None else row.hit_rate,
        brier_score=None if row is None else row.brier_score,
        pnl_cents=0 if row is None else row.pnl_cents,
        posterior_edge_ci_low=None if row is None else row.posterior_edge_ci_low,
    )


def roster_summary(session: Session) -> list[EvalRosterEntry]:
    names = list(
        session.scalars(select(StrategyInstanceRow.name).order_by(StrategyInstanceRow.name)).all()
    )
    return [
        _roster_entry(name, _latest_row(session, name, _ROSTER_WINDOW))
        for name in names
    ]
