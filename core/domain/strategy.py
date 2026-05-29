from pydantic import BaseModel, ConfigDict, Field

from core.domain.enums import StrategyState
from core.domain.serde import to_camel


class StrategyConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    min_bankroll_cents: int
    min_tradeable_bankroll_cents: int
    max_drawdown_pct_from_hwm: float
    auto_resume_on_deposit: bool
    max_input_age_seconds: int


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
