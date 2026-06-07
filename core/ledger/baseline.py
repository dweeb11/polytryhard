from core.db.models import StrategyInstanceRow

DEFAULT_MIN_TRADEABLE_BANKROLL_CENTS = 5_000


def min_tradeable_for_starting_baseline(amount_cents: int) -> int:
    return min(amount_cents, DEFAULT_MIN_TRADEABLE_BANKROLL_CENTS)


def config_with_starting_baseline(
    config: dict[str, object],
    amount_cents: int,
) -> dict[str, object]:
    updated = dict(config)
    updated["min_bankroll_cents"] = amount_cents
    updated["min_tradeable_bankroll_cents"] = min_tradeable_for_starting_baseline(amount_cents)
    return updated


def apply_starting_baseline(strategy: StrategyInstanceRow, amount_cents: int) -> None:
    strategy.initial_deposit_cents = amount_cents
    strategy.bankroll_hwm_cents = amount_cents
    strategy.hwm_reset_at = None
    strategy.config_jsonb = config_with_starting_baseline(strategy.config_jsonb, amount_cents)
