from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from core.db.shared_enums import FeatureSubjectKind, ForecastSource, SourceRunStatus
from core.db.types import str_enum_column


class SharedBase(DeclarativeBase):
    pass


class ReferenceLocationRow(SharedBase):
    __tablename__ = "reference_location"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    station_code: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(128))
    lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    lon: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(64))


class ReferenceMarketRow(SharedBase):
    __tablename__ = "reference_market"

    ticker: Mapped[str] = mapped_column(String(128), primary_key=True)
    series: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512))
    settlement_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    settlement_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settlement_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    raw_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)


class RawMarketSnapshotRow(SharedBase):
    __tablename__ = "raw_market_snapshot"
    __table_args__ = (
        Index("ix_raw_market_snapshot_ticker_as_of", "ticker", text("as_of DESC")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    ticker: Mapped[str] = mapped_column(String(128), ForeignKey("reference_market.ticker"))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    bid_yes: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    ask_yes: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    mid_yes: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    bid_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ask_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_trade_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    last_trade_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("source_run.id"), nullable=True
    )
    raw_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)


class RawForecastRunRow(SharedBase):
    __tablename__ = "raw_forecast_run"
    __table_args__ = (
        Index(
            "ix_raw_forecast_run_source_loc_var_run",
            "source",
            "location_id",
            "variable",
            text("run_time DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[ForecastSource] = mapped_column(str_enum_column(ForecastSource))
    run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location_id: Mapped[str] = mapped_column(String(64), ForeignKey("reference_location.id"))
    valid_window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    variable: Mapped[str] = mapped_column(String(64))
    value: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    ensemble_member: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)


class FeatureValueRow(SharedBase):
    __tablename__ = "feature_value"
    __table_args__ = (
        Index(
            "ix_feature_value_provider_subject_as_of",
            "provider_name",
            "subject_kind",
            "subject_id",
            text("as_of DESC"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(64))
    provider_version: Mapped[str] = mapped_column(String(16))
    subject_kind: Mapped[FeatureSubjectKind] = mapped_column(str_enum_column(FeatureSubjectKind))
    subject_id: Mapped[str] = mapped_column(String(128))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    value_numeric: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    value_jsonb: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceRunRow(SharedBase):
    __tablename__ = "source_run"
    __table_args__ = (
        Index("ix_source_run_source_started", "source_name", text("started_at DESC")),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[SourceRunStatus] = mapped_column(str_enum_column(SourceRunStatus))
    rows_written: Mapped[int] = mapped_column(BigInteger)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(String(64))
