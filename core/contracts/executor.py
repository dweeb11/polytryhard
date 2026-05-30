from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from core.domain.trading import Order


@dataclass(frozen=True)
class Fill:
    position_id: str
    fill_id: str
    price: Decimal
    qty: int
    fees_cents: int


@dataclass
class ExecutorContext:
    request_id: str
    session: Session
    strategy_name: str
    signal_id: str | None = None
    fees_cents: int = 0


class Executor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def place(self, order: Order, ctx: ExecutorContext) -> Fill:
        raise NotImplementedError
