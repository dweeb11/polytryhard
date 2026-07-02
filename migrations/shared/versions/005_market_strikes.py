"""reference_market strike metadata

Revision ID: 005_market_strikes
Revises: 004_contract_resolution
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_market_strikes"
down_revision: str | None = "004_contract_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reference_market", sa.Column("strike_type", sa.String(32), nullable=True))
    op.add_column("reference_market", sa.Column("floor_strike", sa.Numeric(12, 6), nullable=True))
    op.add_column("reference_market", sa.Column("cap_strike", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("reference_market", "cap_strike")
    op.drop_column("reference_market", "floor_strike")
    op.drop_column("reference_market", "strike_type")
