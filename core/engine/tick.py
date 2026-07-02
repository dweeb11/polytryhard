from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.clock import Clock
from core.contracts.executor import ExecutorContext
from core.contracts.feature import FeatureContext
from core.contracts.strategy import StrategyContext
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.domain.enums import AuditActor, SignalOutcome, StrategyState
from core.domain.feature import FeatureValue
from core.domain.state_machine import can_emit_signals
from core.domain.strategy import effective_strategy_config
from core.domain.trading import Rejection
from core.engine.markets import (
    build_market_states,
    features_snapshot,
    index_features,
    strategy_features_for_market,
    total_bankroll_cents,
)
from core.executors.registry import default_executor
from core.features.persistence import persist_feature_values
from core.features.registry import enabled_feature_providers
from core.ledger import writer
from core.ledger.queries import free_cash_cents, get_system_state
from core.risk.sizing import SizingInput, size_order
from core.settings import Settings
from core.strategies.registry import registered_strategies

logger = logging.getLogger(__name__)


def _strategy_open_positions(session: Session, strategy_name: str) -> tuple[PaperPositionRow, ...]:
    return tuple(
        session.scalars(
            select(PaperPositionRow).where(
                PaperPositionRow.status == "open",
                PaperPositionRow.strategy_name == strategy_name,
            )
        ).all()
    )


def _engine_request_id() -> str:
    return f"engine_{uuid4().hex[:12]}"


async def run_engine_tick(
    *,
    settings: Settings,
    clock: Clock,
    shared_session: Session,
    per_env_session: Session,
    request_id: str | None = None,
) -> dict[str, int]:
    tick_id = request_id or _engine_request_id()
    as_of = clock.now()
    stats = {"features": 0, "signals": 0, "orders": 0}

    feature_ctx = FeatureContext(request_id=tick_id, settings=settings, session=shared_session)
    computed: list[FeatureValue] = []
    for provider in enabled_feature_providers(settings):
        values = await provider.compute(as_of, feature_ctx)
        computed.extend(values)
    stats["features"] = persist_feature_values(shared_session, computed)

    feature_index = index_features(computed)
    markets = build_market_states(shared_session, as_of)
    system_state = get_system_state(per_env_session)
    bankroll_total = total_bankroll_cents(per_env_session)
    strategy_rows = {
        row.name: row
        for row in per_env_session.scalars(select(StrategyInstanceRow)).all()
    }
    executor = default_executor(settings)

    for strategy_impl in registered_strategies():
        row = strategy_rows.get(strategy_impl.name)
        if row is None:
            continue

        config = effective_strategy_config(row.config_jsonb, strategy_name=row.name)
        if (
            StrategyState(row.state) == StrategyState.ACTIVE
            and row.bankroll_hwm_cents > 0
        ):
            drawdown_pct = (
                (row.bankroll_hwm_cents - row.bankroll_cents)
                / row.bankroll_hwm_cents
                * 100
            )
            if drawdown_pct >= config.max_drawdown_pct_from_hwm:
                writer.drawdown_pause_strategy(
                    per_env_session,
                    row.name,
                    f"drawdown {drawdown_pct:.1f}% >= "
                    f"{config.max_drawdown_pct_from_hwm}% from HWM",
                    AuditActor.SCHEDULER,
                    tick_id,
                )
                continue

        if not can_emit_signals(
            enabled=row.enabled,
            state=StrategyState(row.state),
            kelly_fraction=float(row.kelly_fraction),
        ):
            continue

        ctx = StrategyContext(strategy_name=row.name, config_jsonb=row.config_jsonb)
        strategy_open = _strategy_open_positions(per_env_session, row.name)

        for market in markets:
            market_features = strategy_features_for_market(
                feature_index,
                location_id=market.location_id,
                ticker=market.ticker,
            )
            signal = strategy_impl.evaluate(market, market_features, ctx)
            if signal is None:
                continue

            snapshot = features_snapshot(market_features)
            sizing = size_order(
                SizingInput(
                    signal=signal,
                    market=market,
                    strategy=row,
                    system_state=system_state,
                    open_positions=strategy_open,
                    features=market_features,
                    free_cash_cents=free_cash_cents(per_env_session, row.name),
                    total_bankroll_cents=bankroll_total,
                )
            )

            if isinstance(sizing, Rejection):
                writer.record_signal(
                    per_env_session,
                    strategy_name=row.name,
                    signal=signal,
                    market=market,
                    features_snapshot=snapshot,
                    outcome=sizing.outcome,
                    rejection_reason=sizing.reason,
                    actor=AuditActor.SCHEDULER,
                    request_id=tick_id,
                )
                stats["signals"] += 1
                continue

            signal_row = writer.record_signal(
                per_env_session,
                strategy_name=row.name,
                signal=signal,
                market=market,
                features_snapshot=snapshot,
                outcome=SignalOutcome.ORDER_PLACED,
                rejection_reason=None,
                actor=AuditActor.SCHEDULER,
                request_id=tick_id,
            )
            stats["signals"] += 1
            await executor.place(
                sizing,
                ExecutorContext(
                    request_id=tick_id,
                    session=per_env_session,
                    strategy_name=row.name,
                    signal_id=signal_row.id,
                    fees_cents=0,
                ),
            )
            stats["orders"] += 1
            strategy_open = _strategy_open_positions(per_env_session, row.name)

    per_env_session.commit()
    shared_session.commit()
    logger.info(
        "engine tick complete request_id=%s features=%s signals=%s orders=%s",
        tick_id,
        stats["features"],
        stats["signals"],
        stats["orders"],
    )
    return stats
