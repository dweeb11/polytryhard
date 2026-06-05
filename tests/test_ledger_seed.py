from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.models import CashEventRow, StrategyInstanceRow
from core.ledger.seed import seed_strategies_if_needed


def _session(factory: sessionmaker[Session]) -> Session:
    return factory()


def test_seed_uses_default_paper_bankroll(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed",
            initial_bankroll_cents=25_000,
        )

        rows = session.scalars(select(StrategyInstanceRow)).all()
        assert {row.name for row in rows} == {
            "weather_ensemble_disagreement",
            "weather_stale_quote",
        }
        for row in rows:
            assert row.bankroll_cents == 25_000
            assert row.initial_deposit_cents == 25_000
            assert row.bankroll_hwm_cents == 25_000
            assert row.config_jsonb["min_bankroll_cents"] == 25_000
            assert row.config_jsonb["min_tradeable_bankroll_cents"] == 5_000


def test_seed_uses_per_strategy_bankroll_override(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed",
            initial_bankroll_cents=25_000,
            strategy_bankroll_overrides={"weather_stale_quote": 15_000},
        )

        ensemble = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
        stale = session.get(StrategyInstanceRow, "weather_stale_quote")
        assert ensemble is not None
        assert stale is not None
        assert ensemble.bankroll_cents == 25_000
        assert ensemble.initial_deposit_cents == 25_000
        assert ensemble.bankroll_hwm_cents == 25_000
        assert ensemble.config_jsonb["min_bankroll_cents"] == 25_000
        assert stale.bankroll_cents == 15_000
        assert stale.initial_deposit_cents == 15_000
        assert stale.bankroll_hwm_cents == 15_000
        assert stale.config_jsonb["min_bankroll_cents"] == 15_000


def test_seed_derives_config_thresholds_for_sub_default_bankroll(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed",
            initial_bankroll_cents=8_000,
        )

        row = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
        assert row is not None
        assert row.bankroll_cents == 8_000
        assert row.bankroll_cents >= row.config_jsonb["min_bankroll_cents"]
        assert row.config_jsonb["min_bankroll_cents"] == 8_000
        assert row.config_jsonb["min_tradeable_bankroll_cents"] == 5_000


def test_seed_scales_min_tradeable_below_default_floor(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed",
            initial_bankroll_cents=3_000,
        )

        row = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
        assert row is not None
        assert row.bankroll_cents == 3_000
        assert row.config_jsonb["min_bankroll_cents"] == 3_000
        assert row.config_jsonb["min_tradeable_bankroll_cents"] == 3_000


def test_seed_writes_initial_deposit_cash_event(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed",
            initial_bankroll_cents=12_345,
        )

        events = session.scalars(
            select(CashEventRow).where(
                CashEventRow.strategy_name == "weather_ensemble_disagreement"
            )
        ).all()
        assert len(events) == 1
        assert events[0].amount_cents == 12_345
        assert events[0].balance_after_cents == 12_345


def test_seed_is_idempotent_and_does_not_rewrite_existing_ledger(
    per_env_session_factory: sessionmaker[Session],
) -> None:
    with _session(per_env_session_factory) as session:
        seed_strategies_if_needed(
            session,
            request_id="test_seed_1",
            initial_bankroll_cents=10_000,
        )
        seed_strategies_if_needed(
            session,
            request_id="test_seed_2",
            initial_bankroll_cents=50_000,
        )

        strategy = session.get(StrategyInstanceRow, "weather_ensemble_disagreement")
        assert strategy is not None
        assert strategy.bankroll_cents == 10_000
        assert strategy.initial_deposit_cents == 10_000
        assert strategy.bankroll_hwm_cents == 10_000
        assert session.scalar(select(func.count()).select_from(CashEventRow)) == 2
