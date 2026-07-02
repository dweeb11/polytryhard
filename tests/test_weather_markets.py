from datetime import date
from decimal import Decimal

import pytest

from core.domain.weather_markets import (
    bracket_probability,
    bracket_satisfied,
    location_for_series,
    target_local_date,
    weather_series,
)


def test_target_local_date_parses_kalshi_ticker() -> None:
    assert target_local_date("KXHIGHNY-25MAY28-T72") == date(2025, 5, 28)
    assert target_local_date("KXHIGHCHI-26JAN02-B34.5") == date(2026, 1, 2)


def test_target_local_date_rejects_garbage() -> None:
    assert target_local_date("KXHIGHNY") is None
    assert target_local_date("KXHIGHNY-NODATE-T72") is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [(Decimal("74"), True), (Decimal("73"), False), (Decimal("73.5"), True)],
)
def test_bracket_greater_is_strictly_above_floor(value: Decimal, expected: bool) -> None:
    # EMPIRICALLY VERIFIED — scripts/verify_bracket_semantics.py, 66 resolutions, 0 mismatches.
    assert (
        bracket_satisfied(value, strike_type="greater", floor_strike=Decimal("73"), cap_strike=None)
        is expected
    )


def test_bracket_less_is_strictly_below_cap() -> None:
    assert (
        bracket_satisfied(
            Decimal("71"), strike_type="less", floor_strike=None, cap_strike=Decimal("72")
        )
        is True
    )
    assert (
        bracket_satisfied(
            Decimal("72"), strike_type="less", floor_strike=None, cap_strike=Decimal("72")
        )
        is False
    )


def test_bracket_between_is_inclusive() -> None:
    for value, expected in [("72", True), ("73", True), ("71.9", False), ("73.1", False)]:
        assert (
            bracket_satisfied(
                Decimal(value),
                strike_type="between",
                floor_strike=Decimal("72"),
                cap_strike=Decimal("73"),
            )
            is expected
        )


def test_bracket_unknown_type_returns_none() -> None:
    assert (
        bracket_satisfied(
            Decimal("72"), strike_type="functional", floor_strike=None, cap_strike=None
        )
        is None
    )


def test_bracket_probability_laplace_smoothing() -> None:
    maxes = [Decimal("74"), Decimal("75"), Decimal("71"), Decimal("70")]
    # 2 of 4 above floor 73 -> (2 + 1) / (4 + 2) = 0.5
    prob = bracket_probability(
        maxes, strike_type="greater", floor_strike=Decimal("73"), cap_strike=None
    )
    assert prob == Decimal("3") / Decimal("6")


def test_bracket_probability_never_zero_or_one() -> None:
    maxes = [Decimal("90")] * 10
    prob = bracket_probability(
        maxes, strike_type="greater", floor_strike=Decimal("73"), cap_strike=None
    )
    assert prob is not None
    assert Decimal("0") < prob < Decimal("1")


def test_bracket_probability_empty_members_is_none() -> None:
    assert (
        bracket_probability([], strike_type="greater", floor_strike=Decimal("73"), cap_strike=None)
        is None
    )


def test_series_helpers_moved_here() -> None:
    assert weather_series("KXHIGHNY") is True
    assert location_for_series("KXHIGHCHI") == "chicago"
