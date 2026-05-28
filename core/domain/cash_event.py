from pydantic import BaseModel, ConfigDict

from core.domain.enums import CashEventKind
from core.domain.serde import to_camel


class CashEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: str
    strategy_name: str
    occurred_at: str
    kind: CashEventKind
    amount_cents: int
    balance_after_cents: int
    reason: str
    ref_position_id: str | None
