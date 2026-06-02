from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.eval.metrics import EvalMetrics, compute_metrics
from core.eval.queries import bankroll_balance_series, resolved_trades

_WINDOWS: tuple[EvalWindow, ...] = (EvalWindow.D7, EvalWindow.D30, EvalWindow.ALL)
_DEFAULT_TAU = 0.5


def _strategy_tau(strategy: StrategyInstanceRow) -> float:
    raw = strategy.config_jsonb.get("posterior_tau", _DEFAULT_TAU)
    if isinstance(raw, (int, float)):
        return float(raw)
    return _DEFAULT_TAU


def write_snapshot(
    session: Session,
    *,
    strategy_name: str,
    window: EvalWindow,
    metrics: EvalMetrics,
    computed_at: datetime,
) -> EvalMetricSnapshotRow:
    row = EvalMetricSnapshotRow(
        id=str(uuid4()),
        strategy_name=strategy_name,
        computed_at=computed_at,
        window=window,
        n_trades=metrics.n_trades,
        n_wins=metrics.n_wins,
        hit_rate=metrics.hit_rate,
        brier_score=metrics.brier,
        log_loss=metrics.log_loss,
        pnl_cents=metrics.pnl_cents,
        sharpe_proxy=metrics.sharpe_proxy,
        max_drawdown_cents=metrics.max_drawdown_cents,
        posterior_edge_mean=metrics.posterior_edge_mean,
        posterior_edge_ci_low=metrics.posterior_edge_ci_low,
        posterior_edge_ci_high=metrics.posterior_edge_ci_high,
        calibration_bins_jsonb=[b.as_dict() for b in metrics.calibration_bins],
    )
    session.add(row)
    session.flush()
    return row


def recompute_strategy(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    now: datetime,
) -> None:
    strategy = per_env_session.get(StrategyInstanceRow, strategy_name)
    if strategy is None:
        return
    tau = _strategy_tau(strategy)
    for window in _WINDOWS:
        trades = resolved_trades(
            per_env_session=per_env_session,
            shared_session=shared_session,
            strategy_name=strategy_name,
            window=window.value,
            now=now,
        )
        balances = bankroll_balance_series(
            per_env_session=per_env_session,
            strategy_name=strategy_name,
            window=window.value,
            now=now,
        )
        metrics = compute_metrics(trades, balances=balances, tau=tau)
        write_snapshot(
            per_env_session,
            strategy_name=strategy_name,
            window=window,
            metrics=metrics,
            computed_at=now,
        )


def recompute_all(
    *,
    per_env_session: Session,
    shared_session: Session,
    now: datetime,
) -> None:
    names = list(
        per_env_session.scalars(select(StrategyInstanceRow.name)).all()
    )
    for name in names:
        recompute_strategy(
            per_env_session=per_env_session,
            shared_session=shared_session,
            strategy_name=name,
            now=now,
        )
