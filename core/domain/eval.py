from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.domain.serde import to_camel


class _ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class CalibrationBin(_ApiModel):
    lower: float
    upper: float
    predicted_mean: float
    observed_freq: float
    count: int


class EvalSnapshot(_ApiModel):
    window: str
    computed_at: str
    n_trades: int
    n_wins: int
    hit_rate: float | None = None
    brier_score: float | None = None
    log_loss: float | None = None
    pnl_cents: int
    sharpe_proxy: float | None = None
    max_drawdown_cents: int
    posterior_edge_mean: float
    posterior_edge_ci_low: float
    posterior_edge_ci_high: float
    calibration_bins: list[CalibrationBin]


class StrategyEval(_ApiModel):
    strategy_name: str
    windows: list[EvalSnapshot]


# Deliberately minimal one-line summary for the roster view; the full
# posterior CI triple lives in EvalSnapshot (the per-strategy detail endpoint).
class EvalRosterEntry(_ApiModel):
    strategy_name: str
    n_trades: int
    hit_rate: float | None = None
    brier_score: float | None = None
    pnl_cents: int
    posterior_edge_ci_low: float
