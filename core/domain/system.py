from pydantic import BaseModel, ConfigDict

from core.domain.enums import SystemState
from core.domain.serde import to_camel


class SystemEnvState(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)

    state: SystemState
    kill_switch_reason: str | None
    kill_switch_tripped_at: str | None
