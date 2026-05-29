from pydantic import BaseModel, ConfigDict, Field

from core.domain.serde import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class AmountReasonBody(ApiModel):
    amount_cents: int | None = Field(default=None, gt=0)
    reason: str = ""


class ReasonBody(ApiModel):
    reason: str


class SetKellyBody(ApiModel):
    fraction: float = Field(ge=0, le=1)
    reason: str
