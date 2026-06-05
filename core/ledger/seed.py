from collections.abc import Mapping
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import StrategyInstanceRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.utils.time import utc_now

DEFAULT_INITIAL_BANKROLL_CENTS = 10_000
DEFAULT_MIN_TRADEABLE_BANKROLL_CENTS = 5_000

SEED_STRATEGY_NAMES: tuple[str, ...] = (
    "weather_ensemble_disagreement",
    "weather_stale_quote",
)

SEED_STRATEGIES: tuple[tuple[str, dict[str, object]], ...] = (
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


def _seed_config(base: dict[str, object], initial_deposit_cents: int) -> dict[str, object]:
    config = dict(base)
    config["min_bankroll_cents"] = initial_deposit_cents
    config["min_tradeable_bankroll_cents"] = min(
        initial_deposit_cents,
        DEFAULT_MIN_TRADEABLE_BANKROLL_CENTS,
    )
    return config


def seed_strategies_if_needed(
    session: Session,
    *,
    request_id: str,
    initial_bankroll_cents: int = DEFAULT_INITIAL_BANKROLL_CENTS,
    strategy_bankroll_overrides: Mapping[str, int] | None = None,
) -> None:
    overrides = strategy_bankroll_overrides or {}
    for name, base_config in SEED_STRATEGIES:
        if session.get(StrategyInstanceRow, name) is not None:
            continue
        initial_deposit_cents = overrides.get(name, initial_bankroll_cents)
        config = _seed_config(base_config, initial_deposit_cents)
        now = utc_now()
        session.add(
            StrategyInstanceRow(
                name=name,
                enabled=True,
                state=DbStrategyState.SEEDED,
                bankroll_cents=0,
                initial_deposit_cents=initial_deposit_cents,
                bankroll_hwm_cents=initial_deposit_cents,
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
        strategy_request_id = f"{request_id}/{name}"
        writer.deposit(
            session,
            name,
            initial_deposit_cents,
            "initial seed",
            AuditActor.SYSTEM,
            strategy_request_id,
        )
        writer.bootstrap_activate_strategy(
            session,
            name,
            "initial seed activation",
            AuditActor.SYSTEM,
            strategy_request_id,
        )
    session.commit()
