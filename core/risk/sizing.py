from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from core.db.enums import PositionStatus
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.domain.enums import PositionSide, SignalOutcome, SystemState
from core.domain.feature import FeatureStatus, FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.strategy import (
    DEFAULT_CORRELATION_CAP_PCT,
    DEFAULT_EXPOSURE_CAP_PCT,
    StrategyConfig,
    effective_strategy_config,
)
from core.domain.system import SystemEnvState
from core.domain.trading import Order, Rejection
from core.strategies.weather_utils import location_for_series

MIN_QTY = 1
PRICE_SCALE = Decimal("100")


@dataclass(frozen=True)
class SizingInput:
    signal: SignalDraft
    market: MarketState
    strategy: StrategyInstanceRow
    system_state: SystemEnvState
    open_positions: tuple[PaperPositionRow, ...]
    features: dict[str, FeatureValue]
    free_cash_cents: int
    total_bankroll_cents: int


def size_order(input_data: SizingInput) -> Order | Rejection:
    if input_data.system_state.state == SystemState.PAUSED:
        return Rejection(SignalOutcome.REJECTED_SYSTEM_PAUSED, "system paused")

    config = effective_strategy_config(
        input_data.strategy.config_jsonb,
        strategy_name=input_data.strategy.name,
    )
    stale = _stale_feature(config.max_input_age_seconds, input_data.features, input_data.market)
    if stale is not None:
        return Rejection(SignalOutcome.REJECTED_STALE_INPUTS, stale)

    confidence_floor = Decimal(str(config.confidence_floor))
    if input_data.signal.confidence < confidence_floor:
        return Rejection(SignalOutcome.REJECTED_BELOW_THRESHOLD, "below confidence threshold")

    price = _entry_price(input_data.signal.side, input_data.market)
    if price is None or price <= 0 or price >= 1:
        return Rejection(SignalOutcome.REJECTED_MARKET_CLOSED, "invalid market price")

    edge = _edge(input_data.signal, price)
    if edge <= 0:
        return Rejection(SignalOutcome.REJECTED_KELLY_ZERO, "non-positive edge")

    kelly = (
        float(input_data.strategy.kelly_fraction)
        * float(input_data.signal.confidence)
        * float(edge)
    )
    if kelly <= 0:
        return Rejection(SignalOutcome.REJECTED_KELLY_ZERO, "kelly zero")

    bankroll_dollars = Decimal(input_data.strategy.bankroll_cents) / Decimal("100")
    stake_dollars = bankroll_dollars * Decimal(str(kelly))
    cost_basis_cents = int((stake_dollars * PRICE_SCALE).to_integral_value(rounding=ROUND_DOWN))
    if cost_basis_cents <= 0:
        return Rejection(SignalOutcome.REJECTED_KELLY_ZERO, "size rounds to zero")

    qty = int(
        (Decimal(cost_basis_cents) / (price * PRICE_SCALE)).to_integral_value(rounding=ROUND_DOWN)
    )
    if qty < MIN_QTY:
        return Rejection(SignalOutcome.REJECTED_BELOW_MIN_POSITION, "below minimum position size")

    cost_basis_cents = int((price * PRICE_SCALE * qty).to_integral_value(rounding=ROUND_DOWN))
    if cost_basis_cents > input_data.free_cash_cents:
        return Rejection(SignalOutcome.REJECTED_BELOW_MIN_POSITION, "insufficient free cash")

    if _exposure_cap_exceeded(input_data, cost_basis_cents, config):
        return Rejection(SignalOutcome.REJECTED_EXPOSURE_CAP, "global exposure cap")

    if _correlation_cap_exceeded(input_data, cost_basis_cents, config):
        return Rejection(SignalOutcome.REJECTED_CORRELATION_CAP, "correlation cap")

    return Order(
        ticker=input_data.signal.ticker,
        side=input_data.signal.side,
        qty=qty,
        limit_price=price,
        cost_basis_cents=cost_basis_cents,
    )


def _entry_price(side: PositionSide, market: MarketState) -> Decimal | None:
    if side == PositionSide.YES:
        return market.ask_yes
    if market.bid_yes is None:
        return None
    return Decimal("1") - market.bid_yes


def _edge(signal: SignalDraft, price: Decimal) -> Decimal:
    if signal.side == PositionSide.YES:
        return signal.prob_yes - price
    no_prob = Decimal("1") - signal.prob_yes
    return no_prob - price


def _stale_feature(
    max_age_seconds: int,
    features: dict[str, FeatureValue],
    market: MarketState,
) -> str | None:
    cutoff = market.as_of - timedelta(seconds=max_age_seconds)
    location_id = location_for_series(market.series)
    scoped_subjects = {market.ticker, location_id}
    for feature in features.values():
        if feature.subject_id not in scoped_subjects:
            continue
        if feature.status == FeatureStatus.STALE:
            return f"stale feature {feature.provider_name}"
        if feature.status != FeatureStatus.PRESENT:
            return f"missing feature {feature.provider_name}"
        if feature.as_of is None or feature.as_of < cutoff:
            return f"stale feature {feature.provider_name}"
    return None


def _exposure_cap_exceeded(
    input_data: SizingInput,
    new_cost_basis_cents: int,
    config: StrategyConfig,
) -> bool:
    cap_pct = (
        config.exposure_cap_pct
        if config.exposure_cap_pct is not None
        else DEFAULT_EXPOSURE_CAP_PCT
    )
    open_cost = sum(
        pos.cost_basis_cents
        for pos in input_data.open_positions
        if pos.status == PositionStatus.OPEN
    )
    total_exposure = open_cost + new_cost_basis_cents
    cap = int(input_data.total_bankroll_cents * cap_pct)
    return total_exposure > cap


def _correlation_cap_exceeded(
    input_data: SizingInput,
    new_cost_basis_cents: int,
    config: StrategyConfig,
) -> bool:
    settlement_key = _settlement_key(input_data.market.ticker)
    if settlement_key is None:
        return False
    correlated_cost = sum(
        pos.cost_basis_cents
        for pos in input_data.open_positions
        if pos.status == PositionStatus.OPEN and _settlement_key(pos.ticker) == settlement_key
    )
    cap_pct = (
        config.correlation_cap_pct
        if config.correlation_cap_pct is not None
        else DEFAULT_CORRELATION_CAP_PCT
    )
    cap = int(input_data.strategy.bankroll_cents * cap_pct)
    return correlated_cost + new_cost_basis_cents > cap


def _settlement_key(ticker: str) -> str | None:
    parts = ticker.split("-")
    if len(parts) < 2:
        return None
    return parts[1]
