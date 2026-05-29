from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from core.db.enums import (
    CashEventKind,
    PositionSide,
    PositionStatus,
    SignalOutcome,
    StrategyState,
    SystemState,
)


def str_enum_column(enum_type: type) -> Enum:
    return Enum(
        enum_type,
        native_enum=False,
        values_callable=lambda obj: [member.value for member in obj],
    )


class Base(DeclarativeBase):
    pass


class AuditEventRow(Base):
    __tablename__ = "audit_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(128))
    target_type: Mapped[str] = mapped_column(String(64))
    target_id: Mapped[str] = mapped_column(String(256))
    before_state: Mapped[dict[str, object]] = mapped_column(JSON)
    after_state: Mapped[dict[str, object]] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str] = mapped_column(String(64))


class StrategyInstanceRow(Base):
    __tablename__ = "strategy_instance"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    state: Mapped[StrategyState] = mapped_column(str_enum_column(StrategyState))
    bankroll_cents: Mapped[int] = mapped_column(BigInteger)
    initial_deposit_cents: Mapped[int] = mapped_column(BigInteger)
    bankroll_hwm_cents: Mapped[int] = mapped_column(BigInteger)
    hwm_reset_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kelly_fraction: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    config_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)
    consecutive_min_position_rejections: Mapped[int] = mapped_column(Integer, default=0)
    last_state_change_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    cash_events: Mapped[list["CashEventRow"]] = relationship(back_populates="strategy")


class CashEventRow(Base):
    __tablename__ = "cash_event"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(
        String(128), ForeignKey("strategy_instance.name"), index=True
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[CashEventKind] = mapped_column(str_enum_column(CashEventKind))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text)
    ref_position_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("paper_position.id"), nullable=True
    )

    strategy: Mapped[StrategyInstanceRow] = relationship(back_populates="cash_events")


class PaperPositionRow(Base):
    __tablename__ = "paper_position"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(128), ForeignKey("strategy_instance.name"))
    ticker: Mapped[str] = mapped_column(String(128))
    side: Mapped[PositionSide] = mapped_column(str_enum_column(PositionSide))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    open_avg_price: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    qty: Mapped[int] = mapped_column(Integer)
    cost_basis_cents: Mapped[int] = mapped_column(BigInteger)
    realized_pnl_cents: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    unrealized_pnl_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    status: Mapped[PositionStatus] = mapped_column(str_enum_column(PositionStatus))


class PaperFillRow(Base):
    __tablename__ = "paper_fill"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    position_id: Mapped[str] = mapped_column(String(36), ForeignKey("paper_position.id"))
    signal_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("signal.id"), nullable=True
    )
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    side: Mapped[PositionSide] = mapped_column(str_enum_column(PositionSide))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    fees_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    simulator_assumptions_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)


class SignalRow(Base):
    __tablename__ = "signal"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(String(128), ForeignKey("strategy_instance.name"))
    ticker: Mapped[str] = mapped_column(String(128))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prob_yes: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    confidence: Mapped[Decimal] = mapped_column(Numeric(8, 6))
    features_snapshot_jsonb: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    market_state_jsonb: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    outcome: Mapped[SignalOutcome] = mapped_column(str_enum_column(SignalOutcome))
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SystemStateRow(Base):
    __tablename__ = "system_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[SystemState] = mapped_column(str_enum_column(SystemState))
    kill_switch_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    kill_switch_tripped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
