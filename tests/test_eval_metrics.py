import math

import pytest

from core.eval.metrics import (
    EvalMetrics,
    Trade,
    brier,
    compute_metrics,
    hit_rate,
    log_loss,
    max_drawdown_cents,
    n_trades,
    n_wins,
    pnl_cents,
    sharpe_proxy,
)


def _trade(prob: float, outcome: int, pnl: int, cost: int = 100) -> Trade:
    return Trade(
        prob_yes=prob, outcome_yes=outcome, realized_pnl_cents=pnl, cost_basis_cents=cost
    )


def test_counts_basic() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    assert n_trades(trades) == 3
    assert n_wins(trades) == 2
    assert hit_rate(trades) == 2 / 3


def test_counts_empty() -> None:
    assert n_trades([]) == 0
    assert n_wins([]) == 0
    assert hit_rate([]) is None


def test_zero_pnl_is_not_a_win() -> None:
    assert n_wins([_trade(0.5, 1, 0)]) == 0


def test_trade_rejects_non_positive_cost_basis() -> None:
    with pytest.raises(ValueError, match="cost_basis_cents must be > 0"):
        _trade(0.5, 1, 10, cost=0)


def test_compute_metrics_rejects_non_positive_tau() -> None:
    with pytest.raises(ValueError, match="tau must be > 0"):
        compute_metrics([], balances=[10000], tau=0)


def test_compute_metrics_rejects_non_positive_n_bins() -> None:
    with pytest.raises(ValueError, match="n_bins must be > 0"):
        compute_metrics([], balances=[10000], n_bins=0)


def test_brier_hand_computed() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    assert brier(trades) == pytest.approx((0.16 + 0.16 + 0.09) / 3)


def test_brier_empty_is_none() -> None:
    assert brier([]) is None


def test_log_loss_hand_computed() -> None:
    assert log_loss([_trade(0.6, 1, 60)]) == pytest.approx(-math.log(0.6))


def test_log_loss_clamps_confident_wrong() -> None:
    value = log_loss([_trade(1.0, 0, -100)])
    assert value is not None and math.isfinite(value)


def test_log_loss_empty_is_none() -> None:
    assert log_loss([]) is None


def test_pnl_sum() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40)]
    assert pnl_cents(trades) == 20


def test_pnl_empty_is_zero() -> None:
    assert pnl_cents([]) == 0


def test_sharpe_proxy_hand_computed() -> None:
    import statistics

    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40)]
    expected = 0.1 / statistics.stdev([0.6, -0.4])
    assert sharpe_proxy(trades) == pytest.approx(expected)


def test_sharpe_proxy_single_trade_is_none() -> None:
    assert sharpe_proxy([_trade(0.6, 1, 60)]) is None


def test_sharpe_proxy_zero_variance_is_none() -> None:
    assert sharpe_proxy([_trade(0.6, 1, 50), _trade(0.6, 1, 50)]) is None


def test_max_drawdown_peak_to_trough() -> None:
    assert max_drawdown_cents([10000, 12000, 9000, 11000]) == 3000


def test_max_drawdown_monotonic_up_is_zero() -> None:
    assert max_drawdown_cents([10000, 10500, 11000]) == 0


def test_max_drawdown_empty_is_zero() -> None:
    assert max_drawdown_cents([]) == 0


def test_compute_metrics_empty() -> None:
    m = compute_metrics([], balances=[10000], tau=0.5)
    assert isinstance(m, EvalMetrics)
    assert m.n_trades == 0
    assert m.n_wins == 0
    assert m.hit_rate is None
    assert m.brier is None
    assert m.log_loss is None
    assert m.pnl_cents == 0
    assert m.sharpe_proxy is None
    assert m.max_drawdown_cents == 0
    assert m.posterior_edge_mean == 0.0
    assert m.posterior_edge_ci_low == pytest.approx(-1.96 * 0.5)
    assert m.calibration_bins == []


def test_compute_metrics_populated() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    m = compute_metrics(trades, balances=[10000, 10060, 10020, 10050], tau=0.5)
    assert m.n_trades == 3
    assert m.n_wins == 2
    assert m.hit_rate == pytest.approx(2 / 3)
    assert m.brier == pytest.approx((0.16 + 0.16 + 0.09) / 3)
    assert m.pnl_cents == 50
    assert m.max_drawdown_cents == 40
    assert len(m.calibration_bins) == 3
