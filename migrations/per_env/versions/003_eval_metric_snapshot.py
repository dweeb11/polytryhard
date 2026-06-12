"""eval_metric_snapshot table

Revision ID: 003_eval_metric_snapshot
Revises: 002_strategy_ledger
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_eval_metric_snapshot"
down_revision: str | None = "002_strategy_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

eval_window_enum = sa.Enum("7d", "30d", "all", name="eval_window", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "eval_metric_snapshot",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "strategy_name",
            sa.String(length=128),
            sa.ForeignKey("strategy_instance.name"),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window", eval_window_enum, nullable=False),
        sa.Column("n_trades", sa.Integer(), nullable=False),
        sa.Column("n_wins", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("pnl_cents", sa.BigInteger(), nullable=False),
        sa.Column("sharpe_proxy", sa.Float(), nullable=True),
        sa.Column("max_drawdown_cents", sa.BigInteger(), nullable=False),
        sa.Column("posterior_edge_mean", sa.Float(), nullable=False),
        sa.Column("posterior_edge_ci_low", sa.Float(), nullable=False),
        sa.Column("posterior_edge_ci_high", sa.Float(), nullable=False),
        sa.Column("calibration_bins_jsonb", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_eval_metric_snapshot_strategy_window_computed",
        "eval_metric_snapshot",
        ["strategy_name", "window", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eval_metric_snapshot_strategy_window_computed",
        table_name="eval_metric_snapshot",
    )
    op.drop_table("eval_metric_snapshot")
