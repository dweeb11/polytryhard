# M5 Plan 1 — Resolution Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settle paper positions into realized P&L against Kalshi ground truth — ingest contract resolutions to the shared DB, then apply them to open positions through the ledger.

**Architecture:** A new append-only `contract_resolution` table in the shared DB is written by a `kalshi_resolution` ingestion source (conforms to the existing `IngestionSource` ABC, polls unresolved-closed reference markets). A scheduled resolution tick reads new resolutions and, for each open `paper_position` on a resolved ticker, calls a new `resolve_position` ledger writer that books realized P&L as a single paired `cash_event` + `audit_event`, marks the position `resolved`, and raises the HWM. Cost basis is *reserved* (not spent) at open, so resolution moves bankroll by net P&L only.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, Alembic, Pydantic 2, pytest (SQLite via conftest fixtures).

---

## Spec references

- Design: `docs/design/m5-eval.md` §3 (source), §4 (resolution & realized P&L), §9 (fail-closed/invariants).
- PDD: §5.1 (`contract_resolution` schema), §7.1 (ledger invariants), §7.4 (HWM).

## Scope of this plan (PR slices M5.1–M5.3)

In scope: shared schema `004`, `kalshi_resolution` source + pure parser, resolution tick + `resolve_position`/`record_realized_pnl` writers, all their tests.
Out of scope (later plans): `core/eval` metrics, `eval_metric_snapshot`, `/v1/eval`, UI. Do **not** touch those here.

## Conventions to follow (observed in the codebase)

- Shared models subclass `SharedBase` in `core/db/shared_models.py`; per-env models subclass `Base` in `core/db/models.py`.
- Enum columns use `str_enum_column(SomeStrEnum)` (from `core.db.types`); Alembic uses `sa.Enum(..., native_enum=False)`.
- Source plugins return a `FetchResult`; `persist_fetch_result` writes its contents; idempotent upserts are done by `session.get(...)` + insert-if-absent (see `ReferenceMarketRow` handling).
- Ledger mutations go **only** through `core/ledger/writer.py`. Every balance change writes a paired `cash_event` + `audit_event` in one flush (`_write_bankroll_event`). Never assign `StrategyInstanceRow.bankroll_cents` outside the writer.
- Prices/settlement are `Numeric(12, 6)` on a 0..1 scale (`mid_yes` is a YES price in `[0,1]`). Cents conversion: `round(qty * price * 100)` — see `_expected_cost_basis_cents`.
- Tests get DB URLs from the `per_env_sqlite_urls` fixture (returns `(shared_url, per_env_url)`, both migrated) and build engines with `create_engine` + `sessionmaker(expire_on_commit=False)`.

## File structure

| File | Responsibility | New/Modify |
|---|---|---|
| `core/db/shared_enums.py` | add `ContractResolution` StrEnum | Modify |
| `core/db/shared_models.py` | add `ContractResolutionRow` | Modify |
| `migrations/shared/versions/004_contract_resolution.py` | create `contract_resolution` table | Create |
| `core/contracts/source.py` | add `ContractResolutionDraft`, add `resolutions` to `FetchResult` | Modify |
| `core/sources/persistence.py` | persist resolutions (idempotent on ticker) | Modify |
| `core/sources/kalshi/resolution.py` | `KalshiResolutionSource` + pure `parse_market_result` | Create |
| `core/sources/registry.py` | register `KalshiResolutionSource` | Modify |
| `core/ledger/writer.py` | implement `record_realized_pnl`, add `resolve_position` | Modify |
| `core/engine/resolution.py` | `run_resolution_tick` orchestration | Create |
| `tests/test_contract_resolution_model.py` | schema/model round-trip | Create |
| `tests/test_kalshi_resolution_parse.py` | pure parser unit tests | Create |
| `tests/test_ledger_resolve_position.py` | resolve_position per-env tests | Create |
| `tests/test_resolution_tick.py` | end-to-end resolution tick | Create |

---

## Task 1: Shared schema — `contract_resolution` (M5.1)

**Files:**
- Modify: `core/db/shared_enums.py`
- Modify: `core/db/shared_models.py`
- Create: `migrations/shared/versions/004_contract_resolution.py`
- Test: `tests/test_contract_resolution_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_contract_resolution_model.py
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow


def test_contract_resolution_round_trip(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    with Session(engine) as session:
        session.add(
            ReferenceMarketRow(
                ticker="KXHIGHNY-25JUN01-T70",
                series="KXHIGHNY",
                title="NYC high temp",
                settlement_source=None,
                settlement_ref=None,
                open_time=None,
                close_time=None,
                settlement_time=None,
                status="closed",
                raw_jsonb={},
            )
        )
        session.add(
            ContractResolutionRow(
                ticker="KXHIGHNY-25JUN01-T70",
                resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=ContractResolution.YES,
                settlement_value=Decimal("1"),
                source_evidence_jsonb={"result": "yes"},
            )
        )
        session.commit()

        row = session.scalar(select(ContractResolutionRow))
        assert row is not None
        assert row.ticker == "KXHIGHNY-25JUN01-T70"
        assert row.resolution == ContractResolution.YES
        assert row.settlement_value == Decimal("1")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_contract_resolution_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'ContractResolution'` (and `ContractResolutionRow`).

- [ ] **Step 3: Add the enum**

In `core/db/shared_enums.py`, append:

```python
class ContractResolution(StrEnum):
    YES = "yes"
    NO = "no"
    VOID = "void"
```

- [ ] **Step 4: Add the model**

In `core/db/shared_models.py`, add `ContractResolution` to the `core.db.shared_enums` import line, then append:

```python
class ContractResolutionRow(SharedBase):
    __tablename__ = "contract_resolution"

    ticker: Mapped[str] = mapped_column(
        String(128), ForeignKey("reference_market.ticker"), primary_key=True
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[ContractResolution] = mapped_column(str_enum_column(ContractResolution))
    settlement_value: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    source_evidence_jsonb: Mapped[dict[str, object]] = mapped_column(JSON)
```

- [ ] **Step 5: Create the migration**

```python
# migrations/shared/versions/004_contract_resolution.py
"""contract_resolution shared table

Revision ID: 004_contract_resolution
Revises: 003_feature_value
Create Date: 2026-06-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004_contract_resolution"
down_revision: str | None = "003_feature_value"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contract_resolution_enum = sa.Enum(
    "yes",
    "no",
    "void",
    name="contract_resolution",
    native_enum=False,
)


def upgrade() -> None:
    op.create_table(
        "contract_resolution",
        sa.Column("ticker", sa.String(length=128), primary_key=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution", contract_resolution_enum, nullable=False),
        sa.Column("settlement_value", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("source_evidence_jsonb", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["ticker"], ["reference_market.ticker"]),
    )


def downgrade() -> None:
    op.drop_table("contract_resolution")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_contract_resolution_model.py -v`
Expected: PASS.

- [ ] **Step 7: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass (no regressions; new migration picked up by `run_upgrade("shared", ...)`).

- [ ] **Step 8: Commit**

```bash
git add core/db/shared_enums.py core/db/shared_models.py migrations/shared/versions/004_contract_resolution.py tests/test_contract_resolution_model.py
git commit -m "feat(M5.1): add contract_resolution shared table + enum

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Resolution draft + persistence plumbing (M5.2 part 1)

Wire `contract_resolution` into the source contract so a source can emit resolutions and `persist_fetch_result` writes them idempotently.

**Files:**
- Modify: `core/contracts/source.py`
- Modify: `core/sources/persistence.py`
- Test: `tests/test_kalshi_resolution_parse.py` (persistence-of-drafts test added here; parser test in Task 3)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_kalshi_resolution_parse.py
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.contracts.source import ContractResolutionDraft, FetchResult
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.sources.persistence import persist_fetch_result


def _seed_market(session: Session, ticker: str) -> None:
    session.add(
        ReferenceMarketRow(
            ticker=ticker, series="S", title="t", settlement_source=None,
            settlement_ref=None, open_time=None, close_time=None,
            settlement_time=None, status="closed", raw_jsonb={},
        )
    )
    session.commit()


def test_persist_resolution_is_idempotent(per_env_sqlite_urls: tuple[str, str]) -> None:
    shared_url, _ = per_env_sqlite_urls
    engine = create_engine(shared_url)
    ticker = "KXHIGHNY-25JUN01-T70"
    draft = ContractResolutionDraft(
        ticker=ticker,
        resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
        resolution=ContractResolution.NO,
        settlement_value=Decimal("0"),
        source_evidence_jsonb={"result": "no"},
    )
    now = datetime(2026, 6, 2, tzinfo=UTC)
    with Session(engine) as session:
        _seed_market(session, ticker)
        persist_fetch_result(
            session, source_name="kalshi_resolution", request_id="r1",
            started_at=now, finished_at=now,
            result=FetchResult(status=SourceRunStatus.OK, resolutions=[draft]),
        )
        # Second persist of the same ticker must not raise or duplicate.
        persist_fetch_result(
            session, source_name="kalshi_resolution", request_id="r2",
            started_at=now, finished_at=now,
            result=FetchResult(status=SourceRunStatus.OK, resolutions=[draft]),
        )
        rows = session.scalars(select(ContractResolutionRow)).all()
        assert len(rows) == 1
        assert rows[0].resolution == ContractResolution.NO
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_kalshi_resolution_parse.py::test_persist_resolution_is_idempotent -v`
Expected: FAIL — `ImportError: cannot import name 'ContractResolutionDraft'`.

- [ ] **Step 3: Add the draft dataclass and FetchResult field**

In `core/contracts/source.py`: add `ContractResolution` to the `core.db.shared_enums` import, and add the dataclass after `RawForecastRunDraft`:

```python
@dataclass(frozen=True)
class ContractResolutionDraft:
    ticker: str
    resolved_at: datetime
    resolution: ContractResolution
    settlement_value: Decimal
    source_evidence_jsonb: dict[str, object] = field(default_factory=dict)
```

Then add the field to `FetchResult`:

```python
    resolutions: list[ContractResolutionDraft] = field(default_factory=list)
```

And include resolutions in `rows_written`:

```python
    @property
    def rows_written(self) -> int:
        return (
            len(self.market_snapshots)
            + len(self.forecast_runs)
            + len(self.resolutions)
        )
```

- [ ] **Step 4: Persist resolutions idempotently**

In `core/sources/persistence.py`: add `ContractResolutionDraft` to the `core.contracts.source` import, add `ContractResolutionRow` to the `core.db.shared_models` import, and inside `persist_fetch_result` (before the `RawForecastRunRow` loop is fine) add:

```python
    for resolution in result.resolutions:
        if session.get(ContractResolutionRow, resolution.ticker) is not None:
            continue
        session.add(
            ContractResolutionRow(
                ticker=resolution.ticker,
                resolved_at=resolution.resolved_at,
                resolution=resolution.resolution,
                settlement_value=resolution.settlement_value,
                source_evidence_jsonb=resolution.source_evidence_jsonb,
            )
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_kalshi_resolution_parse.py::test_persist_resolution_is_idempotent -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/contracts/source.py core/sources/persistence.py tests/test_kalshi_resolution_parse.py
git commit -m "feat(M5.2): contract resolution draft + idempotent persistence

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: `kalshi_resolution` source + pure parser (M5.2 part 2)

**Files:**
- Create: `core/sources/kalshi/resolution.py`
- Modify: `core/sources/registry.py`
- Test: `tests/test_kalshi_resolution_parse.py` (add parser cases)

Kalshi's `GET /trade-api/v2/markets/{ticker}` returns a `market` object with `status` (`active`/`closed`/`settled`/`finalized`) and, once settled, `result` (`"yes"`/`"no"`/`""`). `result == ""` with a settled status means void. The parser is pure over the decoded JSON.

- [ ] **Step 1: Write the failing parser tests**

Append to `tests/test_kalshi_resolution_parse.py`:

```python
from core.sources.kalshi.resolution import parse_market_result


def test_parse_yes():
    out = parse_market_result({"market": {"status": "finalized", "result": "yes"}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.YES
    assert settlement_value == Decimal("1")


def test_parse_no():
    out = parse_market_result({"market": {"status": "settled", "result": "no"}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.NO
    assert settlement_value == Decimal("0")


def test_parse_void_empty_result_on_settled():
    out = parse_market_result({"market": {"status": "settled", "result": ""}})
    assert out is not None
    resolution, settlement_value = out
    assert resolution == ContractResolution.VOID
    assert settlement_value == Decimal("0")


def test_parse_not_yet_settled_returns_none():
    assert parse_market_result({"market": {"status": "active", "result": ""}}) is None


def test_parse_missing_market_returns_none():
    assert parse_market_result({}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_kalshi_resolution_parse.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sources.kalshi.resolution'`.

- [ ] **Step 3: Implement the source + parser**

```python
# core/sources/kalshi/resolution.py
from __future__ import annotations

from decimal import Decimal
from typing import Any

from core.clock import Clock
from core.contracts.source import (
    ContractResolutionDraft,
    FetchResult,
    IngestionSource,
    SourceContext,
)
from core.db.shared_enums import ContractResolution, SourceRunStatus
from core.settings import Settings

KALSHI_MARKET_URL = "https://api.elections.kalshi.com/trade-api/v2/markets"
_SETTLED_STATUSES = {"settled", "finalized"}
_UNRESOLVED_REFERENCE_STATUSES = {"settled", "finalized"}


def parse_market_result(payload: dict[str, Any]) -> tuple[ContractResolution, Decimal] | None:
    """Pure: decode a Kalshi market payload into (resolution, yes-settlement-price).

    Returns None when the market is not yet settled or the payload is malformed.
    Settlement value is the YES settlement price in [0, 1]: 1 for yes, 0 otherwise.
    """
    market = payload.get("market")
    if not isinstance(market, dict):
        return None
    status = market.get("status")
    if status not in _SETTLED_STATUSES:
        return None
    result = market.get("result")
    if result == "yes":
        return ContractResolution.YES, Decimal("1")
    if result == "no":
        return ContractResolution.NO, Decimal("0")
    # Settled with no/empty result => void (refund).
    return ContractResolution.VOID, Decimal("0")


class KalshiResolutionSource(IngestionSource):
    @property
    def name(self) -> str:
        return "kalshi_resolution"

    @property
    def schedule_seconds(self) -> int:
        return 3600

    def is_enabled(self, settings: Settings) -> bool:
        return True

    async def fetch(self, clock: Clock, ctx: SourceContext) -> FetchResult:
        # Target markets that have closed but are not yet recorded as settled in
        # reference data. We never poll the whole universe — only known markets.
        candidates = [
            m for m in ctx.markets
            if m.status not in _UNRESOLVED_REFERENCE_STATUSES
        ]
        if not candidates:
            return FetchResult(status=SourceRunStatus.OK)

        result = FetchResult()
        resolved_at = clock.now()
        for market in candidates:
            response = await ctx.http.get(f"{KALSHI_MARKET_URL}/{market.ticker}")
            if response.status_code >= 400:
                return FetchResult(
                    status=SourceRunStatus.DEGRADED,
                    error_text=f"Kalshi HTTP {response.status_code} for {market.ticker}",
                )
            parsed = parse_market_result(response.json())
            if parsed is None:
                continue
            resolution, settlement_value = parsed
            result.resolutions.append(
                ContractResolutionDraft(
                    ticker=market.ticker,
                    resolved_at=resolved_at,
                    resolution=resolution,
                    settlement_value=settlement_value,
                    source_evidence_jsonb=response.json().get("market", {}),
                )
            )
        return result
```

- [ ] **Step 4: Register the source**

In `core/sources/registry.py`, import and add to `_ALL_SOURCES`:

```python
from core.sources.kalshi.resolution import KalshiResolutionSource

_ALL_SOURCES: tuple[IngestionSource, ...] = (
    KalshiMarketsSource(),
    OpenMeteoSource(),
    KalshiResolutionSource(),
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_kalshi_resolution_parse.py -v`
Expected: PASS (all parser + persistence cases).

- [ ] **Step 6: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass. (If a source-health/registry test asserts an exact source count, update it to include `kalshi_resolution`.)

- [ ] **Step 7: Commit**

```bash
git add core/sources/kalshi/resolution.py core/sources/registry.py tests/test_kalshi_resolution_parse.py
git commit -m "feat(M5.2): kalshi_resolution source + pure result parser

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: `record_realized_pnl` + `resolve_position` ledger writers (M5.3 part 1)

**Files:**
- Modify: `core/ledger/writer.py`
- Test: `tests/test_ledger_resolve_position.py`

Accounting (design §4): cost basis is reserved, not spent, so resolution moves bankroll by net P&L only.

| Resolution | YES position payout | NO position payout |
|---|---|---|
| `yes` | `round(qty * settlement_value * 100)` = `100*qty` | `0` |
| `no` | `0` | `round(qty * (1 - settlement_value) * 100)` = `100*qty` |
| `void` | refund: `realized_pnl = 0` | refund: `realized_pnl = 0` |

`realized_pnl_cents = payout_cents - cost_basis_cents` (for void, payout is defined as `cost_basis_cents` so pnl is 0).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ledger_resolve_position.py
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import PositionStatus
from core.db.models import CashEventRow, PaperPositionRow
from core.db.shared_enums import ContractResolution
from core.domain.enums import AuditActor, CashEventKind, PositionSide
from core.ledger import seed, writer
from core.ledger.queries import free_cash_cents


def _setup(factory: sessionmaker[Session]) -> Session:
    session = factory()
    seed.seed_system_state(session)  # ACTIVE system + baseline rows
    return session


def _seed_strategy(session: Session, name: str, bankroll: int) -> None:
    writer.deposit(session, name, bankroll, "seed", AuditActor.OPERATOR, "req-seed")


@pytest.fixture
def session(per_env_session_factory: sessionmaker[Session]):
    s = _setup(per_env_session_factory)
    yield s
    s.close()


def _open(session: Session, *, name: str, side: PositionSide, qty: int, price: str):
    cost = int((Decimal(qty) * Decimal(price) * 100).to_integral_value())
    pos, _ = writer.open_paper_position(
        session, strategy_name=name, order_ticker="KXT", side=side, qty=qty,
        price=Decimal(price), cost_basis_cents=cost, signal_id=None, fees_cents=0,
        simulator_assumptions={}, actor=AuditActor.SCHEDULER, request_id="req-open",
    )
    return pos


def test_resolve_yes_position_wins(session: Session) -> None:
    name = "strat_a"
    writer.create_strategy(session, name)  # see note in Step 3 if helper differs
    _seed_strategy(session, name, 100_00)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    # cost basis = 400c; bankroll still 10000c (cost reserved, not spent)
    assert free_cash_cents(session, name) == 100_00 - 400

    writer.resolve_position(
        session, position=pos, resolution=ContractResolution.YES,
        settlement_value=Decimal("1"), actor=AuditActor.SCHEDULER, request_id="req-res",
    )
    session.flush()
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 1000 - 400  # payout 1000c - cost 400c
    strat = session.get(__import__("core.db.models", fromlist=["StrategyInstanceRow"]).StrategyInstanceRow, name)
    assert strat.bankroll_cents == 100_00 + 600
    assert strat.bankroll_hwm_cents == 100_00 + 600  # realized gain raises HWM
    pnl_events = [
        e for e in session.query(CashEventRow).all()
        if e.kind == CashEventKind.REALIZED_PNL and e.ref_position_id == pos.id
    ]
    assert len(pnl_events) == 1 and pnl_events[0].amount_cents == 600


def test_resolve_yes_position_loses(session: Session) -> None:
    name = "strat_b"
    writer.create_strategy(session, name)
    _seed_strategy(session, name, 100_00)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    writer.resolve_position(
        session, position=pos, resolution=ContractResolution.NO,
        settlement_value=Decimal("0"), actor=AuditActor.SCHEDULER, request_id="req-res",
    )
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed.realized_pnl_cents == -400
    from core.db.models import StrategyInstanceRow
    assert session.get(StrategyInstanceRow, name).bankroll_cents == 100_00 - 400


def test_resolve_void_refunds(session: Session) -> None:
    name = "strat_c"
    writer.create_strategy(session, name)
    _seed_strategy(session, name, 100_00)
    pos = _open(session, name=name, side=PositionSide.YES, qty=10, price="0.40")
    writer.resolve_position(
        session, position=pos, resolution=ContractResolution.VOID,
        settlement_value=Decimal("0"), actor=AuditActor.SCHEDULER, request_id="req-res",
    )
    refreshed = session.get(PaperPositionRow, pos.id)
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 0
    from core.db.models import StrategyInstanceRow
    assert session.get(StrategyInstanceRow, name).bankroll_cents == 100_00
    # free cash fully restored (reservation released)
    assert free_cash_cents(session, name) == 100_00


def test_resolve_is_idempotent(session: Session) -> None:
    name = "strat_d"
    writer.create_strategy(session, name)
    _seed_strategy(session, name, 100_00)
    pos = _open(session, name=name, side=PositionSide.NO, qty=5, price="0.30")
    writer.resolve_position(
        session, position=pos, resolution=ContractResolution.NO,
        settlement_value=Decimal("0"), actor=AuditActor.SCHEDULER, request_id="req-res",
    )
    # Re-resolving an already-resolved position is a no-op.
    writer.resolve_position(
        session, position=session.get(PaperPositionRow, pos.id),
        resolution=ContractResolution.NO, settlement_value=Decimal("0"),
        actor=AuditActor.SCHEDULER, request_id="req-res-2",
    )
    from core.db.models import StrategyInstanceRow
    # NO position, NO resolution => payout 500c, cost 150c => +350c, applied once.
    assert session.get(StrategyInstanceRow, name).bankroll_cents == 100_00 + 350
```

> **Note for the implementer:** before writing the impl, confirm the strategy-creation helper. The tests above assume `writer.create_strategy(session, name)` seeds a `strategy_instance` row. If the codebase seeds strategies differently (check `core/ledger/seed.py` and existing tests like `tests/test_ledger_deposit_withdraw.py`), replace the `writer.create_strategy(...)` + `_seed_strategy(...)` lines with the project's actual strategy-seeding helper. Do not invent a new one — reuse what `test_ledger_deposit_withdraw.py` uses.

- [ ] **Step 2: Run tests to verify they fail**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_ledger_resolve_position.py -v`
Expected: FAIL — `AttributeError: module 'core.ledger.writer' has no attribute 'resolve_position'` (and `record_realized_pnl` raises `NotImplementedError`).

- [ ] **Step 3: Implement the writers**

In `core/ledger/writer.py`: add imports near the top — `from core.db.shared_enums import ContractResolution` and ensure `PositionStatus as DbPositionStatus` is imported (it is). Replace the `record_realized_pnl` stub (currently raising `NotImplementedError`) with:

```python
def record_realized_pnl(
    session: Session,
    strategy_name: str,
    amount_cents: int,
    reason: str,
    actor: AuditActor,
    request_id: str,
    *,
    ref_position_id: str | None = None,
) -> CashEvent:
    strategy = _lock_strategy_row(session, strategy_name)
    before = {"bankrollCents": strategy.bankroll_cents}
    new_bankroll = strategy.bankroll_cents + amount_cents
    event = _write_bankroll_event(
        session,
        strategy=strategy,
        kind=CashEventKind.REALIZED_PNL,
        amount_cents=amount_cents,
        balance_after_cents=new_bankroll,
        reason=reason,
        actor=actor,
        request_id=request_id,
        audit_action="record_realized_pnl",
        before_state=before,
        after_state={"bankrollCents": new_bankroll},
        ref_position_id=ref_position_id,
    )
    # HWM is the running max of bankroll; realized gains raise it (PDD §7.4).
    if new_bankroll > strategy.bankroll_hwm_cents:
        strategy.bankroll_hwm_cents = new_bankroll
    return event
```

Then add `resolve_position` (place it after `open_paper_position`):

```python
def _resolution_payout_cents(
    *,
    side: PositionSide,
    qty: int,
    cost_basis_cents: int,
    resolution: ContractResolution,
    settlement_value: Decimal,
) -> int:
    if resolution == ContractResolution.VOID:
        return cost_basis_cents  # refund => realized_pnl 0
    yes_price = settlement_value if side == PositionSide.YES else (Decimal("1") - settlement_value)
    payout = (Decimal(qty) * yes_price * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(payout)


def resolve_position(
    session: Session,
    *,
    position: PaperPositionRow,
    resolution: ContractResolution,
    settlement_value: Decimal,
    actor: AuditActor,
    request_id: str,
) -> None:
    if position.status != DbPositionStatus.OPEN:
        return  # idempotent: already resolved/closed
    side = PositionSide(position.side.value if hasattr(position.side, "value") else position.side)
    payout = _resolution_payout_cents(
        side=side,
        qty=position.qty,
        cost_basis_cents=position.cost_basis_cents,
        resolution=resolution,
        settlement_value=settlement_value,
    )
    realized = payout - position.cost_basis_cents
    record_realized_pnl(
        session,
        position.strategy_name,
        realized,
        f"resolution {resolution.value} position={position.id}",
        actor,
        request_id,
        ref_position_id=position.id,
    )
    now = utc_now()
    position.status = DbPositionStatus.RESOLVED
    position.closed_at = now
    position.realized_pnl_cents = realized
    position.unrealized_pnl_cents = 0
    _append_audit(
        session,
        actor=actor,
        action="resolve_position",
        target_type="paper_position",
        target_id=position.id,
        before_state={"status": "open"},
        after_state={
            "status": "resolved",
            "resolution": resolution.value,
            "realizedPnlCents": realized,
        },
        reason=f"resolution {resolution.value}",
        request_id=request_id,
    )
    session.flush()
```

> Note: `record_realized_pnl` writes a zero-amount event for void (`realized == 0`), giving every resolved position a uniform cash-event trail (design §10).

- [ ] **Step 4: Run tests to verify they pass**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_ledger_resolve_position.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm purity guard + invariant tests still green**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_ledger_purity_guard.py tests/test_ledger_invariant_property.py -v`
Expected: PASS — `bankroll == SUM(cash_event)` invariant holds with the new `realized_pnl` events.

- [ ] **Step 6: Commit**

```bash
git add core/ledger/writer.py tests/test_ledger_resolve_position.py
git commit -m "feat(M5.3): resolve_position + record_realized_pnl ledger writers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Resolution tick orchestration (M5.3 part 2)

Read new resolutions from shared and apply them to open positions in per-env, in one pass. Idempotent via the position-status guard.

**Files:**
- Create: `core/engine/resolution.py`
- Test: `tests/test_resolution_tick.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resolution_tick.py
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import PositionStatus
from core.db.models import PaperPositionRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide
from core.engine.resolution import run_resolution_tick
from core.ledger import writer


def test_resolution_tick_settles_open_positions(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    ticker = "KXT"

    # shared: a resolved market
    with Session(shared_engine) as shared:
        shared.add(ReferenceMarketRow(
            ticker=ticker, series="S", title="t", settlement_source=None,
            settlement_ref=None, open_time=None, close_time=None,
            settlement_time=None, status="settled", raw_jsonb={}))
        shared.add(ContractResolutionRow(
            ticker=ticker, resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
            resolution=ContractResolution.YES, settlement_value=Decimal("1"),
            source_evidence_jsonb={}))
        shared.commit()

    # per-env: a strategy with an open YES position on that ticker
    per_env = per_env_session_factory()
    from core.ledger import seed
    seed.seed_system_state(per_env)
    name = "strat_a"
    writer.create_strategy(per_env, name)  # reuse real helper — see Task 4 note
    writer.deposit(per_env, name, 100_00, "seed", AuditActor.OPERATOR, "rq")
    pos, _ = writer.open_paper_position(
        per_env, strategy_name=name, order_ticker=ticker, side=PositionSide.YES,
        qty=10, price=Decimal("0.40"), cost_basis_cents=400, signal_id=None,
        fees_cents=0, simulator_assumptions={}, actor=AuditActor.SCHEDULER,
        request_id="rq-open")
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared, per_env_session=per_env, request_id="res-tick-1")

    assert stats["resolved"] == 1
    refreshed = per_env.get(PaperPositionRow, pos.id)
    assert refreshed.status == PositionStatus.RESOLVED
    assert refreshed.realized_pnl_cents == 600
    assert per_env.get(StrategyInstanceRow, name).bankroll_cents == 100_00 + 600

    # Second run is a no-op (positions already resolved).
    with Session(shared_engine) as shared:
        stats2 = run_resolution_tick(
            shared_session=shared, per_env_session=per_env, request_id="res-tick-2")
    assert stats2["resolved"] == 0
    per_env.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_resolution_tick.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.engine.resolution'`.

- [ ] **Step 3: Implement the tick**

```python
# core/engine/resolution.py
from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.models import PaperPositionRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow
from core.domain.enums import AuditActor
from core.ledger import writer

logger = logging.getLogger(__name__)


def _resolution_request_id() -> str:
    return f"resolution_{uuid4().hex[:12]}"


def run_resolution_tick(
    *,
    shared_session: Session,
    per_env_session: Session,
    request_id: str | None = None,
) -> dict[str, int]:
    tick_id = request_id or _resolution_request_id()
    resolutions = shared_session.scalars(select(ContractResolutionRow)).all()
    resolved = 0
    for res in resolutions:
        open_positions = per_env_session.scalars(
            select(PaperPositionRow).where(
                PaperPositionRow.ticker == res.ticker,
                PaperPositionRow.status == "open",
            )
        ).all()
        for position in open_positions:
            writer.resolve_position(
                per_env_session,
                position=position,
                resolution=ContractResolution(res.resolution),
                settlement_value=res.settlement_value,
                actor=AuditActor.SCHEDULER,
                request_id=tick_id,
            )
            resolved += 1
    per_env_session.commit()
    logger.info("resolution tick complete request_id=%s resolved=%s", tick_id, resolved)
    return {"resolved": resolved}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_resolution_tick.py -v`
Expected: PASS (both the settle and the no-op second run).

- [ ] **Step 5: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/engine/resolution.py tests/test_resolution_tick.py
git commit -m "feat(M5.3): resolution tick applies settlements to open positions

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: Wire the resolution tick into the scheduler cycle

The scheduler runs ingestion then the engine tick each cycle. After ingestion (which now includes `kalshi_resolution` writing to shared), run the resolution tick so settlements apply the same cycle.

**Files:**
- Modify: `core/scheduler.py`

- [ ] **Step 1: Locate the engine-tick call**

Read `core/scheduler.py` around `_run_engine_tick` and `run_cycle` (the cycle calls `_run_engine_tick(cycle_id)` after ingesting all sources). Confirm how it obtains shared + per-env sessions (it builds them from session factories — mirror that exact pattern).

- [ ] **Step 2: Add a resolution-tick call after the engine tick**

In the method that runs the engine tick (`_run_engine_tick`), after the existing `run_engine_tick(...)` call and using the **same** shared + per-env sessions it already opens, add:

```python
from core.engine.resolution import run_resolution_tick
# ... after run_engine_tick(...) within the same session scope:
run_resolution_tick(
    shared_session=shared_session,
    per_env_session=per_env_session,
    request_id=cycle_id,
)
```

Match the actual variable names used in that method (e.g. if it uses `shared`/`per_env`, use those). Keep it inside the existing `with`/session block so both ticks share one cycle id and commit boundary.

- [ ] **Step 3: Run the scheduler tests**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/ -k scheduler -v`
Expected: PASS. If no scheduler test exercises a full cycle, also run the full suite below.

- [ ] **Step 4: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add core/scheduler.py
git commit -m "feat(M5.3): run resolution tick after engine tick each cycle

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final verification (whole plan)

- [ ] **Full gate:** `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q` — all green.
- [ ] **Migration applies cleanly:** a fresh `per_env_sqlite_urls` fixture (used by every DB test) runs `run_upgrade("shared", ...)` through `004` without error.
- [ ] **Invariant intact:** `tests/test_ledger_invariant_property.py` passes — `bankroll == SUM(cash_event)` including `realized_pnl` events.
- [ ] **Idempotency proven:** re-running `run_resolution_tick` reports `resolved=0`; re-persisting a resolution does not duplicate.
- [ ] Update `docs/milestones/M5-eval/milestone.md`: check off M5.1, M5.2, M5.3.

## Self-review notes (carried for the implementer)

- **Strategy seeding helper (`writer.create_strategy`)** is an assumption — verify against `core/ledger/seed.py` and `tests/test_ledger_deposit_withdraw.py` and substitute the real helper before running Task 4/5 tests. This is the one place the plan could not pin an exact signature without that file.
- **Kalshi endpoint host/path** (`api.elections.kalshi.com/trade-api/v2/markets/{ticker}`) — confirm against `core/sources/kalshi/__init__.py` / `auth.py` (the markets source already calls Kalshi; reuse its base URL/auth approach rather than hardcoding if it differs).
- **Source count assertions** — if any existing test asserts the exact number/order of registered sources, update it for the added `kalshi_resolution`.
- Settlement value is stored as a YES price in `[0,1]`; payout math multiplies by `100` to reach cents, matching `_expected_cost_basis_cents`.
