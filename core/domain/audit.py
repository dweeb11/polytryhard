from typing import Any

from pydantic import BaseModel, ConfigDict

from core.domain.enums import AuditActor
from core.domain.serde import to_camel


class AuditEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    id: str
    occurred_at: str
    actor: AuditActor
    action: str
    target_type: str
    target_id: str
    before_state: dict[str, Any]
    after_state: dict[str, Any]
    reason: str
    request_id: str
