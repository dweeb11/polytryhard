from datetime import timedelta
from decimal import Decimal

from helpers import EVAL_TEST_NOW, create_funded_strategy, seed_contract_resolution
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow
from core.db.models import SignalRow
from core.db.shared_enums import ContractResolution
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.eval.queries import bankroll_balance_series, resolved_trades
from core.ledger import writer
from core.utils.time import utc_now

NOW = EVAL_TEST_NOW


def _insert_signal(
    session: Session, *, signal_id: str, name: str, ticker: str, prob_yes: str
) -> None:
    session.add(
        SignalRow(
            id=signal_id,
            strategy_name=name,
            ticker=ticker,
            evaluated_at=utc_now(),
            prob_yes=Decimal(prob_yes),
            confidence=Decimal("0.6"),
            features_snapshot_jsonb={},
            market_state_jsonb={},
            outcome=SignalOutcome.ORDER_PLACED,
            rejection_reason=None,
        )
    )
    session.flush()


def _open_and_resolve(
    per_env: Session,
    *,
    name: str,
    signal_id: str | None,
    ticker: str,
    side: PositionSide,
    resolution: ContractResolution,
) -> None:
    pos, _ = writer.open_paper_position(
        per_env,
        strategy_name=name,
        order_ticker=ticker,
        side=side,
        qty=10,
        price=Decimal("0.40"),
        cost_basis_cents=400,
        signal_id=signal_id,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="rq-open",
    )
    writer.resolve_position(
        per_env,
        position=pos,
        resolution=resolution,
        settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
        actor=AuditActor.SCHEDULER,
        request_id="rq-res",
    )
    per_env.commit()


def test_resolved_trades_joins_signal_and_outcome(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_a"

    with Session(shared_engine) as shared:
        seed_contract_resolution(shared, "KX-WIN", ContractResolution.YES)
        seed_contract_resolution(shared, "KX-VOID", ContractResolution.VOID)

    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name)
    _insert_signal(per_env, signal_id="sig-win", name=name, ticker="KX-WIN", prob_yes="0.6")
    _insert_signal(per_env, signal_id="sig-void", name=name, ticker="KX-VOID", prob_yes="0.5")
    _open_and_resolve(
        per_env,
        name=name,
        signal_id="sig-win",
        ticker="KX-WIN",
        side=PositionSide.YES,
        resolution=ContractResolution.YES,
    )
    _open_and_resolve(
        per_env,
        name=name,
        signal_id="sig-void",
        ticker="KX-VOID",
        side=PositionSide.YES,
        resolution=ContractResolution.VOID,
    )

    with Session(shared_engine) as shared:
        trades = resolved_trades(
            per_env_session=per_env,
            shared_session=shared,
            strategy_name=name,
            window=EvalWindow.ALL,
            now=NOW,
        )

    assert len(trades) == 1
    assert trades[0].prob_yes == 0.6
    assert trades[0].outcome_yes == 1
    assert trades[0].realized_pnl_cents == 600
    assert trades[0].cost_basis_cents == 400
    per_env.close()


def test_resolved_trades_excludes_unsignaled_position(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_b"
    with Session(shared_engine) as shared:
        seed_contract_resolution(shared, "KX-NOSIG", ContractResolution.YES)
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name)
    _open_and_resolve(
        per_env,
        name=name,
        signal_id=None,
        ticker="KX-NOSIG",
        side=PositionSide.YES,
        resolution=ContractResolution.YES,
    )
    with Session(shared_engine) as shared:
        trades = resolved_trades(
            per_env_session=per_env,
            shared_session=shared,
            strategy_name=name,
            window=EvalWindow.ALL,
            now=NOW,
        )
    assert trades == []
    per_env.close()


def test_window_cutoff_excludes_old_trades(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_c"
    with Session(shared_engine) as shared:
        seed_contract_resolution(shared, "KX-OLD", ContractResolution.YES)
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name)
    _insert_signal(per_env, signal_id="sig-old", name=name, ticker="KX-OLD", prob_yes="0.6")
    _open_and_resolve(
        per_env,
        name=name,
        signal_id="sig-old",
        ticker="KX-OLD",
        side=PositionSide.YES,
        resolution=ContractResolution.YES,
    )
    from core.db.models import PaperPositionRow

    pos = per_env.query(PaperPositionRow).one()
    pos.closed_at = NOW - timedelta(days=40)
    per_env.commit()

    with Session(shared_engine) as shared:
        in_30d = resolved_trades(
            per_env_session=per_env,
            shared_session=shared,
            strategy_name=name,
            window=EvalWindow.D30,
            now=NOW,
        )
        in_all = resolved_trades(
            per_env_session=per_env,
            shared_session=shared,
            strategy_name=name,
            window=EvalWindow.ALL,
            now=NOW,
        )
    assert in_30d == []
    assert len(in_all) == 1
    per_env.close()


def test_bankroll_balance_series_chronological(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    name = "strat_d"
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name)
    series = bankroll_balance_series(
        per_env_session=per_env, strategy_name=name, window=EvalWindow.ALL, now=NOW
    )
    assert series == [100_00]
    per_env.close()
