import math

import pytest

from core.eval.posterior import PosteriorEdge, posterior_edge


def test_zero_trades_returns_prior() -> None:
    edge = posterior_edge([], tau=0.5)
    assert edge.mean == 0.0
    assert edge.ci_low == pytest.approx(-1.96 * 0.5)
    assert edge.ci_high == pytest.approx(1.96 * 0.5)


def test_single_trade_is_wide_and_shrunk() -> None:
    edge = posterior_edge([0.2], tau=0.5)
    assert edge.mean == pytest.approx(0.1)
    half_width = 1.96 * (0.5 / math.sqrt(2))
    assert edge.ci_low == pytest.approx(0.1 - half_width)
    assert edge.ci_high == pytest.approx(0.1 + half_width)
    assert edge.ci_low < 0 < edge.ci_high


def test_two_trades_hand_computed() -> None:
    rois = [0.1, 0.3]
    tau = 0.5
    s2 = 0.02
    data_precision = 2 / s2
    post_precision = 1 / tau**2 + data_precision
    expected_mean = (0.2 * data_precision) / post_precision
    expected_sd = math.sqrt(1 / post_precision)
    edge = posterior_edge(rois, tau=tau)
    assert edge.mean == pytest.approx(expected_mean)
    assert edge.ci_low == pytest.approx(expected_mean - 1.96 * expected_sd)
    assert edge.ci_high == pytest.approx(expected_mean + 1.96 * expected_sd)


def test_more_trades_tighten_the_interval() -> None:
    few = posterior_edge([0.1, 0.3], tau=0.5)
    many = posterior_edge([0.2] * 50 + [0.1, 0.3] * 25, tau=0.5)
    assert (many.ci_high - many.ci_low) < (few.ci_high - few.ci_low)


def test_identical_rois_stay_finite() -> None:
    edge = posterior_edge([0.05, 0.05, 0.05], tau=0.5)
    assert math.isfinite(edge.mean)
    assert math.isfinite(edge.ci_low) and math.isfinite(edge.ci_high)


def test_is_frozen_dataclass() -> None:
    edge = posterior_edge([0.1, 0.2], tau=0.5)
    assert isinstance(edge, PosteriorEdge)
