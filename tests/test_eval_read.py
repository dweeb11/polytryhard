from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow
from core.domain.eval import CalibrationBin, EvalRosterEntry, EvalSnapshot, StrategyEval
from core.eval.read import latest_snapshots, roster_summary
from core.ledger.seed import seed_strategies_if_needed


def _snap(strategy: str, window: EvalWindow, computed_at: datetime, **kw) -> EvalMetricSnapshotRow:
    base = dict(
        n_trades=5, n_wins=3, hit_rate=0.6, brier_score=0.2, log_loss=0.6,
        pnl_cents=100, sharpe_proxy=0.3, max_drawdown_cents=-50,
        posterior_edge_mean=0.04, posterior_edge_ci_low=-0.01, posterior_edge_ci_high=0.1,
        calibration_bins_jsonb=[],
    )
    base.update(kw)
    return EvalMetricSnapshotRow(
        id=f"{strategy}-{window.value}-{computed_at.isoformat()}",
        strategy_name=strategy, computed_at=computed_at, window=window, **base,
    )


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


def test_latest_snapshots_returns_one_row_per_window_latest_wins(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-read")
    name = "weather_ensemble_disagreement"
    old = datetime(2026, 5, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    session.add_all([
        _snap(name, EvalWindow.D7, old, n_trades=1),
        _snap(name, EvalWindow.D7, new, n_trades=9),
        _snap(name, EvalWindow.ALL, new, n_trades=20),
    ])
    session.commit()
    snaps = latest_snapshots(session, name)
    by_window = {s.window: s for s in snaps}
    assert by_window["7d"].n_trades == 9      # latest D7 wins
    assert by_window["all"].n_trades == 20
    assert "30d" not in by_window             # no 30d row written
    session.close()


def test_roster_summary_includes_strategies_without_snapshots(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-roster")
    name = "weather_ensemble_disagreement"
    session.add(
        _snap(name, EvalWindow.ALL, datetime(2026, 6, 1, tzinfo=UTC), n_trades=12, hit_rate=0.5)
    )
    session.commit()
    roster = {e.strategy_name: e for e in roster_summary(session)}
    assert roster[name].n_trades == 12
    assert roster[name].hit_rate == 0.5
    # a seeded strategy with no snapshot still appears, with null metrics
    other = "weather_stale_quote"
    assert other in roster
    assert roster[other].n_trades == 0
    assert roster[other].hit_rate is None
    session.close()
