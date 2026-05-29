"""strategy ledger tables

Revision ID: 002_strategy_ledger
Revises: 001_initial_per_env
Create Date: 2026-05-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "002_strategy_ledger"
down_revision: str | None = "001_initial_per_env"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

strategy_state_enum = sa.Enum(
    "seeded",
    "active",
    "low_bankroll_paused",
    "drawdown_paused",
    "operator_paused",
    "decommissioned",
    name="strategy_state",
    native_enum=False,
)
cash_event_kind_enum = sa.Enum(
    "deposit",
    "withdraw",
    "realized_pnl",
    "fee",
    "transfer_in",
    "transfer_out",
    name="cash_event_kind",
    native_enum=False,
)
position_side_enum = sa.Enum("yes", "no", name="position_side", native_enum=False)
position_status_enum = sa.Enum(
    "open",
    "closed",
    "resolved",
    name="position_status",
    native_enum=False,
)
signal_outcome_enum = sa.Enum(
    "order_placed",
    "rejected_kelly_zero",
    "rejected_exposure_cap",
    "rejected_correlation_cap",
    "rejected_below_threshold",
    "rejected_below_min_position",
    "rejected_market_closed",
    "rejected_stale_inputs",
    "rejected_system_paused",
    name="signal_outcome",
    native_enum=False,
)
system_state_enum = sa.Enum("active", "paused", name="system_state", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "strategy_instance",
        sa.Column("name", sa.String(length=128), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("state", strategy_state_enum, nullable=False, server_default="seeded"),
        sa.Column("bankroll_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("initial_deposit_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("bankroll_hwm_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("hwm_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "kelly_fraction",
            sa.Numeric(precision=8, scale=6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("config_jsonb", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "consecutive_min_position_rejections",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_state_change_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "paper_position",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "strategy_name",
            sa.String(length=128),
            sa.ForeignKey("strategy_instance.name"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=128), nullable=False),
        sa.Column("side", position_side_enum, nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("open_avg_price", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("cost_basis_cents", sa.BigInteger(), nullable=False),
        sa.Column("realized_pnl_cents", sa.BigInteger(), nullable=True),
        sa.Column("unrealized_pnl_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("status", position_status_enum, nullable=False),
    )
    op.create_index(
        "ix_paper_position_strategy_name",
        "paper_position",
        ["strategy_name"],
    )
    op.create_table(
        "cash_event",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "strategy_name",
            sa.String(length=128),
            sa.ForeignKey("strategy_instance.name"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", cash_event_kind_enum, nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "ref_position_id",
            sa.String(length=36),
            sa.ForeignKey("paper_position.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_cash_event_strategy_occurred",
        "cash_event",
        ["strategy_name", sa.text("occurred_at DESC")],
    )
    op.create_table(
        "signal",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "strategy_name",
            sa.String(length=128),
            sa.ForeignKey("strategy_instance.name"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(length=128), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("prob_yes", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=8, scale=6), nullable=False),
        sa.Column("features_snapshot_jsonb", sa.JSON(), nullable=True),
        sa.Column("market_state_jsonb", sa.JSON(), nullable=True),
        sa.Column("outcome", signal_outcome_enum, nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_signal_strategy_evaluated",
        "signal",
        ["strategy_name", sa.text("evaluated_at DESC")],
    )
    op.create_table(
        "paper_fill",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "position_id",
            sa.String(length=36),
            sa.ForeignKey("paper_position.id"),
            nullable=False,
        ),
        sa.Column(
            "signal_id",
            sa.String(length=36),
            sa.ForeignKey("signal.id"),
            nullable=True,
        ),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("side", position_side_enum, nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("fees_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "simulator_assumptions_jsonb",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.create_index(
        "ix_paper_fill_position_id",
        "paper_fill",
        ["position_id"],
    )
    op.create_table(
        "system_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("state", system_state_enum, nullable=False, server_default="active"),
        sa.Column("kill_switch_reason", sa.Text(), nullable=True),
        sa.Column("kill_switch_tripped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO system_state "
            "(id, state, kill_switch_reason, kill_switch_tripped_at, updated_at) "
            "VALUES (1, 'active', NULL, NULL, CURRENT_TIMESTAMP)"
        )
    )


def downgrade() -> None:
    op.drop_table("system_state")
    op.drop_index("ix_paper_fill_position_id", table_name="paper_fill")
    op.drop_table("paper_fill")
    op.drop_index("ix_signal_strategy_evaluated", table_name="signal")
    op.drop_table("signal")
    op.drop_index("ix_cash_event_strategy_occurred", table_name="cash_event")
    op.drop_table("cash_event")
    op.drop_index("ix_paper_position_strategy_name", table_name="paper_position")
    op.drop_table("paper_position")
    op.drop_table("strategy_instance")
