from __future__ import annotations

from core.contracts.executor import Executor, ExecutorContext, Fill
from core.domain.trading import Order
from core.ledger import writer

# M4.7: fill at order limit_price (risk-sized). Snapshot bid/ask fills land in M4.8.
_PAPER_FILL_ASSUMPTIONS: dict[str, object] = {
    "fillModel": "quoted_limit",
    "priceSource": "order.limit_price",
}


class PaperExecutor(Executor):
    @property
    def name(self) -> str:
        return "paper"

    async def place(self, order: Order, ctx: ExecutorContext) -> Fill:
        position, fill = writer.open_paper_position(
            ctx.session,
            strategy_name=ctx.strategy_name,
            order_ticker=order.ticker,
            side=order.side,
            qty=order.qty,
            price=order.limit_price,
            cost_basis_cents=order.cost_basis_cents,
            signal_id=ctx.signal_id,
            fees_cents=ctx.fees_cents,
            simulator_assumptions=_PAPER_FILL_ASSUMPTIONS,
            actor=ctx.actor,
            request_id=ctx.request_id,
        )
        return Fill(
            position_id=position.id,
            fill_id=fill.id,
            price=fill.price,
            qty=fill.qty,
            fees_cents=fill.fees_cents,
        )
