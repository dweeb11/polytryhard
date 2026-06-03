from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.enums import EvalWindow
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.utils.time import utc_now

EVAL_TEST_NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

DEFAULT_STRATEGY_CONFIG: dict[str, object] = {
    "min_bankroll_cents": 10_000,
    "min_tradeable_bankroll_cents": 5_000,
    "max_drawdown_pct_from_hwm": 30,
    "auto_resume_on_deposit": True,
    "max_input_age_seconds": 900,
}


def eval_metric_snapshot_row(
    strategy: str,
    window: EvalWindow,
    computed_at: datetime,
    **kw: object,
) -> EvalMetricSnapshotRow:
    base: dict[str, object] = {
        "n_trades": 5,
        "n_wins": 3,
        "hit_rate": 0.6,
        "brier_score": 0.2,
        "log_loss": 0.6,
        "pnl_cents": 100,
        "sharpe_proxy": 0.3,
        "max_drawdown_cents": -50,
        "posterior_edge_mean": 0.04,
        "posterior_edge_ci_low": -0.01,
        "posterior_edge_ci_high": 0.1,
        "calibration_bins_jsonb": [],
    }
    base.update(kw)
    return EvalMetricSnapshotRow(
        id=f"{strategy}-{window.value}-{computed_at.isoformat()}",
        strategy_name=strategy,
        computed_at=computed_at,
        window=window,
        **base,
    )


def create_funded_strategy(
    session: Session,
    name: str,
    *,
    config_jsonb: dict[str, object] | None = None,
) -> None:
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
            config_jsonb={**DEFAULT_STRATEGY_CONFIG, **(config_jsonb or {})},
            consecutive_min_position_rejections=0,
            last_state_change_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "test setup", AuditActor.USER, "rq")
    session.commit()


def seed_contract_resolution(
    shared: Session,
    ticker: str,
    resolution: ContractResolution,
    *,
    resolved_at: datetime | None = None,
) -> None:
    shared.add(
        ReferenceMarketRow(
            ticker=ticker,
            series="S",
            title="t",
            settlement_source=None,
            settlement_ref=None,
            open_time=None,
            close_time=None,
            settlement_time=None,
            status="settled",
            raw_jsonb={},
        )
    )
    shared.flush()
    shared.add(
        ContractResolutionRow(
            ticker=ticker,
            resolved_at=resolved_at or EVAL_TEST_NOW,
            resolution=resolution,
            settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
            source_evidence_jsonb={},
        )
    )
    shared.commit()
