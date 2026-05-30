from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.domain.enums import PositionSide, SignalOutcome, StrategyState, SystemState
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.state_machine import can_emit_signals
from core.domain.strategy import StrategyConfig
from core.domain.system import SystemEnvState
from core.domain.trading import Order, Rejection
from core.strategies.weather_utils import location_for_series

DEFAULT_EXPOSURE_CAP_PCT = 0.5
DEFAULT_CONFIDENCE_FLOOR = 0.55
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

    strategy_state = StrategyState(input_data.strategy.state)
    if not can_emit_signals(
        enabled=input_data.strategy.enabled,
        state=strategy_state,
        kelly_fraction=float(input_data.strategy.kelly_fraction),
    ):
        return Rejection(SignalOutcome.REJECTED_SYSTEM_PAUSED, "strategy not emitting")

    config = StrategyConfig.model_validate(input_data.strategy.config_jsonb)
    stale = _stale_feature(config.max_input_age_seconds, input_data.features, input_data.market)
    if stale is not None:
        return Rejection(SignalOutcome.REJECTED_STALE_INPUTS, stale)

    confidence_floor = Decimal(
        str(
            _config_float(
                input_data.strategy.config_jsonb,
                "confidenceFloor",
                DEFAULT_CONFIDENCE_FLOOR,
            )
        )
    )
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

    if _exposure_cap_exceeded(input_data, cost_basis_cents):
        return Rejection(SignalOutcome.REJECTED_EXPOSURE_CAP, "global exposure cap")

    if _correlation_cap_exceeded(input_data, cost_basis_cents):
        return Rejection(SignalOutcome.REJECTED_CORRELATION_CAP, "correlation cap")

    return Order(
        ticker=input_data.signal.ticker,
        side=input_data.signal.side,
        qty=qty,
        limit_price=price,
        cost_basis_cents=cost_basis_cents,
    )


def _config_float(config: dict[str, object], key: str, default: float) -> float:
    raw = config.get(key, default)
    if isinstance(raw, (int, float)):
        return float(raw)
    return default


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
    for feature in features.values():
        if feature.status.value != "present" or feature.as_of is None:
            continue
        if feature.subject_id not in {market.ticker, location_id}:
            continue
        if feature.as_of < cutoff:
            return f"stale feature {feature.provider_name}"
    return None


def _exposure_cap_exceeded(input_data: SizingInput, new_cost_basis_cents: int) -> bool:
    cap_pct = _config_float(
        input_data.strategy.config_jsonb,
        "exposureCapPct",
        DEFAULT_EXPOSURE_CAP_PCT,
    )
    open_cost = sum(
        pos.cost_basis_cents
        for pos in input_data.open_positions
        if pos.status.value == "open"
    )
    total_exposure = open_cost + new_cost_basis_cents
    cap = int(input_data.total_bankroll_cents * cap_pct)
    return total_exposure > cap


def _correlation_cap_exceeded(input_data: SizingInput, new_cost_basis_cents: int) -> bool:
    settlement_key = _settlement_key(input_data.market.ticker)
    if settlement_key is None:
        return False
    correlated_cost = sum(
        pos.cost_basis_cents
        for pos in input_data.open_positions
        if pos.status.value == "open" and _settlement_key(pos.ticker) == settlement_key
    )
    cap_pct = _config_float(
        input_data.strategy.config_jsonb,
        "correlationCapPct",
        DEFAULT_EXPOSURE_CAP_PCT,
    )
    cap = int(input_data.strategy.bankroll_cents * cap_pct)
    return correlated_cost + new_cost_basis_cents > cap


def _settlement_key(ticker: str) -> str | None:
    parts = ticker.split("-")
    if len(parts) < 2:
        return None
    return parts[1]
