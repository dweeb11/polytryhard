"""initial shared database baseline

Revision ID: 001_initial_shared
Revises:
Create Date: 2026-05-26
"""

from collections.abc import Sequence

revision: str = "001_initial_shared"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
