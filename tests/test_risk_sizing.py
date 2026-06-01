from datetime import UTC, datetime, timedelta
from decimal import Decimal

from core.domain.trading import Order, Rejection

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import StrategyInstanceRow
from core.domain.enums import PositionSide, SignalOutcome, SystemState
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.system import SystemEnvState
from core.risk.sizing import SizingInput, size_order

AS_OF = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)


def _active_system_state() -> SystemEnvState:
    return SystemEnvState(
        state=SystemState.ACTIVE,
        kill_switch_reason=None,
        kill_switch_tripped_at=None,
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
            subject_id="KXHIGHNY-25MAY28-T72",
            as_of=AS_OF,
            value_numeric=Decimal("0.10"),
        ),
    }


def test_size_order_places_when_edge_positive() -> None:
    result = size_order(
        SizingInput(
            signal=SignalDraft(
                ticker="KXHIGHNY-25MAY28-T72",
                prob_yes=Decimal("0.70"),
                confidence=Decimal("0.80"),
                side=PositionSide.YES,
            ),
            market=MarketState(
                ticker="KXHIGHNY-25MAY28-T72",
                series="KXHIGHNY",
                bid_yes=Decimal("0.40"),
                ask_yes=Decimal("0.55"),
                mid_yes=Decimal("0.475"),
                as_of=AS_OF,
                location_id="nyc",
            ),
            strategy=_strategy_row(),
            system_state=_active_system_state(),
            open_positions=(),
            features=_features(),
            free_cash_cents=10_000,
            total_bankroll_cents=10_000,
        )
    )
    assert isinstance(result, Order)
    assert result.qty >= 1


def test_size_order_rejects_stale_inputs() -> None:
    stale_features = _features()
    stale_features["ensemble_mean_temp"] = FeatureValue.present(
        provider_name="ensemble_mean_temp",
        provider_version="1",
        subject_kind="location",
        subject_id="nyc",
        as_of=AS_OF - timedelta(hours=2),
        value_numeric=Decimal("72"),
    )
    result = size_order(
        SizingInput(
            signal=SignalDraft(
                ticker="KXHIGHNY-25MAY28-T72",
                prob_yes=Decimal("0.70"),
                confidence=Decimal("0.80"),
                side=PositionSide.YES,
            ),
            market=MarketState(
                ticker="KXHIGHNY-25MAY28-T72",
                series="KXHIGHNY",
                bid_yes=Decimal("0.40"),
                ask_yes=Decimal("0.55"),
                mid_yes=Decimal("0.475"),
                as_of=AS_OF,
                location_id="nyc",
            ),
            strategy=_strategy_row(),
            system_state=_active_system_state(),
            open_positions=(),
            features=stale_features,
            free_cash_cents=10_000,
            total_bankroll_cents=10_000,
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_STALE_INPUTS


def test_size_order_rejects_zero_edge() -> None:
    result = size_order(
        SizingInput(
            signal=SignalDraft(
                ticker="KXHIGHNY-25MAY28-T72",
                prob_yes=Decimal("0.50"),
                confidence=Decimal("0.80"),
                side=PositionSide.YES,
            ),
            market=MarketState(
                ticker="KXHIGHNY-25MAY28-T72",
                series="KXHIGHNY",
                bid_yes=Decimal("0.40"),
                ask_yes=Decimal("0.55"),
                mid_yes=Decimal("0.475"),
                as_of=AS_OF,
                location_id="nyc",
            ),
            strategy=_strategy_row(),
            system_state=_active_system_state(),
            open_positions=(),
            features=_features(),
            free_cash_cents=10_000,
            total_bankroll_cents=10_000,
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_KELLY_ZERO


def test_size_order_rejects_below_confidence_floor() -> None:
    result = size_order(
        SizingInput(
            signal=SignalDraft(
                ticker="KXHIGHNY-25MAY28-T72",
                prob_yes=Decimal("0.70"),
                confidence=Decimal("0.50"),
                side=PositionSide.YES,
            ),
            market=MarketState(
                ticker="KXHIGHNY-25MAY28-T72",
                series="KXHIGHNY",
                bid_yes=Decimal("0.40"),
                ask_yes=Decimal("0.55"),
                mid_yes=Decimal("0.475"),
                as_of=AS_OF,
                location_id="nyc",
            ),
            strategy=_strategy_row(),
            system_state=_active_system_state(),
            open_positions=(),
            features=_features(),
            free_cash_cents=10_000,
            total_bankroll_cents=10_000,
        )
    )
    assert isinstance(result, Rejection)
    assert result.outcome == SignalOutcome.REJECTED_BELOW_THRESHOLD
