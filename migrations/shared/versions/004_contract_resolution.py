"""contract_resolution shared table

Revision ID: 004_contract_resolution
Revises: 003_feature_value
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_contract_resolution"
down_revision: str | None = "003_feature_value"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contract_resolution_enum = sa.Enum(
    "yes",
    "no",
    "void",
    name="contract_resolution",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "contract_resolution",
        sa.Column("ticker", sa.String(length=128), primary_key=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", contract_resolution_enum, nullable=False),
        sa.Column("settlement_value", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("source_evidence_jsonb", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["reference_market.ticker"]),
    )


def downgrade() -> None:
    op.drop_table("contract_resolution")
