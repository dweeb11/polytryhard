from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.domain.enums import StrategyState
from core.domain.serde import to_camel

DEFAULT_CONFIDENCE_FLOOR = 0.55
DEFAULT_DISAGREEMENT_THRESHOLD = 2.0
DEFAULT_SPREAD_MARGIN_MULTIPLIER = 1.5
DEFAULT_WIDE_SPREAD_THRESHOLD = 0.08
DEFAULT_EXPOSURE_CAP_PCT = 0.5
DEFAULT_CORRELATION_CAP_PCT = 0.5
DEFAULT_MIN_EDGE = 0.05
DEFAULT_MAX_DISAGREEMENT_F = 3.0

WEATHER_ENSEMBLE_DISAGREEMENT = "weather_ensemble_disagreement"
WEATHER_STALE_QUOTE = "weather_stale_quote"


class StrategyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    min_bankroll_cents: int
    min_tradeable_bankroll_cents: int
    max_drawdown_pct_from_hwm: float
    auto_resume_on_deposit: bool
    max_input_age_seconds: int
    confidence_floor: float | None = None
    disagreement_threshold: float | None = None
    spread_margin_multiplier: float | None = None
    wide_spread_threshold: float | None = None
    exposure_cap_pct: float | None = None
    correlation_cap_pct: float | None = None
    min_edge: float | None = None
    max_disagreement_f: float | None = None


class StrategyInstance(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    name: str
    enabled: bool
    state: StrategyState
    bankroll_cents: int
    bankroll_hwm_cents: int
    initial_deposit_cents: int
    kelly_fraction: float
    config: StrategyConfig
    last_state_change_at: str
    today_pnl_cents: int = Field(default=0)


def effective_strategy_config(
    raw: Mapping[str, Any],
    *,
    strategy_name: str,
) -> StrategyConfig:
    """Resolve stored config_jsonb to the values runtime code actually applies."""
    config = StrategyConfig.model_validate(raw)
    updates: dict[str, float] = {}

    if config.confidence_floor is None:
        updates["confidence_floor"] = DEFAULT_CONFIDENCE_FLOOR
    if config.exposure_cap_pct is None:
        updates["exposure_cap_pct"] = DEFAULT_EXPOSURE_CAP_PCT
    if config.correlation_cap_pct is None:
        updates["correlation_cap_pct"] = DEFAULT_CORRELATION_CAP_PCT

    if strategy_name in (WEATHER_ENSEMBLE_DISAGREEMENT, WEATHER_STALE_QUOTE):
        if config.min_edge is None:
            updates["min_edge"] = DEFAULT_MIN_EDGE

    if strategy_name == WEATHER_ENSEMBLE_DISAGREEMENT:
        if config.disagreement_threshold is None:
            updates["disagreement_threshold"] = DEFAULT_DISAGREEMENT_THRESHOLD
        if config.spread_margin_multiplier is None:
            updates["spread_margin_multiplier"] = DEFAULT_SPREAD_MARGIN_MULTIPLIER
        if config.max_disagreement_f is None:
            updates["max_disagreement_f"] = DEFAULT_MAX_DISAGREEMENT_F
    elif strategy_name == WEATHER_STALE_QUOTE:
        if config.wide_spread_threshold is None:
            updates["wide_spread_threshold"] = DEFAULT_WIDE_SPREAD_THRESHOLD

    if not updates:
        return config
    return config.model_copy(update=updates)
