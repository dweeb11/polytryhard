from core.domain.enums import StrategyState

PAUSABLE_STATES: frozenset[StrategyState] = frozenset({StrategyState.ACTIVE})
RESUMABLE_STATES: frozenset[StrategyState] = frozenset(
    {
        StrategyState.LOW_BANKROLL_PAUSED,
        StrategyState.DRAWDOWN_PAUSED,
        StrategyState.OPERATOR_PAUSED,
    }
)
AUTO_RESUME_ON_DEPOSIT_STATES: frozenset[StrategyState] = frozenset(
    {StrategyState.LOW_BANKROLL_PAUSED}
)
SIGNAL_EMITTING_STATES: frozenset[StrategyState] = frozenset({StrategyState.ACTIVE})
DEPOSIT_BLOCKED_STATES: frozenset[StrategyState] = frozenset({StrategyState.DECOMMISSIONED})


def can_pause(state: StrategyState) -> bool:
    return state in PAUSABLE_STATES


def can_resume(state: StrategyState) -> bool:
    return state in RESUMABLE_STATES


def resume_target_state() -> StrategyState:
    return StrategyState.ACTIVE


def pause_target_state() -> StrategyState:
    return StrategyState.OPERATOR_PAUSED


def should_auto_resume_on_deposit(
    *,
    current_state: StrategyState,
    auto_resume_on_deposit: bool,
    new_bankroll_cents: int,
    min_bankroll_cents: int,
) -> bool:
    if not auto_resume_on_deposit:
        return False
    if current_state not in AUTO_RESUME_ON_DEPOSIT_STATES:
        return False
    return new_bankroll_cents >= min_bankroll_cents


def can_emit_signals(*, enabled: bool, state: StrategyState, kelly_fraction: float) -> bool:
    if not enabled or state not in SIGNAL_EMITTING_STATES:
        return False
    return kelly_fraction > 0
