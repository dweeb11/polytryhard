import pytest

from core.eval.metrics import Trade, calibration_bins


def _t(prob: float, outcome: int) -> Trade:
    return Trade(prob_yes=prob, outcome_yes=outcome, realized_pnl_cents=0, cost_basis_cents=100)


def test_empty_trades_no_bins() -> None:
    assert calibration_bins([]) == []


def test_calibration_bins_rejects_non_positive_n_bins() -> None:
    with pytest.raises(ValueError, match="n_bins must be > 0"):
        calibration_bins([_t(0.5, 1)], n_bins=0)


def test_bins_group_by_decile_and_omit_empty() -> None:
    trades = [_t(0.62, 1), _t(0.66, 0), _t(0.71, 1)]
    bins = calibration_bins(trades, n_bins=10)
    assert len(bins) == 2
    first = bins[0]
    assert first.lower == pytest.approx(0.6)
    assert first.upper == pytest.approx(0.7)
    assert first.count == 2
    assert first.predicted_mean == pytest.approx((0.62 + 0.66) / 2)
    assert first.observed_freq == pytest.approx(0.5)
    second = bins[1]
    assert second.count == 1
    assert second.observed_freq == pytest.approx(1.0)


def test_prob_one_lands_in_last_bin() -> None:
    bins = calibration_bins([_t(1.0, 1)], n_bins=10)
    assert len(bins) == 1
    assert bins[0].lower == pytest.approx(0.9)
    assert bins[0].upper == pytest.approx(1.0)
    assert bins[0].count == 1


def test_bins_are_sorted_ascending() -> None:
    bins = calibration_bins([_t(0.95, 1), _t(0.05, 0), _t(0.55, 1)], n_bins=10)
    lowers = [b.lower for b in bins]
    assert lowers == sorted(lowers)


def test_as_dict_shape() -> None:
    [bin_] = calibration_bins([_t(0.55, 1)], n_bins=10)
    assert bin_.as_dict() == {
        "lower": pytest.approx(0.5),
        "upper": pytest.approx(0.6),
        "predicted_mean": pytest.approx(0.55),
        "observed_freq": pytest.approx(1.0),
        "count": 1,
    }
