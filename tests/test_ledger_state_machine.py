from core.domain import state_machine
from core.domain.enums import StrategyState


def test_can_activate_only_from_seeded() -> None:
    assert state_machine.can_activate(StrategyState.SEEDED)
    assert not state_machine.can_activate(StrategyState.ACTIVE)


def test_can_pause_only_from_active() -> None:
    assert state_machine.can_pause(StrategyState.ACTIVE)
    assert not state_machine.can_pause(StrategyState.OPERATOR_PAUSED)


def test_can_resume_from_paused_states() -> None:
    for state in (
        StrategyState.LOW_BANKROLL_PAUSED,
        StrategyState.DRAWDOWN_PAUSED,
        StrategyState.OPERATOR_PAUSED,
    ):
        assert state_machine.can_resume(state)
    assert not state_machine.can_resume(StrategyState.ACTIVE)


def test_should_auto_resume_on_deposit() -> None:
    assert state_machine.should_auto_resume_on_deposit(
        current_state=StrategyState.LOW_BANKROLL_PAUSED,
        auto_resume_on_deposit=True,
        new_bankroll_cents=15_000,
        min_bankroll_cents=10_000,
    )
    assert not state_machine.should_auto_resume_on_deposit(
        current_state=StrategyState.LOW_BANKROLL_PAUSED,
        auto_resume_on_deposit=False,
        new_bankroll_cents=15_000,
        min_bankroll_cents=10_000,
    )
