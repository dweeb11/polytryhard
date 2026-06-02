from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.utils.time import utc_now


def _seed_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name,
            enabled=True,
            state=DbStrategyState.SEEDED,
            bankroll_cents=0,
            initial_deposit_cents=0,
            bankroll_hwm_cents=0,
            hwm_reset_at=None,
            kelly_fraction=0.25,
            config_jsonb={},
            consecutive_min_position_rejections=0,
            last_state_change_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()


def test_eval_metric_snapshot_round_trip(per_env_sqlite_urls: tuple[str, str]) -> None:
    _, per_env_url = per_env_sqlite_urls
    engine = create_engine(per_env_url)
    with Session(engine) as session:
        _seed_strategy(session, "strat_a")
        session.add(
            EvalMetricSnapshotRow(
                id="snap-1",
                strategy_name="strat_a",
                computed_at=datetime(2026, 6, 2, tzinfo=UTC),
                window=EvalWindow.D7,
                n_trades=3,
                n_wins=2,
                hit_rate=2 / 3,
                brier_score=0.13,
                log_loss=0.5,
                pnl_cents=50,
                sharpe_proxy=0.4,
                max_drawdown_cents=40,
                posterior_edge_mean=0.1,
                posterior_edge_ci_low=-0.2,
                posterior_edge_ci_high=0.4,
                calibration_bins_jsonb=[
                    {
                        "lower": 0.6,
                        "upper": 0.7,
                        "predicted_mean": 0.63,
                        "observed_freq": 0.5,
                        "count": 2,
                    }
                ],
            )
        )
        session.commit()

        row = session.scalar(select(EvalMetricSnapshotRow))
        assert row is not None
        assert row.window == EvalWindow.D7
        assert row.n_trades == 3
        assert row.hit_rate == 2 / 3
        assert row.calibration_bins_jsonb[0]["count"] == 2

        session.add(
            EvalMetricSnapshotRow(
                id="snap-2",
                strategy_name="strat_a",
                computed_at=datetime(2026, 6, 2, tzinfo=UTC),
                window=EvalWindow.ALL,
                n_trades=0,
                n_wins=0,
                hit_rate=None,
                brier_score=None,
                log_loss=None,
                pnl_cents=0,
                sharpe_proxy=None,
                max_drawdown_cents=0,
                posterior_edge_mean=0.0,
                posterior_edge_ci_low=-0.98,
                posterior_edge_ci_high=0.98,
                calibration_bins_jsonb=[],
            )
        )
        session.commit()
        snap2 = session.get(EvalMetricSnapshotRow, "snap-2")
        assert snap2 is not None
        assert snap2.hit_rate is None
