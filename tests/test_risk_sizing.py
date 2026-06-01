from datetime import UTC, datetime, timedelta
from decimal import Decimal

from core.db.enums import PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.domain.enums import PositionSide, SignalOutcome, SystemState
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.system import SystemEnvState
from core.domain.trading import Order, Rejection
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
        total_bankroll_cents=10_000,
    )
    for key, value in overrides.items():
        object.__setattr__(base, key, value)
    return base


def test_size_order_places_when_edge_positive() -> None:
    result = size_order(_sizing_input())
    assert isinstance(result, Order)
    assert result.qty == 5
    assert result.cost_basis_cents == 275
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
    result = size_order(
        _sizing_input(
            strategy=strategy,
            open_positions=(_open_position(ticker="KXHIGHCHI-25MAY28-T80", cost_basis_cents=4725),),
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
