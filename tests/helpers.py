from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor
from core.ledger import writer
from core.utils.time import utc_now

EVAL_TEST_NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)

DEFAULT_STRATEGY_CONFIG: dict[str, object] = {
    "min_bankroll_cents": 10_000,
    "min_tradeable_bankroll_cents": 5_000,
    "max_drawdown_pct_from_hwm": 30,
    "auto_resume_on_deposit": True,
    "max_input_age_seconds": 900,
}


def create_funded_strategy(
    session: Session,
    name: str,
    *,
    config_jsonb: dict[str, object] | None = None,
) -> None:
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
            config_jsonb={**DEFAULT_STRATEGY_CONFIG, **(config_jsonb or {})},
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


def seed_contract_resolution(
    shared: Session,
    ticker: str,
    resolution: ContractResolution,
    *,
    resolved_at: datetime | None = None,
) -> None:
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
            resolved_at=resolved_at or EVAL_TEST_NOW,
            resolution=resolution,
            settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
            source_evidence_jsonb={},
        )
    )
    shared.commit()
