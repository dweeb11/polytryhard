# M8 — Strategy Correctness & Honest Accounting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `prob_yes` a real probability (strike-aware, ensemble-derived) and make paper P&L honest (fees, no duplicate entries, enforced drawdown pause), so eval metrics measure something meaningful.

**Architecture:** Add strike metadata to `reference_market` (from the Kalshi payload we already store), introduce a market-scoped `weather_model_prob` feature provider that computes P(daily-high satisfies the market bracket) from ensemble member daily maxes, rewrite both strategies on top of it, and tighten `core/risk` (Kelly denominator, Kalshi fee model, per-ticker dedupe, per-strategy exposure cap) plus automatic drawdown pause in the tick.

**Tech Stack:** Python 3.11, SQLAlchemy 2, Alembic (dual-tree: `migrations/shared/`, `migrations/per_env/`), Pydantic v2, pytest (SQLite fixtures via `tests/conftest.py`).

## Global Constraints

- Feature branch from `staging`; PRs target `staging`. One concern per PR, < ~300 lines. Branch naming `feat/<linear-id>-<slug>` (get the Linear ID per task, or use `feat/m8-<slug>` if no Linear issue exists).
- **PR review: CodeRabbit only — do not invoke Codex review on polytryhard PRs.**
- Full gate before every commit that claims green: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q` (run from repo root).
- Strategies stay pure: no I/O, no clock, no randomness. The AST purity guard (`tests/test_strategy_purity_guard.py`) must stay green.
- All bankroll mutations go through `core/ledger/writer.py`. Ledger purity guard (`tests/test_ledger_purity_guard.py`) must stay green.
- Shared migrations are **additive only**. Never remove fields from Pydantic API schemas (`core/api/v1/schemas.py`, `core/domain/strategy.py` — `StrategyConfig` fields are API contract).
- All timestamps UTC (`core/utils/time.py`); local-day logic must convert explicitly via `zoneinfo`.
- Fail closed: missing strike metadata, missing ensemble members, unknown strike type → feature `MISSING`, no signal.
- Co-author line on AI-assisted commits: `Co-Authored-By: Claude <noreply@anthropic.com>`.

## Task map (one PR each)

| # | Linear | Task | Layer |
|---|--------|------|-------|
| 1 | APP-376 | Strike metadata: shared migration 005 + parse + persistence + backfill script | Schema/ingestion |
| 2 | APP-377 | `core/domain/weather_markets.py`: target-date parser + bracket predicate + smoothed probability | Domain (pure) |
| 3 | APP-382 | Empirical bracket-semantics verification script (evidence gate) | Script |
| 4 | APP-379 | Daily-high member query + `weather_model_prob` feature provider | Features |
| 5 | APP-378 | Kalshi fee model in `core/risk/fees.py` | Risk (pure) |
| 6 | APP-380 | Sizing fixes: fee-aware edge, Kelly denominator, per-ticker dedupe, per-strategy exposure cap | Risk |
| 7 | APP-383 | Rewrite both strategies on `weather_model_prob`; new config knobs; remove fake temp↔prob mapping | Strategies |
| 8 | APP-381 | Automatic drawdown pause in engine tick | Ledger/engine |

Tasks 2, 3, 5 are independent of each other. Task 4 needs 1+2. Task 6 needs 5. Task 7 needs 4+6. Task 8 is independent (can run any time).

---

### Task 1: Strike metadata on `reference_market`

Kalshi market payloads already carry `strike_type`, `floor_strike`, `cap_strike` and we store the full payload in `raw_jsonb` — we just never lifted the fields out. Lift them into real columns so `MarketState` can carry them.

**Files:**
- Create: `migrations/shared/versions/005_market_strikes.py`
- Modify: `core/db/shared_models.py` (`ReferenceMarketRow`)
- Modify: `core/contracts/source.py` (`ReferenceMarketUpsert`)
- Modify: `core/sources/kalshi/parse.py` (`parse_market`)
- Modify: `core/sources/persistence.py` (`persist_fetch_result`, `load_markets`)
- Modify: `core/domain/market.py` (`MarketState`)
- Modify: `core/engine/markets.py` (`build_market_states`)
- Create: `scripts/backfill_market_strikes.py`
- Test: `tests/test_kalshi_parse.py` (extend), `tests/test_source_persistence.py` (extend), `tests/test_engine_markets.py` (extend)

**Interfaces:**
- Consumes: existing `parse_market(payload) -> ReferenceMarketUpsert | None`.
- Produces: `ReferenceMarketUpsert.strike_type: str | None`, `.floor_strike: Decimal | None`, `.cap_strike: Decimal | None`; same three fields on `ReferenceMarketRow` and `MarketState`. Task 4 reads them off `ReferenceMarketRow`; Task 7 reads `MarketState` untouched (strategies don't need strikes directly — the feature provider does).

- [ ] **Step 1: Write the failing parse test** — append to `tests/test_kalshi_parse.py`:

```python
def test_parse_market_extracts_strike_fields() -> None:
    payload = {
        "ticker": "KXHIGHNY-25MAY28-B72.5",
        "series_ticker": "KXHIGHNY",
        "title": "High temp in NYC on May 28",
        "status": "active",
        "strike_type": "between",
        "floor_strike": 72,
        "cap_strike": 73,
    }
    upsert = parse_market(payload)
    assert upsert is not None
    assert upsert.strike_type == "between"
    assert upsert.floor_strike == Decimal("72")
    assert upsert.cap_strike == Decimal("73")


def test_parse_market_strike_fields_default_none() -> None:
    upsert = parse_market({"ticker": "KXHIGHNY-25MAY28-T72", "status": "active"})
    assert upsert is not None
    assert upsert.strike_type is None
    assert upsert.floor_strike is None
    assert upsert.cap_strike is None
```

(Add `from decimal import Decimal` to the test file imports if not present.)

- [ ] **Step 2: Run to verify failure**

Run: `REQUIRE_DBS=0 pytest tests/test_kalshi_parse.py -v -k strike`
Expected: FAIL — `TypeError: ... unexpected keyword` or `AttributeError: 'ReferenceMarketUpsert' object has no attribute 'strike_type'`

- [ ] **Step 3: Add fields to the DTO** — in `core/contracts/source.py`, extend `ReferenceMarketUpsert` (keep field order: new optionals go before `raw_jsonb`):

```python
@dataclass(frozen=True)
class ReferenceMarketUpsert:
    ticker: str
    series: str
    title: str
    status: str
    settlement_source: str | None = None
    settlement_ref: str | None = None
    open_time: datetime | None = None
    close_time: datetime | None = None
    settlement_time: datetime | None = None
    strike_type: str | None = None
    floor_strike: Decimal | None = None
    cap_strike: Decimal | None = None
    raw_jsonb: dict[str, object] = field(default_factory=dict)
```

- [ ] **Step 4: Extract in `parse_market`** — in `core/sources/kalshi/parse.py`, add a helper and pass the fields:

```python
def _parse_strike(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value))
        except ArithmeticError:
            return None
    return None
```

and inside `parse_market`'s return:

```python
        strike_type=str(payload["strike_type"]) if payload.get("strike_type") else None,
        floor_strike=_parse_strike(payload.get("floor_strike")),
        cap_strike=_parse_strike(payload.get("cap_strike")),
```

- [ ] **Step 5: Run parse tests**

Run: `REQUIRE_DBS=0 pytest tests/test_kalshi_parse.py -v`
Expected: PASS

- [ ] **Step 6: Model + migration.** In `core/db/shared_models.py`, add to `ReferenceMarketRow` after `status`:

```python
    strike_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    floor_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    cap_strike: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
```

Create `migrations/shared/versions/005_market_strikes.py` (additive only):

```python
"""reference_market strike metadata

Revision ID: 005_market_strikes
Revises: 004_contract_resolution
Create Date: 2026-07-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005_market_strikes"
down_revision: str | None = "004_contract_resolution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reference_market", sa.Column("strike_type", sa.String(32), nullable=True))
    op.add_column("reference_market", sa.Column("floor_strike", sa.Numeric(12, 6), nullable=True))
    op.add_column("reference_market", sa.Column("cap_strike", sa.Numeric(12, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("reference_market", "cap_strike")
    op.drop_column("reference_market", "floor_strike")
    op.drop_column("reference_market", "strike_type")
```

- [ ] **Step 7: Persistence write-and-load.** In `core/sources/persistence.py`:
  - `persist_fetch_result`: in the insert branch add `strike_type=upsert.strike_type, floor_strike=upsert.floor_strike, cap_strike=upsert.cap_strike,`; in the update branch add `existing.strike_type = upsert.strike_type`, `existing.floor_strike = upsert.floor_strike`, `existing.cap_strike = upsert.cap_strike`.
  - `load_markets`: pass the three fields through to `ReferenceMarketUpsert`.

  Add a round-trip assertion to the existing upsert test in `tests/test_source_persistence.py` — extend whichever test persists a `ReferenceMarketUpsert` to build it with `strike_type="between", floor_strike=Decimal("72"), cap_strike=Decimal("73")` and assert the row read back carries them.

- [ ] **Step 8: `MarketState` carries strikes.** In `core/domain/market.py` add to `MarketState`:

```python
    strike_type: str | None = None
    floor_strike: Decimal | None = None
    cap_strike: Decimal | None = None
```

and to `to_json()`:

```python
            "strikeType": self.strike_type,
            "floorStrike": float(self.floor_strike) if self.floor_strike is not None else None,
            "capStrike": float(self.cap_strike) if self.cap_strike is not None else None,
```

In `core/engine/markets.py` `build_market_states`, pass `strike_type=market.strike_type, floor_strike=market.floor_strike, cap_strike=market.cap_strike` into the `MarketState(...)` constructor. Extend an existing `tests/test_engine_markets.py` case: seed a `ReferenceMarketRow` with strikes and assert the built `MarketState` carries them.

- [ ] **Step 9: Backfill script.** Create `scripts/backfill_market_strikes.py` — one-off, reads `raw_jsonb` for rows with `strike_type IS NULL` and fills the columns:

```python
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
```

(Rename `_parse_strike` to `parse_strike` in `parse.py` if ruff flags the private import; update both call sites.)

- [ ] **Step 10: Full gate, run migration locally, commit**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
Expected: all green.
If a local Postgres is available: `./.venv/bin/alembic -c alembic.ini upgrade head` — expected: `005_market_strikes` applies cleanly.

```bash
git add migrations/shared/versions/005_market_strikes.py core/db/shared_models.py core/contracts/source.py core/sources/kalshi/parse.py core/sources/persistence.py core/domain/market.py core/engine/markets.py scripts/backfill_market_strikes.py tests/
git commit -m "feat: extract Kalshi strike metadata into reference_market and MarketState"
```

---

### Task 2: Pure bracket domain logic (`core/domain/weather_markets.py`)

The date parser, the bracket predicate, and the smoothed member probability. Pure functions — strategies and feature providers both import from here. Also becomes the new home of the series→location map so features stop importing from `core/strategies/`.

**Files:**
- Create: `core/domain/weather_markets.py`
- Modify: `core/strategies/weather_utils.py` (re-export from the new module; delete `ensemble_to_prob`/`prob_to_temp` in Task 7, not here)
- Test: `tests/test_weather_markets.py` (new)

**Interfaces:**
- Produces:
  - `target_local_date(ticker: str) -> date | None` — parses `KXHIGHNY-25MAY28-T72` → `date(2025, 5, 28)`.
  - `bracket_satisfied(value: Decimal, *, strike_type: str, floor_strike: Decimal | None, cap_strike: Decimal | None) -> bool | None` — `None` = unknown strike type (fail closed).
  - `bracket_probability(daily_maxes: Sequence[Decimal], *, strike_type: str, floor_strike: Decimal | None, cap_strike: Decimal | None) -> Decimal | None` — Laplace-smoothed `(hits + 1) / (n + 2)`; `None` if no members or unknown type.
  - `SERIES_TO_LOCATION`, `weather_series(series) -> bool`, `location_for_series(series) -> str | None` (moved here verbatim; `weather_utils` re-exports).

- [ ] **Step 1: Write the failing tests** — create `tests/test_weather_markets.py`:

```python
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
def test_bracket_greater_is_strictly_above_cap(value: Decimal, expected: bool) -> None:
    # ASSUMED Kalshi semantics — verified empirically by scripts/verify_bracket_semantics.py
    assert (
        bracket_satisfied(value, strike_type="greater", floor_strike=None, cap_strike=Decimal("73"))
        is expected
    )


def test_bracket_less_is_strictly_below_floor() -> None:
    assert (
        bracket_satisfied(
            Decimal("71"), strike_type="less", floor_strike=Decimal("72"), cap_strike=None
        )
        is True
    )
    assert (
        bracket_satisfied(
            Decimal("72"), strike_type="less", floor_strike=Decimal("72"), cap_strike=None
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
    # 2 of 4 above cap 73 -> (2 + 1) / (4 + 2) = 0.5
    prob = bracket_probability(
        maxes, strike_type="greater", floor_strike=None, cap_strike=Decimal("73")
    )
    assert prob == Decimal("3") / Decimal("6")


def test_bracket_probability_never_zero_or_one() -> None:
    maxes = [Decimal("90")] * 10
    prob = bracket_probability(
        maxes, strike_type="greater", floor_strike=None, cap_strike=Decimal("73")
    )
    assert prob is not None
    assert Decimal("0") < prob < Decimal("1")


def test_bracket_probability_empty_members_is_none() -> None:
    assert (
        bracket_probability([], strike_type="greater", floor_strike=None, cap_strike=Decimal("73"))
        is None
    )


def test_series_helpers_moved_here() -> None:
    assert weather_series("KXHIGHNY") is True
    assert location_for_series("KXHIGHCHI") == "chicago"
```

- [ ] **Step 2: Run to verify failure**

Run: `REQUIRE_DBS=0 pytest tests/test_weather_markets.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.domain.weather_markets'`

- [ ] **Step 3: Implement** — create `core/domain/weather_markets.py`:

```python
"""Pure domain logic for Kalshi weather bracket markets.

Bracket semantics (per Kalshi API docs, and verified empirically against
contract_resolution rows by scripts/verify_bracket_semantics.py):
  greater  -> value strictly greater than cap_strike
  less     -> value strictly less than floor_strike
  between  -> floor_strike <= value <= cap_strike (inclusive both ends)
Unknown strike types return None -> callers fail closed.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

WEATHER_SERIES_PATTERN = re.compile(r"^KXHIGH", re.IGNORECASE)

# Ticker like KXHIGHNY-25MAY28-T72 -> location slug nyc (Kalshi NY = NYC metro)
SERIES_TO_LOCATION: dict[str, str] = {
    "KXHIGHNY": "nyc",
    "KXHIGHCHI": "chicago",
    "KXHIGHLAX": "la",
    "KXHIGHMIA": "miami",
    "KXHIGHHOU": "houston",
    "KXHIGHAUS": "austin",
}

_DATE_SEGMENT = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})$")
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def weather_series(series: str) -> bool:
    return bool(WEATHER_SERIES_PATTERN.match(series))


def location_for_series(series: str) -> str | None:
    upper = series.upper()
    for prefix, location_id in SERIES_TO_LOCATION.items():
        if upper.startswith(prefix):
            return location_id
    return None


def target_local_date(ticker: str) -> date | None:
    parts = ticker.upper().split("-")
    if len(parts) < 2:
        return None
    match = _DATE_SEGMENT.match(parts[1])
    if match is None:
        return None
    yy, mon, dd = match.groups()
    month = _MONTHS.get(mon)
    if month is None:
        return None
    try:
        return date(2000 + int(yy), month, int(dd))
    except ValueError:
        return None


def bracket_satisfied(
    value: Decimal,
    *,
    strike_type: str,
    floor_strike: Decimal | None,
    cap_strike: Decimal | None,
) -> bool | None:
    kind = strike_type.lower()
    if kind == "greater":
        if cap_strike is None:
            return None
        return value > cap_strike
    if kind == "less":
        if floor_strike is None:
            return None
        return value < floor_strike
    if kind == "between":
        if floor_strike is None or cap_strike is None:
            return None
        return floor_strike <= value <= cap_strike
    return None


def bracket_probability(
    daily_maxes: Sequence[Decimal],
    *,
    strike_type: str,
    floor_strike: Decimal | None,
    cap_strike: Decimal | None,
) -> Decimal | None:
    if not daily_maxes:
        return None
    hits = 0
    for value in daily_maxes:
        satisfied = bracket_satisfied(
            value, strike_type=strike_type, floor_strike=floor_strike, cap_strike=cap_strike
        )
        if satisfied is None:
            return None
        if satisfied:
            hits += 1
    n = len(daily_maxes)
    return (Decimal(hits) + Decimal(1)) / (Decimal(n) + Decimal(2))
```

- [ ] **Step 4: Re-export from `weather_utils`.** In `core/strategies/weather_utils.py`, replace the local definitions of `WEATHER_SERIES_PATTERN`, `SERIES_TO_LOCATION`, `weather_series`, `location_for_series` with:

```python
from core.domain.weather_markets import (  # noqa: F401  (re-export for existing imports)
    SERIES_TO_LOCATION,
    WEATHER_SERIES_PATTERN,
    location_for_series,
    weather_series,
)
```

Keep `scoped_features`, `numeric_feature`, `ensemble_to_prob`, `prob_to_temp` untouched for now (Task 7 deletes the last two). `core/engine/markets.py` and `core/risk/sizing.py` keep working via the re-export; optionally repoint their imports to `core.domain.weather_markets` in this PR.

- [ ] **Step 5: Run tests + full gate**

Run: `REQUIRE_DBS=0 pytest tests/test_weather_markets.py tests/test_weather_strategies.py tests/test_engine_markets.py -v`, then the full gate.
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add core/domain/weather_markets.py core/strategies/weather_utils.py tests/test_weather_markets.py
git commit -m "feat: pure bracket domain logic (target date, predicate, smoothed probability)"
```

---

### Task 3: Empirical bracket-semantics verification (evidence gate)

The predicate in Task 2 encodes *assumed* Kalshi semantics. Before any strategy trades on it, verify against ground truth we already ingest: `contract_resolution` rows carry the observed `settlement_value` and the actual YES/NO resolution.

**Files:**
- Create: `scripts/verify_bracket_semantics.py`

**Interfaces:**
- Consumes: `bracket_satisfied` from Task 2; `ReferenceMarketRow` strike columns from Task 1.
- Produces: a console report. **Definition of done for this task: run the script against the staging shared DB and paste the output into the PR description. Mismatch rate must be 0% on markets with strike metadata; any mismatch means the predicate mapping in Task 2 is wrong and must be fixed before Task 7 ships.**

- [ ] **Step 1: Write the script**

```python
"""Verify bracket_satisfied() against actual Kalshi resolutions.

For every resolved weather market with strike metadata, compare
bracket_satisfied(settlement_value) to the recorded YES/NO resolution.

Usage: DATABASE_URL_SHARED=postgresql://... python scripts/verify_bracket_semantics.py
Exit code 0 = all match; 1 = mismatches found or nothing to check.
"""

from __future__ import annotations

import os
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow  # noqa: E402
from core.domain.weather_markets import bracket_satisfied, weather_series  # noqa: E402


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
            predicted = bracket_satisfied(
                resolution.settlement_value,
                strike_type=market.strike_type,
                floor_strike=market.floor_strike,
                cap_strike=market.cap_strike,
            )
            if predicted is None:
                skipped += 1
                continue
            actual_yes = resolution.resolution.value == "yes"
            checked += 1
            if predicted is not actual_yes:
                mismatches.append(
                    f"{market.ticker}: settlement={resolution.settlement_value} "
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
```

- [ ] **Step 2: Lint gate**

Run: `./.venv/bin/ruff check scripts/verify_bracket_semantics.py && ./.venv/bin/mypy core`
Expected: clean.

- [ ] **Step 3: Run against staging shared DB (evidence)**

Run: `DATABASE_URL_SHARED=<staging url> ./.venv/bin/python scripts/backfill_market_strikes.py && DATABASE_URL_SHARED=<staging url> ./.venv/bin/python scripts/verify_bracket_semantics.py`
Expected: `checked=<N> skipped=<M> mismatches=0`, exit 0. **If mismatches > 0: stop, fix the mapping in `core/domain/weather_markets.py` (and its unit tests) until this reports 0, before proceeding to Task 4.**

- [ ] **Step 4: Commit**

```bash
git add scripts/verify_bracket_semantics.py
git commit -m "feat: empirical verification of bracket semantics against recorded resolutions"
```

---

### Task 4: Daily-high member query + `weather_model_prob` feature provider

Replaces the broken pipeline (`ensemble mean at one hour` → `linear temp→prob`) with: per ensemble member, max temperature over the market's **local** target day → fraction of members satisfying the market's bracket → smoothed probability. Emitted as a **market-scoped** feature (`subject_id = ticker`), so it flows through `strategy_features_for_market` untouched and `_stale_feature` in sizing already covers it.

**Files:**
- Modify: `core/features/queries.py` (new query `daily_max_by_member`)
- Create: `core/features/weather_model_prob/__init__.py`, `core/features/weather_model_prob/provider.py`
- Modify: `core/features/registry.py` (register)
- Test: `tests/test_features.py` (extend) or new `tests/test_feature_weather_model_prob.py`

**Interfaces:**
- Consumes: `ReferenceMarketRow.strike_type/floor_strike/cap_strike` (Task 1); `target_local_date`, `location_for_series`, `bracket_probability` (Task 2); existing `list_open_markets`, `list_locations`.
- Produces:
  - `daily_max_by_member(session, *, location_id: str, source: ForecastSource, variable: str, as_of: datetime, day_start_utc: datetime, day_end_utc: datetime) -> dict[int | None, Decimal]` — latest run ≤ `as_of`; among that run's rows with `day_start_utc <= valid_window_start < day_end_utc`, max value per `ensemble_member`. Empty dict when no run/rows.
  - Feature `weather_model_prob` v1: `subject_kind=MARKET`, `subject_id=<ticker>`, `value_numeric = P(bracket satisfied)`, `value_jsonb = {"nMembers": int, "gfsMembers": int, "ecmwfMembers": int, "gfsMeanMax": float | None, "ecmwfMeanMax": float | None}`. `MISSING` (with reason) when: series has no location, ticker has no parsable date, market lacks strike metadata, location has no timezone row, or no members found. Task 7 consumes this by provider name.

- [ ] **Step 1: Write the failing query test.** Follow the existing seeding helpers/patterns in `tests/test_features.py` (it already seeds `RawForecastRunRow`s against the SQLite fixtures — reuse its fixtures and helper functions; if it has a `_forecast_row`-style helper, use it). New test, semantics to lock:

```python
def test_daily_max_by_member_takes_max_per_member_within_window(shared_session) -> None:
    # seed one run (run_time=2025-05-28T00:00Z) for location "nyc", GFS, temperature_2m:
    #   member 0: values 70, 74, 72 at 10:00Z, 18:00Z, 20:00Z
    #   member 1: values 71, 69       at 18:00Z, 20:00Z
    #   member 0 extra row at 2025-05-29T02:00Z (outside window) with value 99
    # window: day_start=2025-05-28T04:00Z (midnight ET), day_end=2025-05-29T04:00Z... but the
    # 29T02:00Z row IS inside that window — use day_end=2025-05-29T00:00Z here to prove exclusion.
    result = daily_max_by_member(
        shared_session,
        location_id="nyc",
        source=ForecastSource.GFS,
        variable=TEMPERATURE_VARIABLE,
        as_of=datetime(2025, 5, 28, 12, tzinfo=UTC),
        day_start_utc=datetime(2025, 5, 28, 0, tzinfo=UTC),
        day_end_utc=datetime(2025, 5, 29, 0, tzinfo=UTC),
    )
    assert result == {0: Decimal("74"), 1: Decimal("71")}
```

Also lock: a second, *newer* run supersedes the older one (only the latest run's rows count), and an empty dict when there is no run ≤ `as_of`.

- [ ] **Step 2: Run to verify failure**

Run: `REQUIRE_DBS=0 pytest tests/test_feature_weather_model_prob.py -v`
Expected: FAIL — `ImportError: cannot import name 'daily_max_by_member'`

- [ ] **Step 3: Implement the query** — append to `core/features/queries.py`:

```python
def daily_max_by_member(
    session: Session,
    *,
    location_id: str,
    source: ForecastSource,
    variable: str,
    as_of: datetime,
    day_start_utc: datetime,
    day_end_utc: datetime,
) -> dict[int | None, Decimal]:
    """Per-ensemble-member max value over [day_start_utc, day_end_utc) from the latest run."""
    latest_run = session.scalar(
        select(func.max(RawForecastRunRow.run_time)).where(
            RawForecastRunRow.location_id == location_id,
            RawForecastRunRow.source == source,
            RawForecastRunRow.variable == variable,
            RawForecastRunRow.run_time <= as_of,
        )
    )
    if latest_run is None:
        return {}
    rows = session.scalars(
        select(RawForecastRunRow).where(
            RawForecastRunRow.location_id == location_id,
            RawForecastRunRow.source == source,
            RawForecastRunRow.variable == variable,
            RawForecastRunRow.run_time == latest_run,
        )
    ).all()
    maxes: dict[int | None, Decimal] = {}
    for row in rows:
        window = _as_utc(row.valid_window_start)
        if not (day_start_utc <= window < day_end_utc):
            continue
        current = maxes.get(row.ensemble_member)
        if current is None or row.value > current:
            maxes[row.ensemble_member] = row.value
    return maxes
```

- [ ] **Step 4: Run query tests** — expected PASS.

- [ ] **Step 5: Write the failing provider test.** Seed: a `ReferenceLocationRow` (`id="nyc"`, `timezone="America/New_York"`), an open `ReferenceMarketRow` (`ticker="KXHIGHNY-25MAY28-T73"`, `series="KXHIGHNY"`, `strike_type="greater"`, `cap_strike=Decimal("73")`), and GFS+ECMWF member rows for the NYC local day 2025-05-28 (local midnight = 04:00 UTC in May). Assertions:

```python
async def test_weather_model_prob_present(shared_session) -> None:
    # 4 pooled members (2 GFS + 2 ECMWF), daily maxes 74, 75, 71, 70 vs "greater than 73"
    provider = WeatherModelProbProvider()
    ctx = FeatureContext(request_id="t", settings=make_settings(), session=shared_session)
    values = await provider.compute(datetime(2025, 5, 28, 12, tzinfo=UTC), ctx)
    by_subject = {v.subject_id: v for v in values}
    fv = by_subject["KXHIGHNY-25MAY28-T73"]
    assert fv.status == FeatureStatus.PRESENT
    assert fv.value_numeric == (Decimal(2) + 1) / (Decimal(4) + 2)  # laplace(2/4)
    assert fv.value_jsonb["nMembers"] == 4


async def test_weather_model_prob_missing_without_strikes(shared_session) -> None:
    # market with strike_type=None -> MISSING with reason "no strike metadata"
    ...  # same shape: seed market without strikes, assert FeatureStatus.MISSING and the reason
```

(Match the async test convention already used in `tests/test_features.py` — it tests async `compute` today; reuse its pattern exactly, including how `Settings` is constructed.)

- [ ] **Step 6: Implement the provider** — `core/features/weather_model_prob/provider.py`:

```python
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from core.contracts.feature import FeatureContext, FeatureProvider
from core.db.shared_enums import FeatureSubjectKind, ForecastSource
from core.domain.feature import FeatureValue
from core.domain.weather_markets import (
    bracket_probability,
    location_for_series,
    target_local_date,
    weather_series,
)
from core.features.queries import (
    TEMPERATURE_VARIABLE,
    daily_max_by_member,
    list_locations,
    list_open_markets,
)
from core.settings import Settings


class WeatherModelProbProvider(FeatureProvider):
    """P(market bracket satisfied) from pooled GFS+ECMWF ensemble daily maxes."""

    @property
    def name(self) -> str:
        return "weather_model_prob"

    @property
    def version(self) -> str:
        return "1"

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def compute(self, as_of: datetime, ctx: FeatureContext) -> list[FeatureValue]:
        results: list[FeatureValue] = []
        subject_kind = FeatureSubjectKind.MARKET.value
        locations = {loc.id: loc for loc in list_locations(ctx.session)}

        def missing(ticker: str, reason: str) -> FeatureValue:
            return FeatureValue.missing(
                provider_name=self.name,
                provider_version=self.version,
                subject_kind=subject_kind,
                subject_id=ticker,
                reason=reason,
            )

        for market in list_open_markets(ctx.session, as_of=as_of):
            if not weather_series(market.series):
                continue
            location_id = location_for_series(market.series)
            if location_id is None or location_id not in locations:
                results.append(missing(market.ticker, "unknown location"))
                continue
            if market.strike_type is None:
                results.append(missing(market.ticker, "no strike metadata"))
                continue
            target_day = target_local_date(market.ticker)
            if target_day is None:
                results.append(missing(market.ticker, "unparsable target date"))
                continue
            tz = ZoneInfo(locations[location_id].timezone)
            day_start = datetime.combine(target_day, time.min, tzinfo=tz)
            day_start_utc = day_start.astimezone(ZoneInfo("UTC"))
            day_end_utc = (day_start + timedelta(days=1)).astimezone(ZoneInfo("UTC"))

            per_source: dict[ForecastSource, list] = {}
            for source in (ForecastSource.GFS, ForecastSource.ECMWF):
                maxes = daily_max_by_member(
                    ctx.session,
                    location_id=location_id,
                    source=source,
                    variable=TEMPERATURE_VARIABLE,
                    as_of=as_of,
                    day_start_utc=day_start_utc,
                    day_end_utc=day_end_utc,
                )
                per_source[source] = list(maxes.values())
            pooled = per_source[ForecastSource.GFS] + per_source[ForecastSource.ECMWF]
            prob = bracket_probability(
                pooled,
                strike_type=market.strike_type,
                floor_strike=market.floor_strike,
                cap_strike=market.cap_strike,
            )
            if prob is None:
                results.append(missing(market.ticker, "no ensemble members for target day"))
                continue

            def _mean(values: list) -> float | None:
                return float(sum(values) / len(values)) if values else None

            results.append(
                FeatureValue.present(
                    provider_name=self.name,
                    provider_version=self.version,
                    subject_kind=subject_kind,
                    subject_id=market.ticker,
                    as_of=as_of,
                    value_numeric=prob,
                    value_jsonb={
                        "nMembers": len(pooled),
                        "gfsMembers": len(per_source[ForecastSource.GFS]),
                        "ecmwfMembers": len(per_source[ForecastSource.ECMWF]),
                        "gfsMeanMax": _mean(per_source[ForecastSource.GFS]),
                        "ecmwfMeanMax": _mean(per_source[ForecastSource.ECMWF]),
                    },
                )
            )
        return results
```

`__init__.py`:

```python
from core.features.weather_model_prob.provider import WeatherModelProbProvider

__all__ = ["WeatherModelProbProvider"]
```

Note on `as_of`: other providers stamp the feature with the forecast run time; here the probability depends on the run **and** the market row, so stamping with the tick's `as_of` is correct and keeps the sizing freshness gate meaningful. If review prefers run-time stamping, use `max(latest run times)` — decide in PR, don't block.

- [ ] **Step 7: Register.** In `core/features/registry.py` add `WeatherModelProbProvider()` to `_ALL_PROVIDERS` (import at top).

- [ ] **Step 8: Run provider tests + full gate** — expected PASS.

- [ ] **Step 9: Commit**

```bash
git add core/features/queries.py core/features/weather_model_prob/ core/features/registry.py tests/test_feature_weather_model_prob.py
git commit -m "feat: weather_model_prob feature — strike-aware ensemble probability per market"
```

---

### Task 5: Kalshi trading-fee model

Kalshi's general fee schedule: `fees = ceil_to_cent(0.07 × contracts × price × (1 − price))`. At 50¢ that's 1.75¢/contract — big enough to erase most weather edges, so paper trading without it overstates every strategy.

**Files:**
- Create: `core/risk/fees.py`
- Test: `tests/test_risk_fees.py` (new)

**Interfaces:**
- Produces: `trading_fee_cents(qty: int, price: Decimal, *, rate: Decimal = Decimal("0.07")) -> int` and `fee_per_contract_dollars(price: Decimal, *, rate: Decimal = Decimal("0.07")) -> Decimal` (un-rounded, for edge math). Task 6 consumes both.

- [ ] **Step 1: Failing tests** — `tests/test_risk_fees.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure** — `REQUIRE_DBS=0 pytest tests/test_risk_fees.py -v` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement** — `core/risk/fees.py`:

```python
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
```

- [ ] **Step 4: Run tests + full gate** — expected PASS.

- [ ] **Step 5: Commit**

```bash
git add core/risk/fees.py tests/test_risk_fees.py
git commit -m "feat: Kalshi trading-fee model"
```

---

### Task 6: Sizing fixes — fee-aware edge, true Kelly, per-ticker dedupe, per-strategy exposure cap

Four defects in `core/risk/sizing.py` + wiring fees through the tick:

1. Edge ignores fees → require `edge − fee_per_contract > 0`.
2. `kelly = fraction × confidence × edge` omits the `/(1 − price)` denominator of binary Kelly.
3. Nothing stops re-entering a ticker the strategy already holds → new rejection.
4. Exposure cap compares *this strategy's* positions against *total* bankroll → N strategies can each take 50% of the pot. Cap against the strategy's own bankroll.

**Files:**
- Modify: `core/domain/enums.py` (`SignalOutcome`)
- Modify: `core/domain/trading.py` (`Order.fees_cents`)
- Modify: `core/risk/sizing.py`
- Modify: `core/engine/tick.py` (pass `order.fees_cents` to `ExecutorContext`; drop `total_bankroll_cents`)
- Modify: `core/engine/markets.py` (delete `total_bankroll_cents` if now unused)
- Test: `tests/test_risk_sizing.py` (extend), `tests/test_engine_tick.py` (extend)

**Interfaces:**
- Consumes: `fee_per_contract_dollars`, `trading_fee_cents` (Task 5).
- Produces: `SignalOutcome.REJECTED_ALREADY_POSITIONED = "rejected_already_positioned"`; `Order` gains `fees_cents: int = 0`; `SizingInput` loses `total_bankroll_cents`. (Enum columns use `native_enum=False` → plain VARCHAR, so the new outcome value needs **no migration**. Check `core/api/v1/schemas.py` / UI types: `SignalOutcome` appears in OpenAPI — regenerate via `REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export ./.venv/bin/python scripts/export_openapi.py` then `npm run regen-api-types` in `ui/`.)

- [ ] **Step 1: Failing tests** — extend `tests/test_risk_sizing.py`, following its existing builder/fixture style for `SizingInput` (it already constructs strategy rows, markets, and signals — reuse those helpers; drop `total_bankroll_cents` from them). New cases to lock:

```python
def test_rejects_when_already_positioned_in_ticker() -> None:
    # open_positions contains an OPEN PaperPositionRow with the signal's ticker
    # -> Rejection(SignalOutcome.REJECTED_ALREADY_POSITIONED)


def test_rejects_when_edge_does_not_clear_fee() -> None:
    # prob_yes = 0.52, ask_yes = 0.50 -> raw edge 0.02, fee at 0.5 = 0.0175 -> net 0.0025 ok;
    # prob_yes = 0.51 -> net edge negative -> Rejection(REJECTED_KELLY_ZERO, "edge below fees")


def test_kelly_uses_binary_denominator() -> None:
    # price 0.5, net edge e, confidence c, fraction f:
    # stake = bankroll * f * c * e / (1 - 0.5)  -> twice the stake of the old formula
    # assert qty matches the new formula exactly


def test_exposure_cap_uses_strategy_bankroll() -> None:
    # strategy bankroll 10_000 cents, cap 0.5, open cost 4_000, new order 1_500
    # -> 5_500 > 5_000 -> Rejection(REJECTED_EXPOSURE_CAP)


def test_order_carries_fees_cents() -> None:
    # accepted order has fees_cents == trading_fee_cents(qty, price)
```

Write them as real tests against the existing helpers (each is ~10 lines once the builders are reused).

- [ ] **Step 2: Run to verify failure** — `REQUIRE_DBS=0 pytest tests/test_risk_sizing.py -v` → new tests FAIL.

- [ ] **Step 3: Implement.**

`core/domain/enums.py` — add to `SignalOutcome`:

```python
    REJECTED_ALREADY_POSITIONED = "rejected_already_positioned"
```

`core/domain/trading.py` — add to `Order`:

```python
    fees_cents: int = 0
```

`core/risk/sizing.py` — the changed portions:

```python
from core.risk.fees import fee_per_contract_dollars, trading_fee_cents
```

Remove `total_bankroll_cents` from `SizingInput`. In `size_order`, after the system-paused check add:

```python
    for pos in input_data.open_positions:
        if pos.status == PositionStatus.OPEN and pos.ticker == input_data.signal.ticker:
            return Rejection(
                SignalOutcome.REJECTED_ALREADY_POSITIONED,
                "already positioned in ticker",
            )
```

Replace the edge/Kelly block:

```python
    edge = _edge(input_data.signal, price)
    net_edge = edge - fee_per_contract_dollars(price)
    if net_edge <= 0:
        return Rejection(SignalOutcome.REJECTED_KELLY_ZERO, "edge below fees")

    # Binary Kelly: f* = (q - p) / (1 - p), scaled by fraction and confidence.
    kelly = (
        float(input_data.strategy.kelly_fraction)
        * float(input_data.signal.confidence)
        * float(net_edge / (Decimal("1") - price))
    )
```

After the final `cost_basis_cents` recompute, account for fees in free cash and attach them:

```python
    fees_cents = trading_fee_cents(qty, price)
    if cost_basis_cents + fees_cents > input_data.free_cash_cents:
        return Rejection(SignalOutcome.REJECTED_BELOW_MIN_POSITION, "insufficient free cash")
```

and return `Order(..., fees_cents=fees_cents)`.

`_exposure_cap_exceeded` — replace the cap line:

```python
    cap = int(input_data.strategy.bankroll_cents * cap_pct)
```

and drop the `total_bankroll_cents` field access.

`core/engine/tick.py` — remove the `total_bankroll_cents` import/call and the `SizingInput` argument; pass fees to the executor:

```python
            await executor.place(
                sizing,
                ExecutorContext(
                    request_id=tick_id,
                    session=per_env_session,
                    strategy_name=row.name,
                    signal_id=signal_row.id,
                    fees_cents=sizing.fees_cents,
                ),
            )
```

`core/engine/markets.py` — delete `total_bankroll_cents` (grep first: `grep -rn total_bankroll_cents core tests` — remove remaining references).

- [ ] **Step 4: Run tests, regen API types, full gate**

Run: `REQUIRE_DBS=0 pytest tests/test_risk_sizing.py tests/test_engine_tick.py -v`, then
`REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export ./.venv/bin/python scripts/export_openapi.py`, then in `ui/`: `npm run regen-api-types && npm run check && npm run lint && npm run test && npm run build`, then the backend full gate.
Expected: all green; `ui/src/lib/api/types.ts` diff shows only the new enum value.

- [ ] **Step 5: Commit**

```bash
git add core/domain/enums.py core/domain/trading.py core/risk/sizing.py core/engine/tick.py core/engine/markets.py tests/ ui/src/lib/api/types.ts
git commit -m "fix: fee-aware Kelly sizing, per-ticker dedupe, per-strategy exposure cap"
```

---

### Task 7: Rewrite both strategies on `weather_model_prob`

Both strategies become honest value trades against a real probability. `weather_ensemble_disagreement` inverts its disagreement logic — high GFS/ECMWF disagreement now means *too uncertain, stand down* (uncertainty filter), instead of being the trigger. `weather_stale_quote` keeps its wide-spread trigger but must clear the edge at the actual crossing price (ask), not mid. The fake `ensemble_to_prob`/`prob_to_temp` mapping is deleted.

**Files:**
- Modify: `core/strategies/weather_ensemble_disagreement/strategy.py` (rewrite)
- Modify: `core/strategies/weather_stale_quote/strategy.py` (rewrite)
- Modify: `core/strategies/weather_utils.py` (delete `ensemble_to_prob`, `prob_to_temp`, `scoped_features` — the engine already scopes; keep `numeric_feature` + re-exports)
- Modify: `core/domain/strategy.py` (`StrategyConfig`: add `min_edge`, `max_disagreement_f`; keep the old fields — API contract — just stop using them)
- Modify: `core/ledger/seed.py` (seed new config keys)
- Test: `tests/test_weather_strategies.py` (rewrite), `tests/test_strategy_config.py` (extend)

**Interfaces:**
- Consumes: feature dict keyed by provider name, as delivered by `strategy_features_for_market` (already scoped per market — do **not** re-scope); `weather_model_prob` (Task 4), `kalshi_spread`, `forecast_disagreement`.
- Produces: same `Strategy` interface and **same strategy names** (ledger/strategy-instance rows and eval history keep working). Bump behavior via config, not identity.
- Config defaults: `DEFAULT_MIN_EDGE = 0.05` (5¢ required beyond costs), `DEFAULT_MAX_DISAGREEMENT_F = 3.0` (°F). `confidence_floor` keeps default 0.55 and is now a *real* gate because confidence no longer bakes the floor in.

- [ ] **Step 1: Failing tests** — rewrite `tests/test_weather_strategies.py`. Helper + representative cases (follow existing FeatureValue construction in the current file):

```python
def _feature(name: str, subject_id: str, value: str) -> FeatureValue:
    return FeatureValue.present(
        provider_name=name,
        provider_version="1",
        subject_kind="market" if name in {"weather_model_prob", "kalshi_spread"} else "location",
        subject_id=subject_id,
        as_of=AS_OF,
        value_numeric=Decimal(value),
    )


def _market(mid: str = "0.50", bid: str = "0.48", ask: str = "0.52") -> MarketState:
    return MarketState(
        ticker="KXHIGHNY-25MAY28-T73",
        series="KXHIGHNY",
        bid_yes=Decimal(bid),
        ask_yes=Decimal(ask),
        mid_yes=Decimal(mid),
        as_of=AS_OF,
        location_id="nyc",
    )


def _features(prob: str, spread: str = "0.04", disagreement: str = "1.0") -> dict[str, FeatureValue]:
    return {
        "weather_model_prob": _feature("weather_model_prob", "KXHIGHNY-25MAY28-T73", prob),
        "kalshi_spread": _feature("kalshi_spread", "KXHIGHNY-25MAY28-T73", spread),
        "forecast_disagreement": _feature("forecast_disagreement", "nyc", disagreement),
    }


class TestEnsembleDisagreement:
    def test_emits_yes_when_model_far_above_mid_and_models_agree(self) -> None:
        # model 0.70 vs mid 0.50; spread 0.04 -> threshold 0.02 + min_edge 0.05 = 0.07 < 0.20
        signal = STRATEGY.evaluate(_market(), _features("0.70"), CTX)
        assert signal is not None
        assert signal.side == PositionSide.YES
        assert signal.prob_yes == Decimal("0.70")

    def test_no_signal_when_models_disagree_too_much(self) -> None:
        assert STRATEGY.evaluate(_market(), _features("0.70", disagreement="5.0"), CTX) is None

    def test_no_signal_when_divergence_within_costs(self) -> None:
        assert STRATEGY.evaluate(_market(), _features("0.55"), CTX) is None

    def test_no_side_when_model_below_mid_emits_no(self) -> None:
        signal = STRATEGY.evaluate(_market(), _features("0.30"), CTX)
        assert signal is not None
        assert signal.side == PositionSide.NO


class TestStaleQuote:
    def test_requires_wide_spread(self) -> None:
        # spread 0.04 < wide threshold 0.08 -> None even with huge edge
        assert STRATEGY.evaluate(_market(), _features("0.90", spread="0.04"), CTX) is None

    def test_yes_edge_measured_at_ask(self) -> None:
        # ask 0.60, model 0.70, min_edge 0.05 -> edge at ask 0.10 -> YES
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        signal = STRATEGY.evaluate(market, _features("0.70", spread="0.10"), CTX)
        assert signal is not None and signal.side == PositionSide.YES

    def test_no_signal_when_edge_dies_at_entry_price(self) -> None:
        # model 0.63 vs ask 0.60 -> edge 0.03 < min_edge 0.05 -> None
        market = _market(mid="0.55", bid="0.50", ask="0.60")
        assert STRATEGY.evaluate(market, _features("0.63", spread="0.10"), CTX) is None
```

Also keep/port the existing negation cases (missing features → None, non-weather series → None).

- [ ] **Step 2: Run to verify failure** — `REQUIRE_DBS=0 pytest tests/test_weather_strategies.py -v` → FAIL.

- [ ] **Step 3: Config plumbing.** `core/domain/strategy.py`:

```python
DEFAULT_MIN_EDGE = 0.05
DEFAULT_MAX_DISAGREEMENT_F = 3.0
```

Add to `StrategyConfig`:

```python
    min_edge: float | None = None
    max_disagreement_f: float | None = None
```

In `effective_strategy_config`, default `min_edge` for **both** strategies, `max_disagreement_f` for `WEATHER_ENSEMBLE_DISAGREEMENT`, and keep the legacy defaults (`disagreement_threshold`, `spread_margin_multiplier`, `wide_spread_threshold`) exactly as they are — API consumers may render them; runtime just stops reading the first two. Update `core/ledger/seed.py` config dicts with `"min_edge": 0.05` and (disagreement strategy only) `"max_disagreement_f": 3.0`. Extend `tests/test_strategy_config.py` with a case asserting the new defaults resolve.

- [ ] **Step 4: Rewrite `weather_ensemble_disagreement/strategy.py`:**

```python
from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.weather_markets import weather_series
from core.settings import Settings
from core.strategies.weather_utils import numeric_feature

REQUIRED_FEATURES = frozenset({"weather_model_prob", "kalshi_spread", "forecast_disagreement"})


class WeatherEnsembleDisagreementStrategy(Strategy):
    """Value trade on the ensemble bracket probability, gated by model agreement.

    High GFS/ECMWF disagreement means the forecast is uncertain -> stand down.
    Trade only when models agree AND the market mid diverges from the model
    probability by more than half the spread plus a configured edge margin.
    """

    @property
    def name(self) -> str:
        return "weather_ensemble_disagreement"

    @property
    def required_features(self) -> frozenset[str]:
        return REQUIRED_FEATURES

    def is_enabled(self, settings: Settings) -> bool:
        return True

    def evaluate(
        self,
        market: MarketState,
        features: dict[str, FeatureValue],
        ctx: StrategyContext,
    ) -> SignalDraft | None:
        if not weather_series(market.series):
            return None
        if not required_features_present(
            self.required_features,
            features,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        model_prob = numeric_feature(features.get("weather_model_prob"))
        spread = numeric_feature(features.get("kalshi_spread"))
        disagreement = numeric_feature(features.get("forecast_disagreement"))
        mid = market.mid_yes
        if model_prob is None or spread is None or disagreement is None or mid is None:
            return None

        config = ctx.effective_config()
        if disagreement > Decimal(str(config.max_disagreement_f)):
            return None

        divergence = model_prob - mid
        threshold = spread / Decimal("2") + Decimal(str(config.min_edge))
        if abs(divergence) <= threshold:
            return None

        side = PositionSide.YES if divergence > 0 else PositionSide.NO
        confidence = min(Decimal("1"), abs(divergence) / Decimal("0.15"))
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=model_prob,
            confidence=confidence,
            side=side,
        )
```

- [ ] **Step 5: Rewrite `weather_stale_quote/strategy.py`:**

```python
from __future__ import annotations

from decimal import Decimal

from core.contracts.strategy import Strategy, StrategyContext, required_features_present
from core.domain.enums import PositionSide
from core.domain.feature import FeatureValue
from core.domain.market import MarketState, SignalDraft
from core.domain.weather_markets import weather_series
from core.settings import Settings
from core.strategies.weather_utils import numeric_feature

REQUIRED_FEATURES = frozenset({"weather_model_prob", "kalshi_spread"})


class WeatherStaleQuoteStrategy(Strategy):
    """Trade wide-spread (possibly stale) books only when the model edge
    survives the actual crossing price, not the mid."""

    @property
    def name(self) -> str:
        return "weather_stale_quote"

    @property
    def required_features(self) -> frozenset[str]:
        return REQUIRED_FEATURES

    def is_enabled(self, settings: Settings) -> bool:
        return True

    def evaluate(
        self,
        market: MarketState,
        features: dict[str, FeatureValue],
        ctx: StrategyContext,
    ) -> SignalDraft | None:
        if not weather_series(market.series):
            return None
        if not required_features_present(
            self.required_features,
            features,
            tolerate_missing=ctx.tolerate_missing_features,
        ):
            return None

        model_prob = numeric_feature(features.get("weather_model_prob"))
        spread = numeric_feature(features.get("kalshi_spread"))
        if model_prob is None or spread is None:
            return None
        if market.ask_yes is None or market.bid_yes is None:
            return None

        config = ctx.effective_config()
        if spread < Decimal(str(config.wide_spread_threshold)):
            return None
        min_edge = Decimal(str(config.min_edge))

        yes_edge = model_prob - market.ask_yes
        no_edge = market.bid_yes - model_prob
        if yes_edge >= no_edge and yes_edge > min_edge:
            side, edge = PositionSide.YES, yes_edge
        elif no_edge > min_edge:
            side, edge = PositionSide.NO, no_edge
        else:
            return None

        confidence = min(Decimal("1"), edge / Decimal("0.15"))
        return SignalDraft(
            ticker=market.ticker,
            prob_yes=model_prob,
            confidence=confidence,
            side=side,
        )
```

- [ ] **Step 6: Clean `weather_utils`.** Delete `ensemble_to_prob`, `prob_to_temp`, and `scoped_features` from `core/strategies/weather_utils.py`. Run `grep -rn "ensemble_to_prob\|prob_to_temp\|scoped_features" core tests` — must return nothing outside this file's history. Keep `numeric_feature` and the `weather_markets` re-exports.

- [ ] **Step 7: Run strategy tests + purity guard + full gate**

Run: `REQUIRE_DBS=0 pytest tests/test_weather_strategies.py tests/test_strategy_purity_guard.py tests/test_engine_tick.py tests/test_strategy_config.py -v`, then full gate. `tests/test_engine_tick.py` seeds features — it will need its fixtures updated to seed `weather_model_prob` (market-scoped) instead of relying on the old temp mapping; adjust its seeded feature rows accordingly.
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add core/strategies/ core/domain/strategy.py core/domain/weather_markets.py core/ledger/seed.py tests/
git commit -m "feat: rewrite weather strategies on strike-aware model probability"
```

---

### Task 8: Automatic drawdown pause

`max_drawdown_pct_from_hwm` is seeded (30%) and `StrategyState.DRAWDOWN_PAUSED` exists, but nothing enforces it. Enforce it at the top of the per-strategy loop in the tick, through a ledger writer transition.

**Files:**
- Modify: `core/ledger/writer.py` (new `_DRAWDOWN_PAUSE` transition + `drawdown_pause_strategy`)
- Modify: `core/engine/tick.py` (check before `can_emit_signals`)
- Test: `tests/test_ledger_state_machine.py` (extend), `tests/test_engine_tick.py` (extend)

**Interfaces:**
- Consumes: `StrategyInstanceRow.bankroll_cents`, `.bankroll_hwm_cents`, `effective_strategy_config(...).max_drawdown_pct_from_hwm`; existing `_LifecycleTransition` machinery and `can_pause` from `core/domain/state_machine.py`.
- Produces: `writer.drawdown_pause_strategy(session, strategy_name, reason, actor, request_id) -> None` — transitions ACTIVE → `DRAWDOWN_PAUSED` with paired audit event (via `_apply_lifecycle_transition`, same as `pause_strategy`).

- [ ] **Step 1: Failing writer test** — extend `tests/test_ledger_state_machine.py` following its existing transition-test style:

```python
def test_drawdown_pause_moves_active_strategy_to_drawdown_paused(per_env_session) -> None:
    # seed active strategy (reuse existing helper), then:
    writer.drawdown_pause_strategy(
        per_env_session, "weather_stale_quote", "drawdown 31.0% >= 30.0% from HWM",
        AuditActor.SCHEDULER, "req-1",
    )
    row = per_env_session.get(StrategyInstanceRow, ...)  # match existing lookup style
    assert row.state == StrategyState.DRAWDOWN_PAUSED.value
```

Plus: pausing from an already-paused state raises `LedgerError` (mirrors `can_pause` behavior — assert whichever the existing `pause_strategy` tests assert).

- [ ] **Step 2: Run to verify failure** — `REQUIRE_DBS=0 pytest tests/test_ledger_state_machine.py -v -k drawdown` → `AttributeError: module ... has no attribute 'drawdown_pause_strategy'`.

- [ ] **Step 3: Implement writer transition** — in `core/ledger/writer.py`, next to `_PAUSE`:

```python
_DRAWDOWN_PAUSE = _LifecycleTransition(
    action="pause_strategy",
    target_fn=lambda: StrategyState.DRAWDOWN_PAUSED,
    verb="pause",
    can_transition=can_pause,
)


def drawdown_pause_strategy(
    session: Session,
    strategy_name: str,
    reason: str,
    actor: AuditActor,
    request_id: str,
) -> None:
    _apply_lifecycle_transition(
        session, strategy_name, reason, actor, request_id, transition=_DRAWDOWN_PAUSE
    )
```

- [ ] **Step 4: Failing tick test** — extend `tests/test_engine_tick.py`: seed an ACTIVE strategy with `bankroll_hwm_cents=10_000`, `bankroll_cents=6_900` (31% drawdown, config 30%), run a tick, assert the row lands in `DRAWDOWN_PAUSED` and **no signals were recorded for it**. Second case: 29% drawdown stays ACTIVE.

- [ ] **Step 5: Implement tick check** — in `core/engine/tick.py`, inside the strategy loop, immediately after `row = strategy_rows.get(...)` / `None` check and **before** `can_emit_signals`:

```python
        config = effective_strategy_config(row.config_jsonb, strategy_name=row.name)
        if (
            StrategyState(row.state) == StrategyState.ACTIVE
            and row.bankroll_hwm_cents > 0
        ):
            drawdown_pct = (
                (row.bankroll_hwm_cents - row.bankroll_cents)
                / row.bankroll_hwm_cents
                * 100
            )
            if drawdown_pct >= config.max_drawdown_pct_from_hwm:
                writer.drawdown_pause_strategy(
                    per_env_session,
                    row.name,
                    f"drawdown {drawdown_pct:.1f}% >= "
                    f"{config.max_drawdown_pct_from_hwm}% from HWM",
                    AuditActor.SCHEDULER,
                    tick_id,
                )
                continue
```

Imports: `from core.domain.enums import StrategyState` is already there via `StrategyState(row.state)` usage; add `from core.domain.strategy import effective_strategy_config`.

- [ ] **Step 6: Run tests + full gate** — expected PASS.

- [ ] **Step 7: Commit**

```bash
git add core/ledger/writer.py core/engine/tick.py tests/
git commit -m "feat: enforce max_drawdown_pct_from_hwm — auto-pause strategies in the tick"
```

---

## Verification & ship (after all tasks)

- [ ] Full gate green: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- [ ] UI gate green (`ui/`): `npm run check && npm run lint && npm run test && npm run build`
- [ ] Migration applies on staging: `alembic -c alembic.ini upgrade head`, then `scripts/backfill_market_strikes.py`
- [ ] **Evidence:** `scripts/verify_bracket_semantics.py` output pasted in the Task 3 PR — `mismatches=0`
- [ ] Staging soak: after a few live ticks, `GET /v1/signals` shows `weather_model_prob` in `features_snapshot_jsonb` with sane probabilities (not clustered at the 0.05/0.95 clamp), and rejected signals show the new `rejected_already_positioned` / fee-related reasons
- [ ] Eval sanity after first resolutions land: calibration bins in `/v1/eval` start tracking the diagonal instead of noise
- [ ] Update `docs/milestones/M8-strategy-correctness/milestone.md` checkboxes as tasks land

---

## Follow-on milestones (each needs its own design doc before implementation)

These were part of the same review; they are deliberately **not** specified as tasks here because each is its own subsystem and PR train. Recommended order:

### M9 — Backtest/replay harness (highest leverage)
Drive `run_engine_tick` with a replay `Clock` over the append-only shared DB history (`raw_market_snapshot`, `raw_forecast_run` are already as-of-stamped; every query filters `as_of <= clock.now()`). Deliverables: replay driver walking historical timestamps against a throwaway per-env SQLite ledger; parameter-sweep entry point (grid over `min_edge`, `max_disagreement_f`, `kelly_fraction`); report reusing `core/eval/metrics.py`. Design doc: `docs/design/m9-replay.md`.

### M10 — New strategies (in order of expected edge per effort)
1. **Observed-high floor** — ingest hourly station observations (NWS/METAR) for the six settlement stations (new `Source`); feature `observed_high_so_far` per location/day; strategy: once the observed running high already decides a bracket (e.g. observed 74 vs "greater than 73"), buy any contract still priced materially below certainty. Near-deterministic; needs the M8 bracket predicate.
2. **Bracket-sum consistency** — per city/day bracket set, if `sum(ask_yes) < 1 - fees` buy the set (or flag it: the MVP can emit audit-only signals). Also a permanent ingestion sanity check.
3. **Longshot-fade baseline** — sell YES > 0.90 / buy NO < 0.10 on weather brackets, small fixed size. Not expected to be the winner; it is the benchmark other strategies must beat.
Design doc: `docs/design/m10-strategies.md`.

### M11 — Expansion
More Kalshi cities (extend `SERIES_TO_LOCATION` + `reference_location` seed + settlement-station verification), Kalshi low-temp series (same pipeline, `min` aggregation — parameterize `daily_max_by_member` direction), precipitation markets (zero-inflated distribution), Polymarket as a second venue (new `Source` + venue column on shared reference tables), automated graduation rules (promote when `posterior_edge_ci_low > 0` with `n_trades >= N` over `W` weeks; demote on drawdown pause), and mark-to-market exits (close a position when the market converges to the model probability — edge gone, free the capital — or when a new forecast run flips the signal; today positions only close at settlement). Design doc per slice.

---

## Design decisions & open questions

- **Pooling GFS+ECMWF members with equal weight** is the simplest defensible start; per-model skill weighting is a config knob for later (data will tell us via per-model `value_jsonb` means we record).
- **Laplace smoothing `(k+1)/(n+2)`** keeps probabilities off 0/1 so log-loss stays finite and Kelly never bets the house on a unanimous 30-member ensemble.
- **`min_edge` default 0.05** is deliberately conservative on top of explicit fee subtraction; tune down in staging if signal volume is too low.
- **Strategy names unchanged** so ledger history, eval snapshots, and strategy-instance rows survive. The behavior change is visible in git history and the config keys.
- **Open question (carried):** should `weather_model_prob.as_of` be the tick time or the underlying forecast run time? Tick time (chosen) keeps the freshness gate simple; run time is stricter. Revisit if stale forecasts slip through the `max_input_age_seconds` gate.
- **Open question (carried):** stale-quote strategy may rarely fire once edges must clear the ask on a wide book — that is the honest version of the idea. If it never fires in a month of staging, decommission it in favor of an M10 strategy.
