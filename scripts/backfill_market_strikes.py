"""Backfill reference_market strike columns from stored raw_jsonb.

Usage: DATABASE_URL_SHARED=postgresql://... python scripts/backfill_market_strikes.py
Idempotent: only touches rows where strike_type IS NULL.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db.shared_models import ReferenceMarketRow  # noqa: E402
from core.sources.kalshi.parse import _parse_strike  # noqa: E402


def main() -> int:
    url = os.environ.get("DATABASE_URL_SHARED")
    if not url:
        print("DATABASE_URL_SHARED is required", file=sys.stderr)
        return 1
    engine = create_engine(url)
    updated = 0
    with Session(engine) as session:
        rows = session.scalars(
            select(ReferenceMarketRow).where(ReferenceMarketRow.strike_type.is_(None))
        ).all()
        for row in rows:
            payload = row.raw_jsonb or {}
            if not payload.get("strike_type"):
                continue
            row.strike_type = str(payload["strike_type"])
            row.floor_strike = _parse_strike(payload.get("floor_strike"))
            row.cap_strike = _parse_strike(payload.get("cap_strike"))
            updated += 1
        session.commit()
    print(f"backfilled {updated} markets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
