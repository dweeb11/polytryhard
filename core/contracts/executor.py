from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from core.domain.enums import AuditActor
from core.domain.trading import Order


@dataclass(frozen=True)
class Fill:
    position_id: str
    fill_id: str
    price: Decimal
    qty: int
    fees_cents: int


@dataclass(frozen=True)
class ExecutorContext:
    request_id: str
    session: Session
    strategy_name: str
    actor: AuditActor = AuditActor.SCHEDULER
    signal_id: str | None = None
    fees_cents: int = 0


class Executor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def place(self, order: Order, ctx: ExecutorContext) -> Fill:
        """Place an order; implementations perform sync ledger I/O on ctx.session."""
        raise NotImplementedError
