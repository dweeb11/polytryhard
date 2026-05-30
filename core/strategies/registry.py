from core.contracts.strategy import Strategy
from core.settings import Settings
from core.strategies.weather_ensemble_disagreement.strategy import (
    WeatherEnsembleDisagreementStrategy,
)
from core.strategies.weather_stale_quote.strategy import WeatherStaleQuoteStrategy

_ALL_STRATEGIES: tuple[Strategy, ...] = (
    WeatherEnsembleDisagreementStrategy(),
    WeatherStaleQuoteStrategy(),
)


def registered_strategies() -> tuple[Strategy, ...]:
    return _ALL_STRATEGIES


def enabled_strategies(settings: Settings) -> list[Strategy]:
    return [strategy for strategy in _ALL_STRATEGIES if strategy.is_enabled(settings)]
