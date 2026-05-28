from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.models import StrategyInstanceRow
from core.domain.enums import AuditActor, StrategyState
from core.ledger import writer
from core.utils.time import utc_now

SEED_STRATEGIES: tuple[tuple[str, dict[str, object]], ...] = (
    (
        "weather_ensemble_disagreement",
        {
            "min_bankroll_cents": 10_000,
            "min_tradeable_bankroll_cents": 5_000,
            "max_drawdown_pct_from_hwm": 30,
            "auto_resume_on_deposit": True,
            "max_input_age_seconds": 900,
        },
    ),
    (
        "weather_stale_quote",
        {
            "min_bankroll_cents": 10_000,
            "min_tradeable_bankroll_cents": 5_000,
            "max_drawdown_pct_from_hwm": 30,
            "auto_resume_on_deposit": True,
            "max_input_age_seconds": 900,
        },
    ),
)

INITIAL_DEPOSIT_CENTS = 10_000


def seed_strategies_if_needed(session: Session, *, request_id: str) -> None:
    for name, config in SEED_STRATEGIES:
        if session.get(StrategyInstanceRow, name) is not None:
            continue
        now = utc_now()
        session.add(
            StrategyInstanceRow(
                name=name,
                enabled=True,
                state=StrategyState.SEEDED.value,
                bankroll_cents=0,
                initial_deposit_cents=INITIAL_DEPOSIT_CENTS,
                bankroll_hwm_cents=0,
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
        row = session.get(StrategyInstanceRow, name)
        assert row is not None
        row.state = StrategyState.ACTIVE.value
    session.commit()
