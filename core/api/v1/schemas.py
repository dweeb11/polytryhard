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


class SetStartingBankrollBody(ApiModel):
    amount_cents: int = Field(gt=0)
    reason: str


class SourceHealthEntry(ApiModel):
    name: str
    enabled: bool
    status: str | None = None
    last_run_at: str | None = None
    last_success_at: str | None = None
    rows_last_run: int | None = None
    last_error: str | None = None
