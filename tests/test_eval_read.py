from core.domain.eval import CalibrationBin, EvalRosterEntry, EvalSnapshot, StrategyEval


def test_eval_snapshot_serializes_camel_case() -> None:
    snap = EvalSnapshot(
        window="30d",
        computed_at="2026-06-01T00:00:00+00:00",
        n_trades=10,
        n_wins=6,
        hit_rate=0.6,
        brier_score=0.21,
        log_loss=0.62,
        pnl_cents=1500,
        sharpe_proxy=0.4,
        max_drawdown_cents=-300,
        posterior_edge_mean=0.05,
        posterior_edge_ci_low=-0.02,
        posterior_edge_ci_high=0.12,
        calibration_bins=[
            CalibrationBin(lower=0.0, upper=0.1, predicted_mean=0.05, observed_freq=0.0, count=3)
        ],
    )
    dumped = snap.model_dump(by_alias=True)
    assert dumped["nTrades"] == 10
    assert dumped["posteriorEdgeCiLow"] == -0.02
    assert dumped["calibrationBins"][0]["predictedMean"] == 0.05


def test_roster_entry_allows_null_metrics() -> None:
    entry = EvalRosterEntry(
        strategy_name="weather_ensemble_disagreement",
        n_trades=0,
        hit_rate=None,
        brier_score=None,
        pnl_cents=0,
        posterior_edge_ci_low=0.0,
    )
    assert entry.model_dump(by_alias=True)["hitRate"] is None


def test_strategy_eval_holds_windows() -> None:
    se = StrategyEval(strategy_name="x", windows=[])
    assert se.model_dump(by_alias=True)["windows"] == []
