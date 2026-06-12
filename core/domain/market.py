from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from core.domain.enums import PositionSide


@dataclass(frozen=True)
class MarketState:
    ticker: str
    series: str
    bid_yes: Decimal | None
    ask_yes: Decimal | None
    mid_yes: Decimal | None
    as_of: datetime
    location_id: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "series": self.series,
            "bidYes": float(self.bid_yes) if self.bid_yes is not None else None,
            "askYes": float(self.ask_yes) if self.ask_yes is not None else None,
            "midYes": float(self.mid_yes) if self.mid_yes is not None else None,
            "asOf": self.as_of.isoformat(),
            "locationId": self.location_id,
        }


@dataclass(frozen=True)
class SignalDraft:
    ticker: str
    prob_yes: Decimal
    confidence: Decimal
    side: PositionSide
