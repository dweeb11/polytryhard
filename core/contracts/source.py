from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol

from core.clock import Clock
from core.db.shared_enums import ContractResolution, ForecastSource, SourceRunStatus
from core.settings import Settings


@dataclass(frozen=True)
class ReferenceLocation:
    id: str
    station_code: str
    name: str
    lat: Decimal
    lon: Decimal
    timezone: str
    source: str


@dataclass(frozen=True)
class ReferenceMarketUpsert:
    ticker: str
    series: str
    title: str
    status: str
    settlement_source: str | None = None
    settlement_ref: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    settlement_time: datetime | None = None
    raw_jsonb: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RawMarketSnapshotDraft:
    ticker: str
    as_of: datetime
    bid_yes: Decimal | None
    ask_yes: Decimal | None
    mid_yes: Decimal | None
    bid_size: int | None
    ask_size: int | None
    last_trade_price: Decimal | None
    last_trade_size: int | None
    raw_jsonb: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RawForecastRunDraft:
    source: ForecastSource
    run_time: datetime
    ingested_at: datetime
    location_id: str
    valid_window_start: datetime
    valid_window_end: datetime
    variable: str
    value: Decimal
    ensemble_member: int | None
    raw_jsonb: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ContractResolutionDraft:
    ticker: str
    resolved_at: datetime
    resolution: ContractResolution
    settlement_value: Decimal
    source_evidence_jsonb: dict[str, object] = field(default_factory=dict)


@dataclass
class FetchResult:
    status: SourceRunStatus = SourceRunStatus.OK
    error_text: str | None = None
    market_snapshots: list[RawMarketSnapshotDraft] = field(default_factory=list)
    forecast_runs: list[RawForecastRunDraft] = field(default_factory=list)
    market_upserts: list[ReferenceMarketUpsert] = field(default_factory=list)
    resolutions: list[ContractResolutionDraft] = field(default_factory=list)

    @property
    def rows_written(self) -> int:
        return (
            len(self.market_snapshots)
            + len(self.forecast_runs)
            + len(self.resolutions)
        )


class HttpClient(Protocol):
    async def get(self, url: str, *, headers: dict[str, str] | None = None) -> Any: ...


@dataclass
class SourceContext:
    request_id: str
    settings: Settings
    locations: tuple[ReferenceLocation, ...]
    markets: tuple[ReferenceMarketUpsert, ...]
    http: HttpClient


class IngestionSource(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def schedule_seconds(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def is_enabled(self, settings: Settings) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def fetch(self, clock: Clock, ctx: SourceContext) -> FetchResult:
        raise NotImplementedError
