from datetime import UTC, datetime
from decimal import Decimal

from helpers import create_funded_strategy
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import PositionStatus
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide
from core.engine.resolution import run_resolution_tick
from core.ledger import writer
from core.utils.time import utc_now


def test_resolution_tick_settles_open_positions(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    ticker = "KXT"

    with Session(shared_engine) as shared:
        shared.add(
            ReferenceMarketRow(
                ticker=ticker,
                series="S",
                title="t",
                settlement_source=None,
                settlement_ref=None,
                open_time=None,
                close_time=None,
                settlement_time=None,
                status="settled",
                raw_jsonb={},
            )
        )
        shared.flush()
        shared.add(
            ContractResolutionRow(
                ticker=ticker,
                resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=ContractResolution.YES,
                settlement_value=Decimal("1"),
                source_evidence_jsonb={},
            )
        )
        shared.commit()

    per_env = per_env_session_factory()
    name = "strat_a"
    create_funded_strategy(per_env, name)
    pos, _ = writer.open_paper_position(
        per_env,
        strategy_name=name,
        order_ticker=ticker,
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.40"),
        cost_basis_cents=400,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="rq-open",
    )
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared,
            per_env_session=per_env,
            now=utc_now(),
            request_id="res-tick-1",
        )

    assert stats["resolved"] == 1
    refreshed = per_env.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 600
    strat = per_env.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00 + 600

    with Session(shared_engine) as shared:
        stats2 = run_resolution_tick(
            shared_session=shared,
            per_env_session=per_env,
            now=utc_now(),
            request_id="res-tick-2",
        )
    assert stats2["resolved"] == 0
    per_env.close()


def test_resolution_tick_skips_open_without_resolution(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    ticker = "KXT-NO-RES"

    per_env = per_env_session_factory()
    name = "strat_open"
    create_funded_strategy(per_env, name)
    pos, _ = writer.open_paper_position(
        per_env,
        strategy_name=name,
        order_ticker=ticker,
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.40"),
        cost_basis_cents=400,
        signal_id=None,
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="rq-open",
    )
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared,
            per_env_session=per_env,
            now=utc_now(),
            request_id="res-tick-no-res",
        )

    assert stats["resolved"] == 0
    refreshed = per_env.get(PaperPositionRow, pos.id)
    assert refreshed is not None
    assert refreshed.status == PositionStatus.OPEN
    assert refreshed.realized_pnl_cents is None
    strat = per_env.get(StrategyInstanceRow, name)
    assert strat is not None
    assert strat.bankroll_cents == 100_00
    per_env.close()


def test_resolution_tick_writes_eval_snapshots(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    from sqlalchemy import select

    from core.db.enums import EvalWindow
    from core.db.models import EvalMetricSnapshotRow, SignalRow
    from core.domain.enums import SignalOutcome

    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    ticker = "KX-EVAL"

    with Session(shared_engine) as shared:
        shared.add(
            ReferenceMarketRow(
                ticker=ticker,
                series="S",
                title="t",
                settlement_source=None,
                settlement_ref=None,
                open_time=None,
                close_time=None,
                settlement_time=None,
                status="settled",
                raw_jsonb={},
            )
        )
        shared.flush()
        shared.add(
            ContractResolutionRow(
                ticker=ticker,
                resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=ContractResolution.YES,
                settlement_value=Decimal("1"),
                source_evidence_jsonb={},
            )
        )
        shared.commit()

    per_env = per_env_session_factory()
    name = "strat_a"
    create_funded_strategy(per_env, name)
    per_env.add(
        SignalRow(
            id="sig-eval",
            strategy_name=name,
            ticker=ticker,
            evaluated_at=utc_now(),
            prob_yes=Decimal("0.6"),
            confidence=Decimal("0.6"),
            features_snapshot_jsonb={},
            market_state_jsonb={},
            outcome=SignalOutcome.ORDER_PLACED,
            rejection_reason=None,
        )
    )
    per_env.flush()
    writer.open_paper_position(
        per_env,
        strategy_name=name,
        order_ticker=ticker,
        side=PositionSide.YES,
        qty=10,
        price=Decimal("0.40"),
        cost_basis_cents=400,
        signal_id="sig-eval",
        fees_cents=0,
        simulator_assumptions={},
        actor=AuditActor.SCHEDULER,
        request_id="rq-open",
    )
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared,
            per_env_session=per_env,
            now=utc_now(),
            request_id="res-tick",
        )
    assert stats["resolved"] == 1

    all_window = per_env.scalars(
        select(EvalMetricSnapshotRow).where(
            EvalMetricSnapshotRow.strategy_name == name,
            EvalMetricSnapshotRow.window == EvalWindow.ALL,
        )
    ).one()
    assert all_window.n_trades == 1
    assert all_window.pnl_cents == 600
    per_env.close()
