from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from core.domain.enums import PositionSide, SignalOutcome


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
