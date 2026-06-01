from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import AuditEventRow, SignalRow
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.domain.market import MarketState, SignalDraft
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.seed import INITIAL_DEPOSIT_CENTS, seed_strategies_if_needed


def _market() -> MarketState:
    return MarketState(
        ticker="KXHIGHNY-25MAY28-T72",
        series="KXHIGHNY",
        bid_yes=Decimal("0.50"),
        ask_yes=Decimal("0.56"),
        mid_yes=Decimal("0.53"),
        as_of=datetime(2025, 5, 28, 12, 0, tzinfo=UTC),
        location_id="nyc",
    )


def _signal_draft() -> SignalDraft:
    return SignalDraft(
        ticker="KXHIGHNY-25MAY28-T72",
        prob_yes=Decimal("0.62"),
        confidence=Decimal("0.71"),
        side=PositionSide.YES,
    )


def test_record_signal_persists_row_and_audit(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"

    row = writer.record_signal(
        session,
        strategy_name=strategy_name,
        signal=_signal_draft(),
        market=_market(),
        features_snapshot={"ensembleMeanTemp": 72.1},
        outcome=SignalOutcome.ORDER_PLACED,
        rejection_reason=None,
        actor=AuditActor.SCHEDULER,
        request_id="sig-req-1",
    )
    session.commit()

    stored = session.get(SignalRow, row.id)
    assert stored is not None
    assert stored.ticker == "KXHIGHNY-25MAY28-T72"
    assert stored.outcome.value == "order_placed"
    audit = session.scalars(
        select(AuditEventRow).where(
            AuditEventRow.target_id == row.id,
            AuditEventRow.action == "record_signal",
            AuditEventRow.request_id == "sig-req-1",
        )
    ).first()
    assert audit is not None
    assert audit.after_state["outcome"] == "order_placed"
    session.close()


def test_record_signal_blocked_when_kill_switch_active(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    writer.apply_kill_switch(session, "incident", AuditActor.USER, "kill-1")
    session.commit()

    with pytest.raises(LedgerError, match="kill switch"):
        writer.record_signal(
            session,
            strategy_name="weather_ensemble_disagreement",
            signal=_signal_draft(),
            market=_market(),
            features_snapshot={},
            outcome=SignalOutcome.REJECTED_SYSTEM_PAUSED,
            rejection_reason="paused",
            actor=AuditActor.SCHEDULER,
            request_id="sig-req-2",
        )
    session.close()


def test_open_paper_position_rejects_insufficient_free_cash(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"

    with pytest.raises(LedgerError, match="free cash"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker="KXHIGHNY-25MAY28-T72",
            side=PositionSide.YES,
            qty=100,
            price=Decimal("0.99"),
            cost_basis_cents=INITIAL_DEPOSIT_CENTS + 1,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-1",
        )
    session.close()


def test_open_paper_position_rejects_when_kill_switch_active(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    writer.apply_kill_switch(session, "incident", AuditActor.USER, "kill-2")
    session.commit()

    with pytest.raises(LedgerError, match="kill switch"):
        writer.open_paper_position(
            session,
            strategy_name="weather_ensemble_disagreement",
            order_ticker="KXHIGHNY-25MAY28-T72",
            side=PositionSide.YES,
            qty=1,
            price=Decimal("0.55"),
            cost_basis_cents=55,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-2",
        )
    session.close()


def test_open_paper_position_validates_inputs(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"
    ticker = "KXHIGHNY-25MAY28-T72"

    with pytest.raises(LedgerError, match="Quantity"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker=ticker,
            side=PositionSide.YES,
            qty=0,
            price=Decimal("0.55"),
            cost_basis_cents=55,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-3a",
        )
    with pytest.raises(LedgerError, match="Cost basis"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker=ticker,
            side=PositionSide.YES,
            qty=1,
            price=Decimal("0.55"),
            cost_basis_cents=0,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-3b",
        )
    with pytest.raises(LedgerError, match="Fees"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker=ticker,
            side=PositionSide.YES,
            qty=1,
            price=Decimal("0.55"),
            cost_basis_cents=55,
            signal_id=None,
            fees_cents=-1,
            simulator_assumptions={"fillModel": "quoted"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-3c",
        )
    session.close()


def test_open_paper_position_writes_position_audit_without_fee(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"

    position, fill = writer.open_paper_position(
        session,
        strategy_name=strategy_name,
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=5,
        price=Decimal("0.55"),
        cost_basis_cents=275,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted"},
        actor=AuditActor.SCHEDULER,
        request_id="pos-req-4",
    )
    session.commit()

    audit = session.scalars(
        select(AuditEventRow).where(
            AuditEventRow.target_id == position.id,
            AuditEventRow.action == "open_paper_position",
            AuditEventRow.request_id == "pos-req-4",
        )
    ).first()
    assert audit is not None
    assert audit.after_state["fillId"] == fill.id
    session.close()
