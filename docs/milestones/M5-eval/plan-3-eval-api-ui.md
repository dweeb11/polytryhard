# M5.6 + M5.7 — Eval read API & UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the `eval_metric_snapshot` data over a read-only `/v1/eval` API and surface it in the UI (per-strategy Calibration & P&L panel + roster eval columns), closing out M5.

**Architecture:** Three ordered PR slices to `staging`. (1) Read models + latest-per-window query + two FastAPI routes + OpenAPI/TS regen. (2) Per-strategy UI panel wired to live eval + a P&L timeline derived from live cash-events. (3) Roster eval columns on the strategies list. Snapshots are append-only, so "latest" = most recent `computed_at` per `strategy × window`.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0, Pydantic v2 (backend); SvelteKit 5 (runes), TypeScript, Vitest, Tailwind (frontend).

**Spec:** `docs/design/m5-eval-api-ui.md`. **Parent design:** `docs/design/m5-eval.md` §7–§8.

**Branching:** Each slice branches from `staging`, PR targets `staging`. Names: `feat/<linear-id>-m56-eval-api`, `feat/<linear-id>-m57a-eval-panel`, `feat/<linear-id>-m57b-eval-roster`.

**Prerequisite:** M5.5 (`eval_metric_snapshot` writer + recompute) merged to `staging` before starting Slice 1 implementation. The writer produces three rows per strategy per recompute: windows `7d`, `30d`, `all` (`core/eval/snapshot.py`).

---

## Reference: shapes already in the codebase

**`EvalMetricSnapshotRow`** (`core/db/models.py`) columns: `id`, `strategy_name`, `computed_at` (UTC datetime), `window` (`EvalWindow` enum), `n_trades`, `n_wins`, `hit_rate` (`float|None`), `brier_score` (`float|None`), `log_loss` (`float|None`), `pnl_cents`, `sharpe_proxy` (`float|None`), `max_drawdown_cents`, `posterior_edge_mean`, `posterior_edge_ci_low`, `posterior_edge_ci_high`, `calibration_bins_jsonb` (list of `{lower, upper, predicted_mean, observed_freq, count}`).

**`EvalWindow`** (`core/db/enums.py`): `D7 = "7d"`, `D30 = "30d"`, `ALL = "all"`.

**`CashEvent`** (`core/domain/cash_event.py`): camel-aliased; fields include `occurred_at` (ISO str), `balance_after_cents`, `kind`, `amount_cents`. Already exposed at `GET /v1/strategies/{name}/cash-events`.

**UI types** (`ui/src/lib/types.ts`): `CalibrationBucket { bucket: number; predicted: number; actual: number; count: number }`; `BankrollPoint { at: string; bankrollCents: number }`. Stores `calibrationByStrategy: Record<string, CalibrationBucket[]>` and `bankrollHistoryByStrategy: Record<string, BankrollPoint[]>` in `ui/src/lib/stores/index.ts`.

**`apiGet(path, query?)`** (`ui/src/lib/api/client.ts`) returns `Promise<unknown>`.

---

# SLICE 1 — M5.6: Read API

**Branch:** `feat/<linear-id>-m56-eval-api` from `staging`.

**Files:**
- Create: `core/domain/eval.py` — Pydantic read models.
- Create: `core/eval/read.py` — `latest_snapshots`, `roster_summary`, row→model mappers.
- Modify: `core/api/v1/routes.py` — two routes + imports.
- Create: `tests/test_eval_read.py` — read-query unit tests (per-env SQLite).
- Create: `tests/test_api_v1_eval.py` — route tests via `TestClient`.
- Modify: `ui/openapi/openapi.json` + `ui/src/lib/api/types.ts` — regenerated, committed.

---

### Task 1: Read models (`core/domain/eval.py`)

**Files:**
- Create: `core/domain/eval.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_eval_read.py`:

```python
from core.domain.eval import CalibrationBin, EvalRosterEntry, EvalSnapshot, StrategyEval


def test_eval_snapshot_serializes_camel_case() -> None:
    snap = EvalSnapshot(
        window="30d",
        computed_at="2026-06-01T00:00:00+00:00",
        n_trades=10,
        n_wins=6,
        hit_rate=0.6,
        brier_score=0.21,
        log_loss=0.62,
        pnl_cents=1500,
        sharpe_proxy=0.4,
        max_drawdown_cents=-300,
        posterior_edge_mean=0.05,
        posterior_edge_ci_low=-0.02,
        posterior_edge_ci_high=0.12,
        calibration_bins=[
            CalibrationBin(lower=0.0, upper=0.1, predicted_mean=0.05, observed_freq=0.0, count=3)
        ],
    )
    dumped = snap.model_dump(by_alias=True)
    assert dumped["nTrades"] == 10
    assert dumped["posteriorEdgeCiLow"] == -0.02
    assert dumped["calibrationBins"][0]["predictedMean"] == 0.05


def test_roster_entry_allows_null_metrics() -> None:
    entry = EvalRosterEntry(
        strategy_name="weather_ensemble_disagreement",
        n_trades=0,
        hit_rate=None,
        brier_score=None,
        pnl_cents=0,
        posterior_edge_ci_low=0.0,
    )
    assert entry.model_dump(by_alias=True)["hitRate"] is None


def test_strategy_eval_holds_windows() -> None:
    se = StrategyEval(strategy_name="x", windows=[])
    assert se.model_dump(by_alias=True)["windows"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_read.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.domain.eval'`.

- [ ] **Step 3: Write minimal implementation**

Create `core/domain/eval.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from core.domain.serde import to_camel


class _ApiModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, alias_generator=to_camel)


class CalibrationBin(_ApiModel):
    lower: float
    upper: float
    predicted_mean: float
    observed_freq: float
    count: int


class EvalSnapshot(_ApiModel):
    window: str
    computed_at: str
    n_trades: int
    n_wins: int
    hit_rate: float | None = None
    brier_score: float | None = None
    log_loss: float | None = None
    pnl_cents: int
    sharpe_proxy: float | None = None
    max_drawdown_cents: int
    posterior_edge_mean: float
    posterior_edge_ci_low: float
    posterior_edge_ci_high: float
    calibration_bins: list[CalibrationBin]


class StrategyEval(_ApiModel):
    strategy_name: str
    windows: list[EvalSnapshot]


class EvalRosterEntry(_ApiModel):
    strategy_name: str
    n_trades: int
    hit_rate: float | None = None
    brier_score: float | None = None
    pnl_cents: int
    posterior_edge_ci_low: float
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_read.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/domain/eval.py tests/test_eval_read.py
git commit -m "feat(M5.6): eval read models (snapshot, roster, calibration bin)

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 2: Read query — `latest_snapshots` + mappers (`core/eval/read.py`)

**Files:**
- Create: `core/eval/read.py`
- Modify: `tests/test_eval_read.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_read.py` (add imports at top):

```python
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow
from core.eval.read import latest_snapshots, roster_summary
from core.ledger.seed import seed_strategies_if_needed


def _session(per_env_sqlite_urls: tuple[str, str]):
    _, per_env_url = per_env_sqlite_urls
    return sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()


def _snap(strategy: str, window: EvalWindow, computed_at: datetime, **kw) -> EvalMetricSnapshotRow:
    base = dict(
        n_trades=5, n_wins=3, hit_rate=0.6, brier_score=0.2, log_loss=0.6,
        pnl_cents=100, sharpe_proxy=0.3, max_drawdown_cents=-50,
        posterior_edge_mean=0.04, posterior_edge_ci_low=-0.01, posterior_edge_ci_high=0.1,
        calibration_bins_jsonb=[],
    )
    base.update(kw)
    return EvalMetricSnapshotRow(
        id=f"{strategy}-{window.value}-{computed_at.isoformat()}",
        strategy_name=strategy, computed_at=computed_at, window=window, **base,
    )


def test_latest_snapshots_returns_one_row_per_window_latest_wins(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session(per_env_sqlite_urls)
    seed_strategies_if_needed(session, request_id="seed-read")
    name = "weather_ensemble_disagreement"
    old = datetime(2026, 5, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    session.add_all([
        _snap(name, EvalWindow.D7, old, n_trades=1),
        _snap(name, EvalWindow.D7, new, n_trades=9),
        _snap(name, EvalWindow.ALL, new, n_trades=20),
    ])
    session.commit()
    snaps = latest_snapshots(session, name)
    by_window = {s.window: s for s in snaps}
    assert by_window["7d"].n_trades == 9      # latest D7 wins
    assert by_window["all"].n_trades == 20
    assert "30d" not in by_window             # no 30d row written
    session.close()


def test_roster_summary_includes_strategies_without_snapshots(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    session = _session(per_env_sqlite_urls)
    seed_strategies_if_needed(session, request_id="seed-roster")
    name = "weather_ensemble_disagreement"
    session.add(_snap(name, EvalWindow.ALL, datetime(2026, 6, 1, tzinfo=UTC), n_trades=12, hit_rate=0.5))
    session.commit()
    roster = {e.strategy_name: e for e in roster_summary(session)}
    assert roster[name].n_trades == 12
    assert roster[name].hit_rate == 0.5
    # a seeded strategy with no snapshot still appears, with null metrics
    other = "weather_stale_quote"
    assert other in roster
    assert roster[other].n_trades == 0
    assert roster[other].hit_rate is None
    session.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_read.py -k "latest_snapshots or roster" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.eval.read'`.

- [ ] **Step 3: Write minimal implementation**

Create `core/eval/read.py`:

```python
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.domain.eval import CalibrationBin, EvalRosterEntry, EvalSnapshot, StrategyEval
from core.utils.time import format_dt

_ROSTER_WINDOW = EvalWindow.ALL


def _latest_row(session: Session, strategy_name: str, window: EvalWindow) -> EvalMetricSnapshotRow | None:
    stmt = (
        select(EvalMetricSnapshotRow)
        .where(
            EvalMetricSnapshotRow.strategy_name == strategy_name,
            EvalMetricSnapshotRow.window == window,
        )
        .order_by(EvalMetricSnapshotRow.computed_at.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def latest_snapshots(session: Session, strategy_name: str) -> list[EvalMetricSnapshotRow]:
    """Most recent snapshot row per window for one strategy (omits windows with no rows)."""
    rows = []
    for window in EvalWindow:
        row = _latest_row(session, strategy_name, window)
        if row is not None:
            rows.append(row)
    return rows


def _bins(row: EvalMetricSnapshotRow) -> list[CalibrationBin]:
    return [CalibrationBin(**b) for b in (row.calibration_bins_jsonb or [])]


def snapshot_from_row(row: EvalMetricSnapshotRow) -> EvalSnapshot:
    window = row.window.value if hasattr(row.window, "value") else str(row.window)
    return EvalSnapshot(
        window=window,
        computed_at=format_dt(row.computed_at),
        n_trades=row.n_trades,
        n_wins=row.n_wins,
        hit_rate=row.hit_rate,
        brier_score=row.brier_score,
        log_loss=row.log_loss,
        pnl_cents=row.pnl_cents,
        sharpe_proxy=row.sharpe_proxy,
        max_drawdown_cents=row.max_drawdown_cents,
        posterior_edge_mean=row.posterior_edge_mean,
        posterior_edge_ci_low=row.posterior_edge_ci_low,
        posterior_edge_ci_high=row.posterior_edge_ci_high,
        calibration_bins=_bins(row),
    )


def strategy_eval(session: Session, strategy_name: str) -> StrategyEval:
    rows = latest_snapshots(session, strategy_name)
    return StrategyEval(
        strategy_name=strategy_name,
        windows=[snapshot_from_row(r) for r in rows],
    )


def roster_summary(session: Session) -> list[EvalRosterEntry]:
    names = list(
        session.scalars(select(StrategyInstanceRow.name).order_by(StrategyInstanceRow.name)).all()
    )
    entries: list[EvalRosterEntry] = []
    for name in names:
        row = _latest_row(session, name, _ROSTER_WINDOW)
        if row is None:
            entries.append(
                EvalRosterEntry(
                    strategy_name=name,
                    n_trades=0,
                    hit_rate=None,
                    brier_score=None,
                    pnl_cents=0,
                    posterior_edge_ci_low=0.0,
                )
            )
        else:
            entries.append(
                EvalRosterEntry(
                    strategy_name=name,
                    n_trades=row.n_trades,
                    hit_rate=row.hit_rate,
                    brier_score=row.brier_score,
                    pnl_cents=row.pnl_cents,
                    posterior_edge_ci_low=row.posterior_edge_ci_low,
                )
            )
    return entries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_read.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add core/eval/read.py tests/test_eval_read.py
git commit -m "feat(M5.6): latest-per-window + roster eval read queries

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 3: API routes (`GET /v1/eval`, `GET /v1/eval/{strategy}`)

**Files:**
- Modify: `core/api/v1/routes.py`
- Create: `tests/test_api_v1_eval.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_v1_eval.py`:

```python
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.api.main import create_app
from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow
from core.ledger.seed import seed_strategies_if_needed
from core.settings import Settings


def _settings(shared_url: str, per_env_url: str) -> Settings:
    return Settings(
        REQUIRE_DBS=False,
        CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url,
        DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )


def _snap(strategy: str, window: EvalWindow, computed_at: datetime, **kw) -> EvalMetricSnapshotRow:
    base = dict(
        n_trades=8, n_wins=5, hit_rate=0.625, brier_score=0.18, log_loss=0.55,
        pnl_cents=420, sharpe_proxy=0.5, max_drawdown_cents=-90,
        posterior_edge_mean=0.06, posterior_edge_ci_low=0.01, posterior_edge_ci_high=0.11,
        calibration_bins_jsonb=[
            {"lower": 0.5, "upper": 0.6, "predictedMean": 0.55, "observedFreq": 0.5, "count": 4}
        ],
    )
    base.update(kw)
    return EvalMetricSnapshotRow(
        id=f"{strategy}-{window.value}-{computed_at.isoformat()}",
        strategy_name=strategy, computed_at=computed_at, window=window, **base,
    )


def test_eval_roster_empty_returns_seeded_strategies_with_null_metrics(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) >= 1
    assert all(r["nTrades"] == 0 and r["hitRate"] is None for r in rows)


def test_eval_roster_and_detail_with_snapshots(
    per_env_sqlite_urls: tuple[str, str], auth_headers: dict[str, str]
) -> None:
    shared_url, per_env_url = per_env_sqlite_urls
    per_env = sessionmaker(bind=create_engine(per_env_url), expire_on_commit=False)()
    seed_strategies_if_needed(per_env, request_id="seed-eval-api")
    name = "weather_ensemble_disagreement"
    now = datetime(2026, 6, 1, tzinfo=UTC)
    per_env.add_all([
        _snap(name, EvalWindow.D7, now, n_trades=3),
        _snap(name, EvalWindow.D30, now, n_trades=8),
        _snap(name, EvalWindow.ALL, now, n_trades=20),
    ])
    per_env.commit()
    per_env.close()

    with TestClient(create_app(_settings(shared_url, per_env_url))) as client:
        roster = client.get("/v1/eval", headers=auth_headers).json()
        detail = client.get(f"/v1/eval/{name}", headers=auth_headers)

    by_name = {r["strategyName"]: r for r in roster}
    assert by_name[name]["nTrades"] == 20          # roster summarizes the ALL window
    assert detail.status_code == 200
    body = detail.json()
    assert body["strategyName"] == name
    windows = {w["window"]: w for w in body["windows"]}
    assert set(windows) == {"7d", "30d", "all"}
    assert windows["all"]["nTrades"] == 20
    assert windows["all"]["calibrationBins"][0]["predictedMean"] == 0.55


def test_eval_detail_unknown_strategy_404(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval/does_not_exist", headers=auth_headers)
    assert resp.status_code == 404


def test_eval_detail_known_strategy_no_snapshots_returns_empty_windows(
    api_client: TestClient, auth_headers: dict[str, str]
) -> None:
    resp = api_client.get("/v1/eval/weather_ensemble_disagreement", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["windows"] == []


def test_eval_requires_auth(api_client: TestClient) -> None:
    assert api_client.get("/v1/eval").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_api_v1_eval.py -v`
Expected: FAIL — `404` on `/v1/eval` (route not registered) for the roster tests.

- [ ] **Step 3: Write minimal implementation**

In `core/api/v1/routes.py`, add to the imports block near the other domain/query imports:

```python
from core.db.models import StrategyInstanceRow
from core.domain.eval import EvalRosterEntry, StrategyEval
from core.eval.read import roster_summary, strategy_eval
```

(If `StrategyInstanceRow` is already imported, do not duplicate it.) Then append these routes at the end of the file:

```python
@router.get("/eval", response_model=list[EvalRosterEntry])
def list_eval_route(session: Session = Depends(per_env_db)) -> list[EvalRosterEntry]:
    return roster_summary(session)


@router.get("/eval/{strategy}", response_model=StrategyEval)
def get_eval_route(
    strategy: str, session: Session = Depends(per_env_db)
) -> StrategyEval:
    if session.get(StrategyInstanceRow, strategy) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="strategy not found")
    return strategy_eval(session, strategy)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_api_v1_eval.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/api/v1/routes.py tests/test_api_v1_eval.py
git commit -m "feat(M5.6): GET /v1/eval roster + /v1/eval/{strategy} detail routes

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 4: Regenerate OpenAPI + TS types; full backend gate

**Files:**
- Modify: `ui/openapi/openapi.json`, `ui/src/lib/api/types.ts`

- [ ] **Step 1: Export OpenAPI schema**

Run: `REQUIRE_DBS=0 CONTROL_PLANE_TOKEN=export ./.venv/bin/python scripts/export_openapi.py`
Expected: `Wrote .../ui/openapi/openapi.json`. Confirm the diff includes `/v1/eval` and `/v1/eval/{strategy}` paths plus `EvalSnapshot`/`EvalRosterEntry`/`StrategyEval`/`CalibrationBin` schemas.

- [ ] **Step 2: Regenerate TS types**

Run: `cd ui && npm run regen-api-types`
Expected: `ui/src/lib/api/types.ts` updated with the new eval schema types.

- [ ] **Step 3: Run the full backend gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: ruff clean, mypy clean, all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ui/openapi/openapi.json ui/src/lib/api/types.ts
git commit -m "chore(M5.6): regen OpenAPI + TS types for /v1/eval

Co-authored-by: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: Open PR**

```bash
git push -u origin feat/<linear-id>-m56-eval-api
gh pr create --base staging --title "M5.6: eval read API (/v1/eval)" \
  --body "Read-only roster + per-strategy eval endpoints over eval_metric_snapshot. Spec: docs/design/m5-eval-api-ui.md. Closes <linear-id>."
```

---

# SLICE 2 — M5.7a: Per-strategy eval panel

**Branch:** `feat/<linear-id>-m57a-eval-panel` from `staging` (after Slice 1 merges).

**Files:**
- Modify: `ui/src/lib/api/hydrate.ts` — add `mapCalibrationBin`, `mapCashEventsToBankroll`, `mapEvalSnapshot`, and a `hydrateStrategyEval(name)` helper.
- Modify: `ui/src/lib/stores/index.ts` — add an `evalByStrategy` store keyed by name.
- Modify: `ui/src/routes/strategies/[name]/+page.svelte` — window selector, metrics table, live calibration + bankroll, live-mode disclaimer gate.
- Modify: `ui/src/lib/__tests__/hydrate.spec.ts` — unit tests for the new mappers.

**Note on mapper inputs:** API responses are camelCase (Pydantic alias). `EvalSnapshot` arrives as `{ window, computedAt, nTrades, hitRate, brierScore, logLoss, pnlCents, sharpeProxy, maxDrawdownCents, posteriorEdgeMean, posteriorEdgeCiLow, posteriorEdgeCiHigh, calibrationBins: [{ lower, upper, predictedMean, observedFreq, count }] }`.

---

### Task 5: Calibration-bin → bucket mapper

**Files:**
- Modify: `ui/src/lib/api/hydrate.ts`
- Modify: `ui/src/lib/__tests__/hydrate.spec.ts`

- [ ] **Step 1: Write the failing test**

Add to `ui/src/lib/__tests__/hydrate.spec.ts` (extend the import from `$lib/api/hydrate` to include `mapCalibrationBins`):

```ts
describe('mapCalibrationBins', () => {
	it('maps API bins to chart buckets', () => {
		const bins = [
			{ lower: 0.0, upper: 0.1, predictedMean: 0.05, observedFreq: 0.0, count: 3 },
			{ lower: 0.5, upper: 0.6, predictedMean: 0.55, observedFreq: 0.5, count: 4 }
		];
		const buckets = mapCalibrationBins(bins);
		expect(buckets).toEqual([
			{ bucket: 0, predicted: 0.05, actual: 0.0, count: 3 },
			{ bucket: 1, predicted: 0.55, actual: 0.5, count: 4 }
		]);
	});

	it('returns [] for empty bins', () => {
		expect(mapCalibrationBins([])).toEqual([]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npm run test -- --run hydrate`
Expected: FAIL — `mapCalibrationBins is not a function` / import error.

- [ ] **Step 3: Write minimal implementation**

Add to `ui/src/lib/api/hydrate.ts` (import `CalibrationBucket` from `$lib/types` alongside existing type imports):

```ts
export function mapCalibrationBins(
	bins: Array<Record<string, unknown>>
): CalibrationBucket[] {
	return bins.map((b, i) => ({
		bucket: i,
		predicted: Number(b.predictedMean ?? 0),
		actual: Number(b.observedFreq ?? 0),
		count: Number(b.count ?? 0)
	}));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm run test -- --run hydrate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/api/hydrate.ts ui/src/lib/__tests__/hydrate.spec.ts
git commit -m "feat(M5.7a): map eval calibration bins to chart buckets

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 6: Cash-events → bankroll timeline mapper

**Files:**
- Modify: `ui/src/lib/api/hydrate.ts`
- Modify: `ui/src/lib/__tests__/hydrate.spec.ts`

- [ ] **Step 1: Write the failing test**

Add to `ui/src/lib/__tests__/hydrate.spec.ts` (extend the hydrate import to include `mapCashEventsToBankroll`):

```ts
describe('mapCashEventsToBankroll', () => {
	it('builds an ascending balance timeline from cash events', () => {
		const events = [
			{ occurredAt: '2026-06-02T00:00:00Z', balanceAfterCents: 11000 },
			{ occurredAt: '2026-06-01T00:00:00Z', balanceAfterCents: 10000 }
		];
		const points = mapCashEventsToBankroll(events);
		expect(points).toEqual([
			{ at: '2026-06-01T00:00:00Z', bankrollCents: 10000 },
			{ at: '2026-06-02T00:00:00Z', bankrollCents: 11000 }
		]);
	});

	it('returns [] when there are no events', () => {
		expect(mapCashEventsToBankroll([])).toEqual([]);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npm run test -- --run hydrate`
Expected: FAIL — `mapCashEventsToBankroll is not a function`.

- [ ] **Step 3: Write minimal implementation**

Add to `ui/src/lib/api/hydrate.ts` (import `BankrollPoint` from `$lib/types`; reuse the existing `compareIsoDesc` import — sort ascending by negating it):

```ts
export function mapCashEventsToBankroll(
	events: Array<Record<string, unknown>>
): BankrollPoint[] {
	return events
		.map((e) => ({
			at: String(e.occurredAt ?? ''),
			bankrollCents: Number(e.balanceAfterCents ?? 0)
		}))
		.sort((a, b) => -compareIsoDesc(a.at, b.at));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm run test -- --run hydrate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/api/hydrate.ts ui/src/lib/__tests__/hydrate.spec.ts
git commit -m "feat(M5.7a): derive bankroll timeline from cash events

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 7: `evalByStrategy` store + `hydrateStrategyEval` helper

**Files:**
- Modify: `ui/src/lib/stores/index.ts`
- Modify: `ui/src/lib/api/hydrate.ts`
- Modify: `ui/src/lib/__tests__/hydrate.spec.ts`

- [ ] **Step 1: Write the failing test**

Add to `ui/src/lib/__tests__/hydrate.spec.ts`:

```ts
describe('hydrateStrategyEval', () => {
	it('populates eval + calibration + bankroll stores for a strategy in live mode', async () => {
		const name = 'weather_ensemble_disagreement';
		apiGetMock.mockImplementation((path: string) => {
			if (path === `/v1/eval/${name}`)
				return Promise.resolve({
					strategyName: name,
					windows: [
						{
							window: '30d', computedAt: '2026-06-01T00:00:00Z', nTrades: 4, nWins: 2,
							hitRate: 0.5, brierScore: 0.2, logLoss: 0.6, pnlCents: 300,
							sharpeProxy: 0.3, maxDrawdownCents: -40, posteriorEdgeMean: 0.05,
							posteriorEdgeCiLow: 0.0, posteriorEdgeCiHigh: 0.1,
							calibrationBins: [{ lower: 0.5, upper: 0.6, predictedMean: 0.55, observedFreq: 0.5, count: 4 }]
						}
					]
				});
			if (path === `/v1/strategies/${name}/cash-events`)
				return Promise.resolve([
					{ occurredAt: '2026-06-01T00:00:00Z', balanceAfterCents: 10300 }
				]);
			return Promise.reject(new Error(`unexpected path: ${path}`));
		});

		await hydrateStrategyEval(name);

		expect(get(evalByStrategy)[name].windows[0].window).toBe('30d');
		expect(get(calibrationByStrategy)[name][0].predicted).toBe(0.55);
		expect(get(bankrollHistoryByStrategy)[name][0].bankrollCents).toBe(10300);
	});
});
```

Add `evalByStrategy`, `calibrationByStrategy`, `bankrollHistoryByStrategy` to the `$lib/stores` import and `hydrateStrategyEval` to the `$lib/api/hydrate` import at the top of the spec.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npm run test -- --run hydrate`
Expected: FAIL — `evalByStrategy`/`hydrateStrategyEval` undefined.

- [ ] **Step 3: Write minimal implementation**

In `ui/src/lib/stores/index.ts`, add a store (place near `calibrationByStrategy`; define a local `StrategyEvalData` type or import the generated type — keep it light):

```ts
export const evalByStrategy = writable<Record<string, { strategyName: string; windows: EvalSnapshotView[] }>>({});
```

Add the view type to `ui/src/lib/types.ts`:

```ts
export interface EvalSnapshotView {
	window: string;
	computedAt: string;
	nTrades: number;
	nWins: number;
	hitRate: number | null;
	brierScore: number | null;
	logLoss: number | null;
	pnlCents: number;
	sharpeProxy: number | null;
	maxDrawdownCents: number;
	posteriorEdgeMean: number;
	posteriorEdgeCiLow: number;
	posteriorEdgeCiHigh: number;
	calibrationBins: Array<{ lower: number; upper: number; predictedMean: number; observedFreq: number; count: number }>;
}
```

In `ui/src/lib/api/hydrate.ts`, import the stores (`calibrationByStrategy`, `bankrollHistoryByStrategy`, `evalByStrategy`) and add:

```ts
export async function hydrateStrategyEval(name: string): Promise<void> {
	const detail = (await apiGet(`/v1/eval/${name}`)) as {
		strategyName: string;
		windows: Array<Record<string, unknown>>;
	};
	evalByStrategy.update((m) => ({ ...m, [name]: detail as never }));

	const latest = detail.windows[0];
	if (latest) {
		const bins = (latest.calibrationBins as Array<Record<string, unknown>>) ?? [];
		calibrationByStrategy.update((m) => ({ ...m, [name]: mapCalibrationBins(bins) }));
	}

	const events = (await apiGet(`/v1/strategies/${name}/cash-events`)) as Array<Record<string, unknown>>;
	bankrollHistoryByStrategy.update((m) => ({ ...m, [name]: mapCashEventsToBankroll(events) }));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm run test -- --run hydrate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/stores/index.ts ui/src/lib/types.ts ui/src/lib/api/hydrate.ts ui/src/lib/__tests__/hydrate.spec.ts
git commit -m "feat(M5.7a): evalByStrategy store + hydrateStrategyEval helper

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 8: Wire the detail page — window selector + metrics table + live-mode gate

**Files:**
- Modify: `ui/src/routes/strategies/[name]/+page.svelte`

This task is UI/visual — verification is via `npm run check`/`lint`/`build` plus manual acceptance, not a unit test.

- [ ] **Step 1: Trigger eval hydration in live mode**

In the `<script>` block of `ui/src/routes/strategies/[name]/+page.svelte`, import the store + helper and the mode store, and hydrate on name change:

```ts
import { evalByStrategy } from '$lib/stores';
import { hydrateStrategyEval } from '$lib/api/hydrate';
import { apiMode } from '$lib/api/mode';

let selectedWindow = $state('30d');

$effect(() => {
	if (name && $apiMode === 'live') void hydrateStrategyEval(name);
});

const evalWindows = $derived($evalByStrategy[name]?.windows ?? []);
const activeSnapshot = $derived(
	evalWindows.find((w) => w.window === selectedWindow) ?? evalWindows[0]
);
```

- [ ] **Step 2: Drive the calibration chart from the selected window**

Replace the calibration data source so the chart follows `selectedWindow`. Update the `calibration` derived value:

```ts
import { mapCalibrationBins } from '$lib/api/hydrate';

const calibration = $derived(
	activeSnapshot
		? mapCalibrationBins(activeSnapshot.calibrationBins)
		: ($calibrationByStrategy[name] ?? [])
);
```

(Keep the `calibrationByStrategy` import for mock-mode fallback.)

- [ ] **Step 3: Add the window selector + metrics table markup**

In the Calibration panel `<div>` (the one with heading "Calibration (10 buckets)"), add a window selector above the chart and a metrics table below it:

```svelte
<div class="mb-2 flex items-center gap-2 text-xs">
	<span class="uppercase text-slate-500">Window</span>
	<select class="rounded border border-[var(--color-border)] bg-slate-900 px-2 py-0.5" bind:value={selectedWindow}>
		<option value="7d">7d</option>
		<option value="30d">30d</option>
		<option value="all">all</option>
	</select>
</div>

{#if activeSnapshot}
	<table class="mt-3 w-full text-xs">
		<tbody class="[&_td]:py-0.5">
			<tr><td class="text-slate-500">Trades</td><td class="tabular-nums">{activeSnapshot.nTrades} ({activeSnapshot.nWins} won)</td></tr>
			<tr><td class="text-slate-500">Hit rate</td><td class="tabular-nums">{activeSnapshot.hitRate == null ? '—' : (activeSnapshot.hitRate * 100).toFixed(1) + '%'}</td></tr>
			<tr><td class="text-slate-500">Brier</td><td class="tabular-nums">{activeSnapshot.brierScore == null ? '—' : activeSnapshot.brierScore.toFixed(3)}</td></tr>
			<tr><td class="text-slate-500">Log loss</td><td class="tabular-nums">{activeSnapshot.logLoss == null ? '—' : activeSnapshot.logLoss.toFixed(3)}</td></tr>
			<tr><td class="text-slate-500">P&amp;L</td><td class="tabular-nums">{formatCents(activeSnapshot.pnlCents)}</td></tr>
			<tr><td class="text-slate-500">Max drawdown</td><td class="tabular-nums">{formatCents(activeSnapshot.maxDrawdownCents)}</td></tr>
			<tr><td class="text-slate-500">Sharpe proxy</td><td class="tabular-nums">{activeSnapshot.sharpeProxy == null ? '—' : activeSnapshot.sharpeProxy.toFixed(2)}</td></tr>
			<tr><td class="text-slate-500">Posterior edge</td><td class="tabular-nums">{(activeSnapshot.posteriorEdgeMean * 100).toFixed(1)}% [{(activeSnapshot.posteriorEdgeCiLow * 100).toFixed(1)}, {(activeSnapshot.posteriorEdgeCiHigh * 100).toFixed(1)}]</td></tr>
		</tbody>
	</table>
{:else}
	<p class="mt-3 text-xs text-slate-500">No eval data yet — needs resolved trades.</p>
{/if}
```

- [ ] **Step 4: Gate the "simulated fixture data" disclaimer to mock mode**

Change the existing disclaimer block so it shows only in mock mode. Replace its `{#if $isDeveloperMode}` guard with:

```svelte
{#if $isDeveloperMode && $apiMode === 'mock'}
	<p class="text-[10px] text-slate-600">
		Prototype: buckets are simulated fixture data, not computed from live Kalshi
		resolutions.
	</p>
{/if}
```

- [ ] **Step 5: Run the UI gate**

Run: `cd ui && npm run check && npm run lint && npm run test && npm run build`
Expected: svelte-check clean, eslint clean, vitest pass, build succeeds.

- [ ] **Step 6: Manual acceptance (record evidence)**

With a live backend (`PUBLIC_BACKEND_URL`/`PUBLIC_BACKEND_TOKEN` set, `npm run dev`): open a strategy with resolved trades → metrics table populated, calibration plot reflects live bins, switching the window selector swaps the numbers, no "simulated fixture" note. In mock mode: panel unchanged, disclaimer still present, `—` for any null metric.

- [ ] **Step 7: Commit + PR**

```bash
git add ui/src/routes/strategies/[name]/+page.svelte
git commit -m "feat(M5.7a): live eval panel — window selector, metrics table, live calibration/bankroll

Co-authored-by: Claude <noreply@anthropic.com>"
git push -u origin feat/<linear-id>-m57a-eval-panel
gh pr create --base staging --title "M5.7a: per-strategy eval panel" \
  --body "Live calibration + metrics table + cash-event bankroll timeline on the strategy detail page. Spec: docs/design/m5-eval-api-ui.md. Closes <linear-id>."
```

---

# SLICE 3 — M5.7b: Roster eval columns

**Branch:** `feat/<linear-id>-m57b-eval-roster` from `staging` (after Slice 2 merges).

**Files:**
- Modify: `ui/src/lib/stores/index.ts` — `evalRoster` store.
- Modify: `ui/src/lib/api/hydrate.ts` — hydrate `/v1/eval` into `evalRoster` inside `hydrateLedgerFromApi`.
- Modify: `ui/src/lib/__tests__/hydrate.spec.ts` — assert roster hydration.
- Modify: `ui/src/routes/+page.svelte` — eval columns on the strategies table.

---

### Task 9: `evalRoster` store + hydration in `hydrateLedgerFromApi`

**Files:**
- Modify: `ui/src/lib/stores/index.ts`, `ui/src/lib/types.ts`, `ui/src/lib/api/hydrate.ts`, `ui/src/lib/__tests__/hydrate.spec.ts`

- [ ] **Step 1: Write the failing test**

In `ui/src/lib/__tests__/hydrate.spec.ts`, extend `mockCoreHydrate()` to answer `/v1/eval`, and add an assertion in the existing `hydrateLedgerFromApi` describe block:

```ts
// inside mockCoreHydrate's apiGetMock.mockImplementation:
if (path === '/v1/eval')
	return Promise.resolve([
		{ strategyName: 'weather_ensemble_disagreement', nTrades: 5, hitRate: 0.6, brierScore: 0.2, pnlCents: 400, posteriorEdgeCiLow: 0.01 }
	]);
```

```ts
it('hydrates the eval roster store', async () => {
	mockCoreHydrate();
	await hydrateLedgerFromApi();
	const roster = get(evalRoster);
	expect(roster['weather_ensemble_disagreement'].brierScore).toBe(0.2);
});
```

Add `evalRoster` to the `$lib/stores` import in the spec.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ui && npm run test -- --run hydrate`
Expected: FAIL — `evalRoster` undefined.

- [ ] **Step 3: Write minimal implementation**

Add to `ui/src/lib/types.ts`:

```ts
export interface EvalRosterEntryView {
	strategyName: string;
	nTrades: number;
	hitRate: number | null;
	brierScore: number | null;
	pnlCents: number;
	posteriorEdgeCiLow: number;
}
```

Add to `ui/src/lib/stores/index.ts`:

```ts
export const evalRoster = writable<Record<string, EvalRosterEntryView>>({});
```

In `ui/src/lib/api/hydrate.ts`, import `evalRoster`, and inside `hydrateLedgerFromApi` (after the core `Promise.all`), add:

```ts
try {
	const rosterRows = (await apiGet('/v1/eval')) as EvalRosterEntryView[];
	evalRoster.set(Object.fromEntries(rosterRows.map((r) => [r.strategyName, r])));
} catch {
	// eval roster is non-critical; leave prior/mock values in place
}
```

Import the `EvalRosterEntryView` type in `hydrate.ts`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd ui && npm run test -- --run hydrate`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/src/lib/stores/index.ts ui/src/lib/types.ts ui/src/lib/api/hydrate.ts ui/src/lib/__tests__/hydrate.spec.ts
git commit -m "feat(M5.7b): hydrate eval roster store from /v1/eval

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

### Task 10: Eval columns on the strategies table

**Files:**
- Modify: `ui/src/routes/+page.svelte`

UI/visual task — verify via `npm run check`/`lint`/`build` + manual acceptance.

- [ ] **Step 1: Read the roster store in the page script**

In the `<script>` of `ui/src/routes/+page.svelte`, add to the `$lib/stores` import: `evalRoster`. Add a small formatter near the top of the script:

```ts
import { evalRoster } from '$lib/stores';

function fmtNum(v: number | null, digits = 3): string {
	return v == null ? '—' : v.toFixed(digits);
}
```

- [ ] **Step 2: Add header cells**

In the `<thead>` row, after the existing `<th class="px-3 py-2">Today P&L</th>`, add:

```svelte
<th class="px-3 py-2">Brier</th>
<th class="px-3 py-2">Edge CI-low</th>
<th class="px-3 py-2">P&amp;L (all)</th>
```

- [ ] **Step 3: Add body cells**

In the `{#each $strategies as s (s.name)}` row, after the existing "Today P&L" `<td>`, add (using the existing `formatCents` util already imported on this page):

```svelte
{@const ev = $evalRoster[s.name]}
<td class="px-3 py-2 tabular-nums">{fmtNum(ev?.brierScore ?? null)}</td>
<td class="px-3 py-2 tabular-nums">{ev ? (ev.posteriorEdgeCiLow * 100).toFixed(1) + '%' : '—'}</td>
<td class="px-3 py-2 tabular-nums">{ev ? formatCents(ev.pnlCents) : '—'}</td>
```

- [ ] **Step 4: Run the UI gate**

Run: `cd ui && npm run check && npm run lint && npm run test && npm run build`
Expected: all clean.

- [ ] **Step 5: Manual acceptance**

Live mode: strategies table shows Brier / Edge CI-low / P&L columns populated for strategies with snapshots, `—` for those without. Mock mode: columns render `—` (no `/v1/eval` fixture) without breaking the table.

- [ ] **Step 6: Commit + PR**

```bash
git add ui/src/routes/+page.svelte
git commit -m "feat(M5.7b): eval columns (Brier, edge CI-low, P&L) on strategies list

Co-authored-by: Claude <noreply@anthropic.com>"
git push -u origin feat/<linear-id>-m57b-eval-roster
gh pr create --base staging --title "M5.7b: roster eval columns" \
  --body "Surface roster eval metrics on the strategies list. Spec: docs/design/m5-eval-api-ui.md. Closes <linear-id>."
```

---

### Task 11: Close out the milestone

**Files:**
- Modify: `docs/milestones/M5-eval/milestone.md`

- [ ] **Step 1: Check off M5.6 and M5.7**

After all three PRs merge to `staging`, edit `docs/milestones/M5-eval/milestone.md`: check `- [x] M5.6 …` and `- [x] M5.7 …`, and advance the Process stage marker from **Implement** toward **Verify**/**Ship**.

- [ ] **Step 2: Commit (on a docs branch off staging)**

```bash
git commit -am "docs(M5): check off M5.6 + M5.7 — eval API & UI complete

Co-authored-by: Claude <noreply@anthropic.com>"
```

---

## Final verification (whole plan)

- [ ] Backend gate green: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
- [ ] UI gate green: `cd ui && npm run check && npm run lint && npm run test && npm run build`
- [ ] OpenAPI/TS types regenerated and committed (no drift).
- [ ] `/v1/eval` + `/v1/eval/{strategy}` require bearer auth; unknown strategy → 404; empty strategy → `windows: []`; roster includes strategies with null metrics.
- [ ] Live mode: detail panel shows real metrics + window switching; strategies list shows eval columns; no "simulated fixture" disclaimer. Mock mode: unchanged, `—` for unknowns.

## Self-review notes (carried for the implementer)

- **Latest-per-window** uses three small ordered `LIMIT 1` queries per strategy rather than a window function — simpler and SQLite/Postgres-portable; matches the append-only "max computed_at" semantics in plan-2.
- **Roster window is `all`** by deliberate choice (cross-strategy comparison). A `?window=` param is a future extension, not in scope.
- **Calibration mapping is intentionally lossy** — the existing `CalibrationChart` only consumes `(bucket, predicted, actual, count)`; bin edges ride along in the API for future use.
- **`EvalSnapshotView`/`EvalRosterEntryView`** are hand-declared view types so the UI doesn't depend on deep paths into generated `types.ts`; the generated types remain the source of truth for the wire contract and are regenerated in Slice 1.
- **`apiMode` gating**: hydration only fires in live mode; mock mode keeps fixture stores untouched so the prototype demo stays intact.
