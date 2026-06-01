from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from core.domain.enums import PositionSide, SignalOutcome
from core.domain.serde import to_camel


@dataclass(frozen=True)
class Order:
    ticker: str
    side: PositionSide
    qty: int
    limit_price: Decimal
    cost_basis_cents: int


@dataclass(frozen=True)
class Rejection:
    outcome: SignalOutcome
    reason: str


class SignalRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: str
    strategy_name: str
    ticker: str
    evaluated_at: str
    prob_yes: float
    confidence: float
    features_snapshot: dict[str, object] | None = None
    market_state: dict[str, object] | None = None
    outcome: SignalOutcome
    rejection_reason: str | None = None


class PaperPositionRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: str
    strategy_name: str
    ticker: str
    side: PositionSide
    opened_at: str
    closed_at: str | None = None
    open_avg_price: float
    qty: int
    cost_basis_cents: int
    realized_pnl_cents: int | None = None
    unrealized_pnl_cents: int | None = None
    status: str
