from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class FeatureStatus(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    STALE = "stale"


@dataclass(frozen=True)
class FeatureValue:
    provider_name: str
    provider_version: str
    subject_kind: str
    subject_id: str
    status: FeatureStatus
    as_of: datetime | None = None
    value_numeric: Decimal | None = None
    value_jsonb: dict[str, object] | None = None
    reason: str | None = None

    @classmethod
    def present(
        cls,
        *,
        provider_name: str,
        provider_version: str,
        subject_kind: str,
        subject_id: str,
        as_of: datetime,
        value_numeric: Decimal | None = None,
        value_jsonb: dict[str, object] | None = None,
    ) -> FeatureValue:
        return cls(
            provider_name=provider_name,
            provider_version=provider_version,
            subject_kind=subject_kind,
            subject_id=subject_id,
            status=FeatureStatus.PRESENT,
            as_of=as_of,
            value_numeric=value_numeric,
            value_jsonb=value_jsonb,
        )

    @classmethod
    def missing(
        cls,
        *,
        provider_name: str,
        provider_version: str,
        subject_kind: str,
        subject_id: str,
        reason: str,
    ) -> FeatureValue:
        return cls(
            provider_name=provider_name,
            provider_version=provider_version,
            subject_kind=subject_kind,
            subject_id=subject_id,
            status=FeatureStatus.MISSING,
            reason=reason,
        )

    @classmethod
    def stale(
        cls,
        *,
        provider_name: str,
        provider_version: str,
        subject_kind: str,
        subject_id: str,
        as_of: datetime,
        value_numeric: Decimal | None = None,
        value_jsonb: dict[str, object] | None = None,
        reason: str = "stale",
    ) -> FeatureValue:
        return cls(
            provider_name=provider_name,
            provider_version=provider_version,
            subject_kind=subject_kind,
            subject_id=subject_id,
            status=FeatureStatus.STALE,
            as_of=as_of,
            value_numeric=value_numeric,
            value_jsonb=value_jsonb,
            reason=reason,
        )

    def to_snapshot(self) -> dict[str, object]:
        payload: dict[str, object] = {"status": self.status.value}
        if self.as_of is not None:
            payload["asOf"] = self.as_of.isoformat()
        if self.value_numeric is not None:
            payload["valueNumeric"] = float(self.value_numeric)
        if self.value_jsonb is not None:
            payload["valueJsonb"] = self.value_jsonb
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


FeatureSnapshot = dict[str, dict[str, object]]
