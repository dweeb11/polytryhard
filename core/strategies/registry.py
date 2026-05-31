from core.contracts.strategy import Strategy
from core.settings import Settings

# Weather strategies register in M4.5; keep the registry empty until then.
_ALL_STRATEGIES: tuple[Strategy, ...] = ()


def registered_strategies() -> tuple[Strategy, ...]:
    return _ALL_STRATEGIES


def enabled_strategies(settings: Settings) -> list[Strategy]:
    return [strategy for strategy in _ALL_STRATEGIES if strategy.is_enabled(settings)]
