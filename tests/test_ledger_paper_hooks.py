from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import AuditEventRow, CashEventRow, SignalRow, StrategyInstanceRow
from core.domain.enums import AuditActor, CashEventKind, PositionSide, SignalOutcome
from core.domain.market import MarketState, SignalDraft
from core.ledger import writer
from core.ledger.errors import LedgerError
from core.ledger.queries import free_cash_cents
from core.ledger.reconcile import check_bankroll_invariant
from core.ledger.seed import INITIAL_DEPOSIT_CENTS, seed_strategies_if_needed


def _expected_cost(qty: int, price: Decimal) -> int:
    return int((Decimal(qty) * price * 100).quantize(Decimal("1")))


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


def test_activate_blocked_when_kill_switch_active(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    name = "weather_ensemble_disagreement"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    row.state = DbStrategyState.SEEDED
    writer.apply_kill_switch(session, "incident", AuditActor.USER, "kill-activate")
    session.commit()

    with pytest.raises(LedgerError, match="kill switch"):
        writer.activate_strategy(session, name, "go live", AuditActor.USER, "activate-req")
    session.close()


def test_bootstrap_activate_succeeds_when_kill_switch_active(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    name = "weather_ensemble_disagreement"
    row = session.get(StrategyInstanceRow, name)
    assert row is not None
    row.state = DbStrategyState.SEEDED
    writer.apply_kill_switch(session, "incident", AuditActor.USER, "kill-bootstrap")
    session.commit()

    writer.bootstrap_activate_strategy(
        session, name, "initial seed activation", AuditActor.SYSTEM, "bootstrap-req"
    )
    session.commit()

    assert row.state == DbStrategyState.ACTIVE
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
            qty=201,
            price=Decimal("0.50"),
            cost_basis_cents=_expected_cost(201, Decimal("0.50")),
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted_limit"},
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


def test_open_paper_position_reserves_free_cash_not_bankroll(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"
    free_before = free_cash_cents(session, strategy_name)
    cost_basis = 275

    writer.open_paper_position(
        session,
        strategy_name=strategy_name,
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=5,
        price=Decimal("0.55"),
        cost_basis_cents=cost_basis,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted_limit"},
        actor=AuditActor.SCHEDULER,
        request_id="pos-req-5",
    )
    session.commit()

    assert free_cash_cents(session, strategy_name) == free_before - cost_basis
    session.close()


def test_open_paper_position_second_open_fails_when_reserved(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"
    ticker = "KXHIGHNY-25MAY28-T72"
    first_cost = INITIAL_DEPOSIT_CENTS // 2

    writer.open_paper_position(
        session,
        strategy_name=strategy_name,
        order_ticker=ticker,
        side=PositionSide.YES,
        qty=100,
        price=Decimal("0.50"),
        cost_basis_cents=first_cost,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted_limit"},
        actor=AuditActor.SCHEDULER,
        request_id="pos-req-6a",
    )
    session.commit()

    with pytest.raises(LedgerError, match="free cash"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker=ticker,
            side=PositionSide.YES,
            qty=101,
            price=Decimal("0.50"),
            cost_basis_cents=_expected_cost(101, Decimal("0.50")),
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted_limit"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-6b",
        )
    session.close()


def test_open_paper_position_fee_debits_bankroll(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"
    strategy = session.get(StrategyInstanceRow, strategy_name)
    assert strategy is not None
    bankroll_before = strategy.bankroll_cents
    fee_cents = 25

    writer.open_paper_position(
        session,
        strategy_name=strategy_name,
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=5,
        price=Decimal("0.55"),
        cost_basis_cents=275,
        signal_id=None,
        fees_cents=fee_cents,
        simulator_assumptions={"fillModel": "quoted_limit"},
        actor=AuditActor.SCHEDULER,
        request_id="pos-req-7",
    )
    session.commit()

    strategy = session.get(StrategyInstanceRow, strategy_name)
    assert strategy is not None
    assert strategy.bankroll_cents == bankroll_before - fee_cents
    check_bankroll_invariant(session, strategy_name)

    fee_event = session.scalars(
        select(CashEventRow).where(
            CashEventRow.strategy_name == strategy_name,
            CashEventRow.kind == CashEventKind.FEE,
        )
    ).first()
    assert fee_event is not None
    assert fee_event.amount_cents == -fee_cents
    session.close()


def test_open_paper_position_links_signal_id(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"

    signal = writer.record_signal(
        session,
        strategy_name=strategy_name,
        signal=_signal_draft(),
        market=_market(),
        features_snapshot={},
        outcome=SignalOutcome.ORDER_PLACED,
        rejection_reason=None,
        actor=AuditActor.SCHEDULER,
        request_id="sig-link-1",
    )
    session.flush()

    _position, fill = writer.open_paper_position(
        session,
        strategy_name=strategy_name,
        order_ticker="KXHIGHNY-25MAY28-T72",
        side=PositionSide.YES,
        qty=1,
        price=Decimal("0.55"),
        cost_basis_cents=55,
        signal_id=signal.id,
        fees_cents=0,
        simulator_assumptions={"fillModel": "quoted_limit"},
        actor=AuditActor.SCHEDULER,
        request_id="pos-req-8",
    )
    session.commit()

    assert fill.signal_id == signal.id
    session.close()


def test_open_paper_position_rejects_unknown_strategy(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")

    with pytest.raises(LedgerError, match="Strategy not found"):
        writer.open_paper_position(
            session,
            strategy_name="no_such_strategy",
            order_ticker="KXHIGHNY-25MAY28-T72",
            side=PositionSide.YES,
            qty=1,
            price=Decimal("0.55"),
            cost_basis_cents=55,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted_limit"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-9",
        )
    session.close()


def test_open_paper_position_rejects_cost_basis_mismatch(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    session = per_env_session_factory()
    seed_strategies_if_needed(session, request_id="seed-test")
    strategy_name = "weather_ensemble_disagreement"

    with pytest.raises(LedgerError, match="does not match"):
        writer.open_paper_position(
            session,
            strategy_name=strategy_name,
            order_ticker="KXHIGHNY-25MAY28-T72",
            side=PositionSide.YES,
            qty=5,
            price=Decimal("0.55"),
            cost_basis_cents=300,
            signal_id=None,
            fees_cents=0,
            simulator_assumptions={"fillModel": "quoted_limit"},
            actor=AuditActor.SCHEDULER,
            request_id="pos-req-10",
        )
    session.close()
