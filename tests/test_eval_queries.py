from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import SignalRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.eval.queries import bankroll_balance_series, resolved_trades
from core.ledger import writer
from core.utils.time import utc_now

NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

_DEFAULT_CONFIG: dict[str, object] = {
    "min_bankroll_cents": 10_000,
    "min_tradeable_bankroll_cents": 5_000,
    "max_drawdown_pct_from_hwm": 30,
    "auto_resume_on_deposit": True,
    "max_input_age_seconds": 900,
}


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
            config_jsonb=_DEFAULT_CONFIG,
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


def _seed_resolution(shared: Session, ticker: str, resolution: ContractResolution) -> None:
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
            resolved_at=NOW,
            resolution=resolution,
            settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
            source_evidence_jsonb={},
        )
    )
    shared.commit()


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
        _seed_resolution(shared, "KX-WIN", ContractResolution.YES)
        _seed_resolution(shared, "KX-VOID", ContractResolution.VOID)

    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
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
            window="all",
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
        _seed_resolution(shared, "KX-NOSIG", ContractResolution.YES)
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
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
            window="all",
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
        _seed_resolution(shared, "KX-OLD", ContractResolution.YES)
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
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
            window="30d",
            now=NOW,
        )
        in_all = resolved_trades(
            per_env_session=per_env,
            shared_session=shared,
            strategy_name=name,
            window="all",
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
    _create_strategy(per_env, name)
    series = bankroll_balance_series(
        per_env_session=per_env, strategy_name=name, window="all", now=NOW
    )
    assert series == [100_00]
    per_env.close()
