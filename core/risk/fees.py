"""Kalshi trading-fee model.

General fee schedule: fees = ceil_to_cent(rate * contracts * P * (1 - P)),
rate 0.07 as of 2026. Rate is a parameter so schedule changes are one-line.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

DEFAULT_FEE_RATE = Decimal("0.07")


def fee_per_contract_dollars(price: Decimal, *, rate: Decimal = DEFAULT_FEE_RATE) -> Decimal:
    return rate * price * (Decimal("1") - price)


def trading_fee_cents(qty: int, price: Decimal, *, rate: Decimal = DEFAULT_FEE_RATE) -> int:
    if qty <= 0:
        return 0
    fee_dollars = fee_per_contract_dollars(price, rate=rate) * qty
    return int((fee_dollars * Decimal("100")).to_integral_value(rounding=ROUND_CEILING))
