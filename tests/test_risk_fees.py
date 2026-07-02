from decimal import Decimal

from core.risk.fees import fee_per_contract_dollars, trading_fee_cents


def test_fee_rounds_up_to_next_cent() -> None:
    # 0.07 * 100 * 0.5 * 0.5 = 1.75 dollars -> 175 cents exactly
    assert trading_fee_cents(100, Decimal("0.5")) == 175
    # 0.07 * 1 * 0.5 * 0.5 = 0.0175 dollars -> rounds UP to 2 cents
    assert trading_fee_cents(1, Decimal("0.5")) == 2


def test_fee_zero_qty_is_zero() -> None:
    assert trading_fee_cents(0, Decimal("0.5")) == 0


def test_fee_cheap_contracts_cost_less() -> None:
    assert trading_fee_cents(100, Decimal("0.05")) < trading_fee_cents(100, Decimal("0.5"))


def test_fee_per_contract_dollars_unrounded() -> None:
    assert fee_per_contract_dollars(Decimal("0.5")) == Decimal("0.0175")
