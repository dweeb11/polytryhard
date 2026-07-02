from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from core.db.enums import PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.domain.enums import PositionSide, SignalOutcome, SystemState
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.system import SystemEnvState
from core.domain.trading import Order, Rejection
from core.risk.fees import fee_per_contract_dollars, trading_fee_cents
from core.risk.sizing import SizingInput, size_order

AS_OF = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
TICKER = "KXHIGHNY-25MAY28-T72"


def _active_system_state() -> SystemEnvState:
    return SystemEnvState(
        state=SystemState.ACTIVE,
        kill_switch_reason=None,
        kill_switch_tripped_at=None,
    )


def _paused_system_state() -> SystemEnvState:
    return SystemEnvState(
        state=SystemState.PAUSED,
        kill_switch_reason="operator",
        kill_switch_tripped_at=AS_OF.isoformat(),
    )


def _strategy_row(**overrides: object) -> StrategyInstanceRow:
    row = StrategyInstanceRow(
        name="weather_ensemble_disagreement",
        enabled=True,
        state=DbStrategyState.ACTIVE,
        bankroll_cents=10_000,
        initial_deposit_cents=10_000,
        bankroll_hwm_cents=10_000,
        hwm_reset_at=None,
        kelly_fraction=Decimal("0.25"),
        config_jsonb={
            "minBankrollCents": 10_000,
            "minTradeableBankrollCents": 5_000,
            "maxDrawdownPctFromHwm": 30,
            "autoResumeOnDeposit": True,
            "maxInputAgeSeconds": 900,
            "confidenceFloor": 0.55,
        },
        consecutive_min_position_rejections=0,
        last_state_change_at=AS_OF,
        created_at=AS_OF,
        updated_at=AS_OF,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _features() -> dict[str, FeatureValue]:
    return {
        "ensemble_mean_temp": FeatureValue.present(
            provider_name="ensemble_mean_temp",
            provider_version="1",
            subject_kind="location",
            subject_id="nyc",
            as_of=AS_OF,
            value_numeric=Decimal("72"),
        ),
        "kalshi_spread": FeatureValue.present(
            provider_name="kalshi_spread",
            provider_version="1",
            subject_kind="market",
            subject_id=TICKER,
            as_of=AS_OF,
            value_numeric=Decimal("0.10"),
        ),
    }


def _market(**overrides: object) -> MarketState:
    market = MarketState(
        ticker=TICKER,
        series="KXHIGHNY",
        bid_yes=Decimal("0.40"),
        ask_yes=Decimal("0.55"),
        mid_yes=Decimal("0.475"),
        as_of=AS_OF,
        location_id="nyc",
    )
    for key, value in overrides.items():
        object.__setattr__(market, key, value)
    return market


def _signal(**overrides: object) -> SignalDraft:
    signal = SignalDraft(
        ticker=TICKER,
        prob_yes=Decimal("0.70"),
        confidence=Decimal("0.80"),
        side=PositionSide.YES,
    )
    for key, value in overrides.items():
        object.__setattr__(signal, key, value)
    return signal


def _open_position(*, ticker: str, cost_basis_cents: int) -> PaperPositionRow:
    return PaperPositionRow(
        id="pos-1",
        strategy_name="weather_ensemble_disagreement",
        ticker=ticker,
        side=PositionSide.YES,
        opened_at=AS_OF,
        closed_at=None,
        open_avg_price=Decimal("0.50"),
        qty=10,
        cost_basis_cents=cost_basis_cents,
        realized_pnl_cents=None,
        unrealized_pnl_cents=0,
        status=PositionStatus.OPEN,
    )


def _sizing_input(**overrides: object) -> SizingInput:
    base = SizingInput(
        signal=_signal(),
        market=_market(),
        strategy=_strategy_row(),
        system_state=_active_system_state(),
        open_positions=(),
        features=_features(),
        free_cash_cents=10_000,
    )
    for key, value in overrides.items():
        object.__setattr__(base, key, value)
    return base


def test_size_order_places_when_edge_positive() -> None:
    result = size_order(_sizing_input())
    assert isinstance(result, Order)
    # Binary Kelly denominator (1 - price) roughly doubles the stake vs. the old
    # fraction*confidence*edge formula; fees also shave a bit off net edge.
    assert result.qty == 10
    assert result.cost_basis_cents == 550
    assert result.limit_price == Decimal("0.55")
    assert result.side == PositionSide.YES


def test_size_order_places_no_side_when_edge_positive() -> None:
    result = size_order(
        _sizing_input(
            signal=_signal(prob_yes=Decimal("0.30"), side=PositionSide.NO),
        )
    )
    assert isinstance(result, Order)
    assert result.side == PositionSide.NO
    assert result.limit_price == Decimal("0.60")
    assert result.qty >= 1


def test_size_order_accepts_confidence_at_floor() -> None:
    result = size_order(_sizing_input(signal=_signal(confidence=Decimal("0.55"))))
    assert isinstance(result, Order)


def test_size_order_rejects_stale_inputs_by_age() -> None:
    stale_features = _features()
    stale_features["ensemble_mean_temp"] = FeatureValue.present(
        provider_name="ensemble_mean_temp",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc",
        as_of=AS_OF - timedelta(hours=2),
        value_numeric=Decimal("72"),
    )
    result = size_order(_sizing_input(features=stale_features))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_STALE_INPUTS


def test_size_order_rejects_stale_feature_status() -> None:
    stale_features = _features()
    stale_features["ensemble_mean_temp"] = FeatureValue.stale(
        provider_name="ensemble_mean_temp",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc",
        as_of=AS_OF,
        value_numeric=Decimal("72"),
    )
    result = size_order(_sizing_input(features=stale_features))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_STALE_INPUTS


def test_size_order_rejects_zero_edge() -> None:
    result = size_order(_sizing_input(signal=_signal(prob_yes=Decimal("0.50"))))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_KELLY_ZERO


def test_size_order_rejects_below_confidence_floor() -> None:
    result = size_order(_sizing_input(signal=_signal(confidence=Decimal("0.50"))))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_BELOW_THRESHOLD


def test_size_order_rejects_system_paused() -> None:
    result = size_order(_sizing_input(system_state=_paused_system_state()))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_SYSTEM_PAUSED


def test_size_order_rejects_insufficient_free_cash() -> None:
    result = size_order(_sizing_input(free_cash_cents=50))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_BELOW_MIN_POSITION
    assert result.reason == "insufficient free cash"


def test_size_order_rejects_global_exposure_cap() -> None:
    strategy = _strategy_row(
        config_jsonb={
            **_strategy_row().config_jsonb,
            "exposureCapPct": 0.01,
        }
    )
    result = size_order(_sizing_input(strategy=strategy))
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_EXPOSURE_CAP


def test_size_order_rejects_correlation_cap() -> None:
    strategy = _strategy_row(
        config_jsonb={
            **_strategy_row().config_jsonb,
            "exposureCapPct": 1.0,
        }
    )
    result = size_order(
        _sizing_input(
            strategy=strategy,
            open_positions=(_open_position(ticker="KXHIGHCHI-25MAY28-T80", cost_basis_cents=4900),),
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_CORRELATION_CAP


def test_size_order_allows_correlation_at_cap_boundary() -> None:
    strategy = _strategy_row(
        config_jsonb={
            **_strategy_row().config_jsonb,
            "exposureCapPct": 1.0,
        }
    )
    # Default correlation cap 0.5 * bankroll(10_000) = 5_000; new order costs 550
    # under the binary-Kelly formula, so 4_450 lands exactly at the boundary.
    result = size_order(
        _sizing_input(
            strategy=strategy,
            open_positions=(_open_position(ticker="KXHIGHCHI-25MAY28-T80", cost_basis_cents=4450),),
        )
    )
    assert isinstance(result, Order)


def test_size_order_rejects_invalid_no_price_when_bid_missing() -> None:
    result = size_order(
        _sizing_input(
            signal=_signal(prob_yes=Decimal("0.30"), side=PositionSide.NO),
            market=_market(bid_yes=None),
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_MARKET_CLOSED


def test_rejects_when_already_positioned_in_ticker() -> None:
    result = size_order(
        _sizing_input(
            open_positions=(_open_position(ticker=TICKER, cost_basis_cents=100),),
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_ALREADY_POSITIONED


def test_rejects_when_edge_does_not_clear_fee() -> None:
    # prob_yes 0.51, ask_yes 0.50 -> raw edge 0.01; fee at 0.5 = 0.0175 -> net negative
    result = size_order(
        _sizing_input(
            signal=_signal(prob_yes=Decimal("0.51")),
            market=_market(ask_yes=Decimal("0.50")),
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_KELLY_ZERO
    assert result.reason == "edge below fees"


def test_kelly_uses_binary_denominator() -> None:
    price = Decimal("0.50")
    signal = _signal(prob_yes=Decimal("0.70"))
    market = _market(ask_yes=price)
    strategy = _strategy_row()

    result = size_order(_sizing_input(signal=signal, market=market, strategy=strategy))
    assert isinstance(result, Order)

    raw_edge = signal.prob_yes - price
    net_edge = raw_edge - fee_per_contract_dollars(price)
    kelly = float(strategy.kelly_fraction) * float(signal.confidence) * float(
        net_edge / (Decimal("1") - price)
    )
    bankroll_dollars = Decimal(strategy.bankroll_cents) / Decimal("100")
    stake_dollars = bankroll_dollars * Decimal(str(kelly))
    cost_basis_cents = int((stake_dollars * Decimal("100")).to_integral_value(rounding=ROUND_DOWN))
    expected_qty = int(
        (Decimal(cost_basis_cents) / (price * Decimal("100"))).to_integral_value(
            rounding=ROUND_DOWN
        )
    )
    assert result.qty == expected_qty


def test_exposure_cap_uses_strategy_bankroll() -> None:
    # This strategy's own bankroll is small (1_000 cents) even though other
    # strategies could hold a much larger total pot; the cap must be computed
    # against *this* strategy's bankroll, not the sum across all strategies.
    strategy = _strategy_row(
        bankroll_cents=1_000,
        config_jsonb={
            **_strategy_row().config_jsonb,
            "exposureCapPct": 0.5,
        },
    )
    # cap = 0.5 * 1_000 = 500; open cost 460 + new order cost 55 = 515 > 500.
    result = size_order(
        _sizing_input(
            strategy=strategy,
            open_positions=(
                _open_position(ticker="KXHIGHCHI-25MAY28-T80", cost_basis_cents=460),
            ),
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_EXPOSURE_CAP


def test_order_carries_fees_cents() -> None:
    result = size_order(_sizing_input())
    assert isinstance(result, Order)
    assert result.fees_cents == trading_fee_cents(result.qty, result.limit_price)


def test_rejects_when_rounded_fee_wipes_out_edge() -> None:
    # price=0.50, edge=0.019 clears the un-rounded per-contract fee (0.0175),
    # so the early net-edge gate passes. But at qty=1 the *rounded* fee
    # (ceil(0.0175 * 100) = 2 cents) exceeds the gross edge in cents (1.9),
    # so the order should still be rejected once qty is known.
    price = Decimal("0.50")
    prob_yes = Decimal("0.519")
    edge = prob_yes - price
    net_edge = edge - fee_per_contract_dollars(price)
    assert net_edge > 0  # sanity: un-rounded gate would pass

    # Large bankroll needed because kelly stake is tiny here; tuned so qty == 1.
    strategy = _strategy_row(bankroll_cents=83_400)
    result = size_order(
        _sizing_input(
            signal=_signal(prob_yes=prob_yes),
            market=_market(ask_yes=price),
            strategy=strategy,
            free_cash_cents=83_400,
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_KELLY_ZERO
    assert result.reason == "edge below fees"
