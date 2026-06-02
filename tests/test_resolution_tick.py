from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide
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
            },
            consecutive_min_position_rejections=0,
            last_state_change_at=now,
            created_at=now,
            updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "test setup", AuditActor.USER, "rq")
    session.commit()


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
    _create_strategy(per_env, name)
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
    _create_strategy(per_env, name)
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
