from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow, PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import (
    CashEventRow,
    EvalMetricSnapshotRow,
    PaperPositionRow,
    SignalRow,
    StrategyInstanceRow,
)
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, CashEventKind, PositionSide, SignalOutcome
from core.engine.resolution import run_resolution_tick
from core.ledger import writer
from core.utils.time import utc_now


def _create_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name,
            enabled=True,
            state=DbStrategyState.SEEDED,
            bankroll_cents=0,
            initial_deposit_cents=0,
            bankroll_hwm_cents=0,
            hwm_reset_at=None,
            kelly_fraction=0.25,
            config_jsonb={
                "min_bankroll_cents": 10_000,
                "min_tradeable_bankroll_cents": 5_000,
                "max_drawdown_pct_from_hwm": 30,
                "auto_resume_on_deposit": True,
                "max_input_age_seconds": 900,
                "posterior_tau": 0.5,
            },
            consecutive_min_position_rejections=0,
            last_state_change_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "setup", AuditActor.USER, "rq")
    session.commit()


def test_full_loop_seed_open_resolve_eval(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "weather_demo"
    win_ticker, lose_ticker = "KX-WIN", "KX-LOSE"

    with Session(shared_engine) as shared:
        for ticker, resolution, value in (
            (win_ticker, ContractResolution.YES, "1"),
            (lose_ticker, ContractResolution.NO, "0"),
        ):
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
                    resolution=resolution,
                    settlement_value=Decimal(value),
                    source_evidence_jsonb={},
                )
            )
        shared.commit()

    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
    for sid, ticker, prob in (
        ("sig-win", win_ticker, "0.6"),
        ("sig-lose", lose_ticker, "0.7"),
    ):
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
        writer.open_paper_position(
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
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared, per_env_session=per_env, request_id="res-tick"
        )
    assert stats["resolved"] == 2

    strat = per_env.get(StrategyInstanceRow, name)
    assert strat is not None and strat.bankroll_cents == 100_00 + 200
    realized = [
        e for e in per_env.scalars(select(CashEventRow)).all()
        if e.kind == CashEventKind.REALIZED_PNL.value
    ]
    assert sorted(e.amount_cents for e in realized) == [-400, 600]
    assert all(
        p.status == PositionStatus.RESOLVED
        for p in per_env.scalars(select(PaperPositionRow)).all()
    )

    snap = per_env.scalars(
        select(EvalMetricSnapshotRow).where(
            EvalMetricSnapshotRow.strategy_name == name,
            EvalMetricSnapshotRow.window == EvalWindow.ALL,
        )
    ).one()
    assert snap.n_trades == 2
    assert snap.n_wins == 1
    assert snap.hit_rate == 0.5
    assert snap.brier_score == pytest.approx((0.16 + 0.49) / 2)
    assert snap.pnl_cents == 200
    per_env.close()
