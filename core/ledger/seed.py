from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import StrategyInstanceRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.ledger.baseline import config_with_starting_baseline
from core.utils.time import utc_now

INITIAL_DEPOSIT_CENTS = 10_000

SEED_STRATEGY_BASE_CONFIGS: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "weather_ensemble_disagreement",
        {
            "max_drawdown_pct_from_hwm": 30,
            "auto_resume_on_deposit": True,
            "max_input_age_seconds": 900,
            "disagreementThreshold": 2.0,
            "spreadMarginMultiplier": 1.5,
            "confidenceFloor": 0.55,
        },
    ),
    (
        "weather_stale_quote",
        {
            "max_drawdown_pct_from_hwm": 30,
            "auto_resume_on_deposit": True,
            "max_input_age_seconds": 900,
            "wideSpreadThreshold": 0.08,
            "confidenceFloor": 0.55,
        },
    ),
)


def seed_strategies_if_needed(session: Session, *, request_id: str) -> None:
    for name, base_config in SEED_STRATEGY_BASE_CONFIGS:
        if session.get(StrategyInstanceRow, name) is not None:
            continue
        config = config_with_starting_baseline(base_config, INITIAL_DEPOSIT_CENTS)
        now = utc_now()
        session.add(
            StrategyInstanceRow(
                name=name,
                enabled=True,
                state=DbStrategyState.SEEDED,
                bankroll_cents=0,
                initial_deposit_cents=INITIAL_DEPOSIT_CENTS,
                bankroll_hwm_cents=INITIAL_DEPOSIT_CENTS,
                hwm_reset_at=None,
                kelly_fraction=(
                    Decimal("0.25")
                    if name == "weather_ensemble_disagreement"
                    else Decimal("0.2")
                ),
                config_jsonb=config,
                consecutive_min_position_rejections=0,
                last_state_change_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        session.flush()
        writer.deposit(
            session,
            name,
            INITIAL_DEPOSIT_CENTS,
            "initial seed",
            AuditActor.SYSTEM,
            request_id,
        )
        writer.bootstrap_activate_strategy(
            session,
            name,
            "initial seed activation",
            AuditActor.SYSTEM,
            request_id,
        )
    session.commit()
