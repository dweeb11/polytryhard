from decimal import Decimal

from helpers import EVAL_TEST_NOW, create_funded_strategy, seed_contract_resolution
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow, SignalRow
from core.db.shared_enums import ContractResolution
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.eval.snapshot import recompute_all, recompute_strategy
from core.ledger import writer
from core.utils.time import utc_now

NOW = EVAL_TEST_NOW


def _signal_and_position(per_env: Session, *, name: str, ticker: str, prob: str) -> None:
    sid = f"sig-{ticker}"
    per_env.add(
        SignalRow(
            id=sid,
            strategy_name=name,
            ticker=ticker,
            evaluated_at=utc_now(),
            prob_yes=Decimal(prob),
            confidence=Decimal("0.6"),
            features_snapshot_jsonb={},
            market_state_jsonb={},
            outcome=SignalOutcome.ORDER_PLACED,
            rejection_reason=None,
        )
    )
    per_env.flush()
    pos, _ = writer.open_paper_position(
        per_env,
        strategy_name=name,
        order_ticker=ticker,
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.40"),
        cost_basis_cents=400,
        signal_id=sid,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="rq-open",
    )
    writer.resolve_position(
        per_env,
        position=pos,
        resolution=ContractResolution.YES,
        settlement_value=Decimal("1"),
        actor=AuditActor.SCHEDULER,
        request_id="rq-res",
    )
    per_env.commit()


def test_recompute_strategy_writes_three_windows(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_a"
    with Session(shared_engine) as shared:
        seed_contract_resolution(shared, "KX-A", ContractResolution.YES)
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name, config_jsonb={"posterior_tau": 0.5})
    _signal_and_position(per_env, name=name, ticker="KX-A", prob="0.6")

    with Session(shared_engine) as shared:
        recompute_strategy(
            per_env_session=per_env, shared_session=shared, strategy_name=name, now=NOW
        )
        per_env.commit()

    rows = per_env.scalars(
        select(EvalMetricSnapshotRow).where(EvalMetricSnapshotRow.strategy_name == name)
    ).all()
    assert {r.window for r in rows} == {EvalWindow.D7, EvalWindow.D30, EvalWindow.ALL}
    all_window = next(r for r in rows if r.window == EvalWindow.ALL)
    assert all_window.n_trades == 1
    assert all_window.n_wins == 1
    assert all_window.brier_score == (0.6 - 1) ** 2
    assert all_window.pnl_cents == 600
    per_env.close()


def test_recompute_strategy_uses_config_tau(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_tau"
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, name, config_jsonb={"posterior_tau": 1.0})
    with Session(shared_engine) as shared:
        recompute_strategy(
            per_env_session=per_env, shared_session=shared, strategy_name=name, now=NOW
        )
        per_env.commit()
    row = per_env.scalars(
        select(EvalMetricSnapshotRow).where(EvalMetricSnapshotRow.window == EvalWindow.ALL)
    ).one()
    assert row.n_trades == 0
    assert row.posterior_edge_ci_high == 1.96 * 1.0
    per_env.close()


def test_recompute_all_covers_every_strategy(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    per_env = per_env_session_factory()
    create_funded_strategy(per_env, "s1")
    create_funded_strategy(per_env, "s2")
    with Session(shared_engine) as shared:
        recompute_all(per_env_session=per_env, shared_session=shared, now=NOW)
        per_env.commit()
    rows = per_env.scalars(select(EvalMetricSnapshotRow)).all()
    assert len(rows) == 6
    per_env.close()
