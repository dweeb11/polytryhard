"""ingestion shared tables

Revision ID: 002_ingestion_shared
Revises: 001_initial_shared
Create Date: 2026-05-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_ingestion_shared"
down_revision: str | None = "001_initial_shared"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

forecast_source_enum = sa.Enum("gfs", "ecmwf", name="forecast_source", native_enum=False)
source_run_status_enum = sa.Enum(
    "ok", "degraded", "error", name="source_run_status", native_enum=False
)


def upgrade() -> None:
    op.create_table(
        "reference_location",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("station_code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("lat", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("lon", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
    )
    op.create_table(
        "reference_market",
        sa.Column("ticker", sa.String(length=128), primary_key=True),
        sa.Column("series", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("settlement_source", sa.String(length=128), nullable=True),
        sa.Column("settlement_ref", sa.String(length=256), nullable=True),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settlement_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_jsonb", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_table(
        "source_run",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_name", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", source_run_status_enum, nullable=False),
        sa.Column("rows_written", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
    )
    op.create_index(
        "ix_source_run_source_started",
        "source_run",
        ["source_name", sa.text("started_at DESC")],
    )
    op.create_table(
        "raw_market_snapshot",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "ticker",
            sa.String(length=128),
            sa.ForeignKey("reference_market.ticker"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bid_yes", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("ask_yes", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("mid_yes", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("bid_size", sa.Integer(), nullable=True),
        sa.Column("ask_size", sa.Integer(), nullable=True),
        sa.Column("last_trade_price", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("last_trade_size", sa.Integer(), nullable=True),
        sa.Column(
            "source_run_id",
            sa.String(length=36),
            sa.ForeignKey("source_run.id"),
            nullable=True,
        ),
        sa.Column("raw_jsonb", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_raw_market_snapshot_ticker_as_of",
        "raw_market_snapshot",
        ["ticker", sa.text("as_of DESC")],
    )
    op.create_table(
        "raw_forecast_run",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", forecast_source_enum, nullable=False),
        sa.Column("run_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "location_id",
            sa.String(length=64),
            sa.ForeignKey("reference_location.id"),
            nullable=False,
        ),
        sa.Column("valid_window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("variable", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("ensemble_member", sa.Integer(), nullable=True),
        sa.Column("raw_jsonb", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_raw_forecast_run_source_loc_var_run",
        "raw_forecast_run",
        ["source", "location_id", "variable", sa.text("run_time DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_raw_forecast_run_source_loc_var_run", table_name="raw_forecast_run")
    op.drop_table("raw_forecast_run")
    op.drop_index("ix_raw_market_snapshot_ticker_as_of", table_name="raw_market_snapshot")
    op.drop_table("raw_market_snapshot")
    op.drop_index("ix_source_run_source_started", table_name="source_run")
    op.drop_table("source_run")
    op.drop_table("reference_market")
    op.drop_table("reference_location")
