"""Verify bracket_satisfied() against actual Kalshi resolutions.

For every resolved weather market with strike metadata, compare
bracket_satisfied(observed_value) to the recorded YES/NO resolution.

Note: ContractResolutionRow.settlement_value stores the contract payout
(0/1), NOT the observed temperature. The observed value lives in
resolution.source_evidence_jsonb["expiration_value"] (a numeric string),
and is empty/absent for older ingests — those rows are skipped.

Usage: DATABASE_URL_SHARED=postgresql://... python scripts/verify_bracket_semantics.py
Exit code 0 = all match; 1 = mismatches found or nothing to check.
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal, InvalidOperation

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow  # noqa: E402
from core.domain.weather_markets import (  # noqa: E402
    bracket_satisfied,
    plausible_temperature_strike,
    weather_series,
)


def main() -> int:
    url = os.environ.get("DATABASE_URL_SHARED")
    if not url:
        print("DATABASE_URL_SHARED is required", file=sys.stderr)
        return 1
    engine = create_engine(url)
    checked = 0
    skipped = 0
    mismatches: list[str] = []
    with Session(engine) as session:
        rows = session.execute(
            select(ContractResolutionRow, ReferenceMarketRow).join(
                ReferenceMarketRow,
                ReferenceMarketRow.ticker == ContractResolutionRow.ticker,
            )
        ).all()
        for resolution, market in rows:
            if not weather_series(market.series):
                continue
            if market.strike_type is None:
                skipped += 1
                continue
            if not plausible_temperature_strike(
                market.floor_strike
            ) or not plausible_temperature_strike(market.cap_strike):
                skipped += 1
                continue
            raw_observed = resolution.source_evidence_jsonb.get("expiration_value")
            if not raw_observed:
                skipped += 1
                continue
            try:
                observed_value = Decimal(str(raw_observed))
            except InvalidOperation:
                skipped += 1
                continue
            predicted = bracket_satisfied(
                observed_value,
                strike_type=market.strike_type,
                floor_strike=market.floor_strike,
                cap_strike=market.cap_strike,
            )
            if predicted is None:
                skipped += 1
                continue
            if resolution.resolution.value == "void":
                skipped += 1
                continue
            actual_yes = resolution.resolution.value == "yes"
            checked += 1
            if predicted is not actual_yes:
                mismatches.append(
                    f"{market.ticker}: observed={observed_value} "
                    f"strike_type={market.strike_type} floor={market.floor_strike} "
                    f"cap={market.cap_strike} predicted={'yes' if predicted else 'no'} "
                    f"actual={resolution.resolution.value}"
                )
    print(f"checked={checked} skipped={skipped} mismatches={len(mismatches)}")
    for line in mismatches:
        print(f"MISMATCH {line}")
    if checked == 0:
        print("nothing checked — run backfill_market_strikes.py first?", file=sys.stderr)
        return 1
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
