from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from core.eval.posterior import posterior_edge

_LOG_LOSS_EPS = 1e-9


@dataclass(frozen=True)
class Trade:
    """A resolved, signal-linked, non-void paper trade.

    prob_yes: the originating signal's predicted P(market resolves YES), in [0, 1].
    outcome_yes: the realized market outcome from the contract resolution (1 if YES, 0 if NO).
    realized_pnl_cents / cost_basis_cents: per-position P&L and reserved cost basis.
    cost_basis_cents must be > 0 (ledger rejects zero at open); ROI metrics divide by it.
    """

    prob_yes: float
    outcome_yes: int
    realized_pnl_cents: int
    cost_basis_cents: int

    def __post_init__(self) -> None:
        if self.cost_basis_cents <= 0:
            raise ValueError(
                f"cost_basis_cents must be > 0 for ROI metrics, got {self.cost_basis_cents}"
            )


@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    predicted_mean: float
    observed_freq: float
    count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "predicted_mean": self.predicted_mean,
            "observed_freq": self.observed_freq,
            "count": self.count,
        }


@dataclass(frozen=True)
class EvalMetrics:
    """Aggregated metrics for a strategy × window.

    n_wins: trades with realized_pnl_cents > 0 (P&L-based, not outcome_yes).
    """

    n_trades: int
    n_wins: int
    hit_rate: float | None
    brier: float | None
    log_loss: float | None
    pnl_cents: int
    sharpe_proxy: float | None
    max_drawdown_cents: int
    posterior_edge_mean: float
    posterior_edge_ci_low: float
    posterior_edge_ci_high: float
    calibration_bins: list[CalibrationBin]


def n_trades(trades: list[Trade]) -> int:
    return len(trades)


def n_wins(trades: list[Trade]) -> int:
    """Trades with positive realized P&L (not outcome_yes-based wins)."""
    return sum(1 for t in trades if t.realized_pnl_cents > 0)


def hit_rate(trades: list[Trade]) -> float | None:
    """n_wins / n_trades; None when there are no trades."""
    total = len(trades)
    if total == 0:
        return None
    return n_wins(trades) / total


def brier(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    return sum((t.prob_yes - t.outcome_yes) ** 2 for t in trades) / len(trades)


def log_loss(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    total = 0.0
    for t in trades:
        p = min(max(t.prob_yes, _LOG_LOSS_EPS), 1.0 - _LOG_LOSS_EPS)
        total += t.outcome_yes * math.log(p) + (1 - t.outcome_yes) * math.log(1.0 - p)
    return -total / len(trades)


def pnl_cents(trades: list[Trade]) -> int:
    return sum(t.realized_pnl_cents for t in trades)


def _rois(trades: list[Trade]) -> list[float]:
    """Per-trade ROI; every trade must have cost_basis_cents > 0 (enforced on Trade)."""
    return [t.realized_pnl_cents / t.cost_basis_cents for t in trades]


def sharpe_proxy(trades: list[Trade]) -> float | None:
    rois = _rois(trades)
    if len(rois) < 2:
        return None
    sd = statistics.stdev(rois)
    if sd == 0:
        return None
    return statistics.fmean(rois) / sd


def max_drawdown_cents(balances: list[int]) -> int:
    peak = None
    worst = 0
    for balance in balances:
        if peak is None or balance > peak:
            peak = balance
        drop = peak - balance
        if drop > worst:
            worst = drop
    return worst


def calibration_bins(trades: list[Trade], *, n_bins: int = 10) -> list[CalibrationBin]:
    if n_bins <= 0:
        raise ValueError(f"n_bins must be > 0, got {n_bins}")
    if not trades:
        return []
    width = 1.0 / n_bins
    buckets: list[list[Trade]] = [[] for _ in range(n_bins)]
    for t in trades:
        idx = int(t.prob_yes / width)
        if idx >= n_bins:
            idx = n_bins - 1
        if idx < 0:
            idx = 0
        buckets[idx].append(t)
    bins: list[CalibrationBin] = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        bins.append(
            CalibrationBin(
                lower=idx * width,
                upper=(idx + 1) * width,
                predicted_mean=statistics.fmean(b.prob_yes for b in bucket),
                observed_freq=statistics.fmean(b.outcome_yes for b in bucket),
                count=len(bucket),
            )
        )
    return bins


def compute_metrics(
    trades: list[Trade],
    *,
    balances: list[int],
    tau: float = 0.5,
    n_bins: int = 10,
) -> EvalMetrics:
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    if n_bins <= 0:
        raise ValueError(f"n_bins must be > 0, got {n_bins}")
    edge = posterior_edge(_rois(trades), tau=tau)
    return EvalMetrics(
        n_trades=n_trades(trades),
        n_wins=n_wins(trades),
        hit_rate=hit_rate(trades),
        brier=brier(trades),
        log_loss=log_loss(trades),
        pnl_cents=pnl_cents(trades),
        sharpe_proxy=sharpe_proxy(trades),
        max_drawdown_cents=max_drawdown_cents(balances),
        posterior_edge_mean=edge.mean,
        posterior_edge_ci_low=edge.ci_low,
        posterior_edge_ci_high=edge.ci_high,
        calibration_bins=calibration_bins(trades, n_bins=n_bins),
    )
