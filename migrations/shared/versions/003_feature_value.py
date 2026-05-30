"""feature_value shared table

Revision ID: 003_feature_value
Revises: 002_ingestion_shared
Create Date: 2026-05-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_feature_value"
down_revision: str | None = "002_ingestion_shared"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

feature_subject_kind_enum = sa.Enum(
    "market",
    "location",
    name="feature_subject_kind",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "feature_value",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("provider_version", sa.String(length=16), nullable=False),
        sa.Column("subject_kind", feature_subject_kind_enum, nullable=False),
        sa.Column("subject_id", sa.String(length=128), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value_numeric", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("value_jsonb", sa.JSON(), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "provider_name",
            "provider_version",
            "subject_kind",
            "subject_id",
            "as_of",
            name="uq_feature_value_provider_subject_as_of",
        ),
    )
    op.create_index(
        "ix_feature_value_provider_subject_as_of",
        "feature_value",
        ["provider_name", "subject_kind", "subject_id", sa.text("as_of DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_feature_value_provider_subject_as_of", table_name="feature_value")
    op.drop_table("feature_value")
