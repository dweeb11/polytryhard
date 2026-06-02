# M5 Plan 2 — Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn resolved paper positions into honest, small-sample-aware evaluation metrics — pure calibration/edge math in `core/eval`, persisted per strategy × window to a new `eval_metric_snapshot` table, recomputed after every resolution tick and on a nightly schedule.

**Architecture:** A new pure `core/eval/` module computes hit rate, Brier, log-loss, P&L, drawdown, a Sharpe proxy, decile calibration bins, and a Normal-Normal posterior edge over per-trade ROI — all from plain dataclasses, no I/O. A thin query layer extracts "trades" (a resolved position joined through its opening fill to the originating signal's `prob_yes`, with the market outcome read from the shared `contract_resolution`) and the bankroll balance series. A snapshot writer persists one `eval_metric_snapshot` row per strategy × window (`7d`/`30d`/`all`) to the per-env DB. Recompute is triggered (a) inside `run_resolution_tick` for strategies whose positions just resolved, and (b) by a nightly scheduler loop for all strategies.

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, Alembic, pytest (SQLite via conftest fixtures). Pure stdlib `math`/`statistics` for the metrics — no numpy.

---

## Spec references

- Design: `docs/design/m5-eval.md` §5 (pure metrics), §6 (Normal-Normal posterior edge), §7 (snapshot writer + recompute triggers), §9 (invariants), §10 (open knobs: `τ` default `0.5`, deciles, void handling).
- PDD: §1.4 (calibration-first edge thesis), §5.2 (`eval_metric_snapshot` columns), §7.5 (graduation gate needs `posterior_edge_ci_low > 0`), §8.4 (nightly recompute).
- Milestone checklist: `docs/milestones/M5-eval/milestone.md` — this plan delivers **M5.4** (APP-210) and **M5.5** (APP-211).

## Scope of this plan (PR slices M5.4–M5.5)

In scope: `core/eval` pure metrics + posterior + calibration (M5.4); `EvalWindow` enum, `eval_metric_snapshot` model + per-env migration `003`, trade-extraction queries, snapshot writer + recompute, post-resolution + nightly wiring, integration test (M5.5).

Out of scope (later plans): `GET /v1/eval` endpoints + Pydantic schemas + OpenAPI/TS regen (M5.6); the read-only Calibration & P&L UI panel (M5.7). Do **not** touch `core/api/` or `ui/` here.

## Context already in place (verified against the codebase)

Plan 1 (M5.1–M5.3) is merged. The following exist and are relied on by this plan — do not re-create them:

- `core/db/shared_enums.py`: `ContractResolution` StrEnum (`YES="yes"`, `NO="no"`, `VOID="void"`).
- `core/db/shared_models.py`: `ContractResolutionRow` (PK `ticker`, columns `resolved_at`, `resolution`, `settlement_value`, `source_evidence_jsonb`).
- `core/db/models.py` (per-env): `PaperPositionRow` (`id`, `strategy_name`, `ticker`, `side`, `closed_at`, `qty`, `cost_basis_cents`, `realized_pnl_cents`, `status`), `PaperFillRow` (`position_id`, `signal_id`), `SignalRow` (`id`, `prob_yes`), `CashEventRow` (`strategy_name`, `occurred_at`, `balance_after_cents`), `StrategyInstanceRow` (`name`, `config_jsonb`).
- `core/db/enums.py`: `PositionStatus` (`OPEN`/`CLOSED`/`RESOLVED`), `PositionSide`.
- `core/engine/resolution.py`: `run_resolution_tick(*, shared_session, per_env_session, request_id=None) -> dict[str, int]` — resolves open positions whose ticker has a `contract_resolution`, then `per_env_session.commit()`s. **This plan modifies it** (Task 10).
- `core/scheduler.py`: `Scheduler` dataclass with `run_cycle()`, `_run_engine_tick()`, `_run_cycle_loop()`, `start()`/`stop()`, `clock`. **This plan adds nightly recompute** (Task 11).
- `core/utils/time.py`: `utc_now()` (UTC-aware `datetime`).

## Conventions to follow (observed in the codebase)

- Per-env models subclass `Base` in `core/db/models.py`; enum columns use `str_enum_column(SomeStrEnum)` from `core.db.types`; Alembic enums use `sa.Enum(..., name="...", native_enum=False)`.
- Per-env migrations live in `migrations/per_env/versions/`; the current head is `002_strategy_ledger` (so `003` chains `down_revision = "002_strategy_ledger"`). The `per_env_sqlite_urls` conftest fixture runs `run_upgrade("per_env", ...)` to head, so a new migration is picked up automatically by every DB test.
- Tests build engines with `create_engine` + `sessionmaker(expire_on_commit=False)`; the `per_env_session_factory` and `per_env_sqlite_urls` fixtures from `tests/conftest.py` provide migrated SQLite DBs. Strategy seeding in tests is done by inserting a `StrategyInstanceRow` directly then calling `writer.deposit(...)` + `writer.activate_strategy(...)` (see `tests/test_ledger_resolve_position.py::_create_strategy`). There is **no** `writer.create_strategy`.
- Money is integer cents (`BigInteger`). Statistical floats (rates, Brier, posterior) are **not** money — store them as `sa.Float` columns, not `Numeric`, so SQLite returns native `float` and mypy types stay `float`.
- Run the gate after each task: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`.

## Key design decisions locked by this plan

These resolve ambiguities in the design so the implementer does not have to:

1. **A "trade" requires a signal and a non-void resolution.** Eval trades are resolved positions inner-joined through their opening fill to a `SignalRow` (for `prob_yes`); positions with no `signal_id` are not evaluable and are excluded. `void` resolutions carry no binary outcome and zero P&L, so they are **excluded from all metrics** (design §5/§10 — voids are not evidence about edge).
2. **`outcome_yes` (the market outcome) comes from the shared `contract_resolution`, not the position side.** `outcome_yes = 1` if the market resolved `YES`, else `0`. This is the calibration target for `prob_yes` (predicted P(market resolves YES)), independent of which side we traded. So the trade-extraction query reads both the per-env and shared sessions.
3. **A "win" is a positive-P&L trade**: `n_wins = count(realized_pnl_cents > 0)`, `hit_rate = n_wins / n_trades`. Side-aware and P&L-denominated, matching the edge thesis.
4. **Posterior edge degenerate handling (concrete reading of design §6):**
   - `n == 0` → return the prior: `mean=0.0`, CI = `±1.96·τ`.
   - `n == 1` → no data-driven variance estimate exists; use the **prior-scale variance** `σ²_eff = τ²` in the conjugate update. This shrinks the lone observation halfway to 0 and keeps the CI wide (satisfies design §5 "single trade → wide, not degenerate") instead of falsely confident.
   - `n ≥ 2` → use sample variance `s²` (ddof=1), floored at a tiny epsilon `1e-9` only to avoid divide-by-zero when all ROIs are identical.
5. **Calibration bins are stored as a JSON column on the snapshot** (`calibration_bins_jsonb`), not a second table. PDD §5.2's column list is illustrative; a JSON list of `{lower, upper, predicted_mean, observed_freq, count}` keeps the snapshot self-contained for the M5.6 read API. Empty deciles are omitted.
6. **`τ` is read per strategy** from `StrategyInstanceRow.config_jsonb["posterior_tau"]`, default `0.5` (design §10).
7. **Snapshots are append-only.** Each recompute inserts fresh rows; "latest" is the max `computed_at` per strategy × window (the M5.6 read query's job, not this plan's).

## File structure

| File | Responsibility | New/Modify |
|---|---|---|
| `core/eval/__init__.py` | package marker | Create |
| `core/eval/metrics.py` | `Trade`, `CalibrationBin`, `EvalMetrics` dataclasses; pure scalar metrics; `calibration_bins`; `compute_metrics` aggregator | Create |
| `core/eval/posterior.py` | `PosteriorEdge` dataclass + `posterior_edge` (Normal-Normal) | Create |
| `core/db/enums.py` | add `EvalWindow` StrEnum | Modify |
| `core/db/models.py` | add `EvalMetricSnapshotRow` | Modify |
| `migrations/per_env/versions/003_eval_metric_snapshot.py` | create `eval_metric_snapshot` table | Create |
| `core/eval/queries.py` | `resolved_trades` + `bankroll_balance_series` extraction | Create |
| `core/eval/snapshot.py` | `write_snapshot`, `recompute_strategy`, `recompute_all` | Create |
| `core/engine/resolution.py` | trigger post-resolution recompute for affected strategies | Modify |
| `core/scheduler.py` | `run_nightly_recompute` + nightly loop | Modify |
| `tests/test_eval_metrics.py` | pure metric unit tests (test-first) | Create |
| `tests/test_eval_posterior.py` | posterior edge unit tests (test-first) | Create |
| `tests/test_eval_calibration.py` | calibration bin unit tests (test-first) | Create |
| `tests/test_eval_snapshot_model.py` | `eval_metric_snapshot` model round-trip | Create |
| `tests/test_eval_queries.py` | trade-extraction queries (per-env + shared) | Create |
| `tests/test_eval_snapshot.py` | snapshot writer + recompute | Create |
| `tests/test_eval_recompute_integration.py` | seed → open → resolve → eval end-to-end | Create |
| `tests/test_scheduler.py` | add nightly-recompute test | Modify |

---

# M5.4 — `core/eval` pure metrics (Linear APP-210)

All pure logic → **test-first** per CLAUDE.md. No I/O, no clock, no DB.

## Task 1: Package scaffold + `Trade` + counts (n_trades, n_wins, hit_rate)

**Files:**
- Create: `core/eval/__init__.py`
- Create: `core/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_metrics.py
from core.eval.metrics import Trade, hit_rate, n_trades, n_wins


def _trade(prob: float, outcome: int, pnl: int, cost: int = 100) -> Trade:
    return Trade(
        prob_yes=prob, outcome_yes=outcome, realized_pnl_cents=pnl, cost_basis_cents=cost
    )


def test_counts_basic() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    assert n_trades(trades) == 3
    assert n_wins(trades) == 2  # two positive-pnl trades
    assert hit_rate(trades) == 2 / 3


def test_counts_empty() -> None:
    assert n_trades([]) == 0
    assert n_wins([]) == 0
    assert hit_rate([]) is None  # no division by zero


def test_zero_pnl_is_not_a_win() -> None:
    assert n_wins([_trade(0.5, 1, 0)]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.eval'`.

- [ ] **Step 3: Create the package marker**

```python
# core/eval/__init__.py
```

(Empty file.)

- [ ] **Step 4: Write the dataclass + count functions**

```python
# core/eval/metrics.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Trade:
    """A resolved, signal-linked, non-void paper trade.

    prob_yes: the originating signal's predicted P(market resolves YES), in [0, 1].
    outcome_yes: the realized market outcome from the contract resolution (1 if YES, 0 if NO).
    realized_pnl_cents / cost_basis_cents: per-position P&L and reserved cost basis.
    """

    prob_yes: float
    outcome_yes: int
    realized_pnl_cents: int
    cost_basis_cents: int


def n_trades(trades: list[Trade]) -> int:
    return len(trades)


def n_wins(trades: list[Trade]) -> int:
    return sum(1 for t in trades if t.realized_pnl_cents > 0)


def hit_rate(trades: list[Trade]) -> float | None:
    total = len(trades)
    if total == 0:
        return None
    return n_wins(trades) / total
```

- [ ] **Step 5: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/eval/__init__.py core/eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat(M5.4): core/eval Trade dataclass + hit-rate counts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: Brier score + log loss

**Files:**
- Modify: `core/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

`brier = mean((p − y)²)`. `log_loss = −mean(y·ln(p) + (1−y)·ln(1−p))` with `p` clamped to `[ε, 1−ε]`, `ε = 1e-9`, so a confident wrong prediction never produces `inf`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_metrics.py`:

```python
import math

import pytest

from core.eval.metrics import brier, log_loss


def test_brier_hand_computed() -> None:
    # p=0.6,y=1 -> 0.16 ; p=0.4,y=0 -> 0.16 ; p=0.7,y=1 -> 0.09
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    assert brier(trades) == pytest.approx((0.16 + 0.16 + 0.09) / 3)


def test_brier_empty_is_none() -> None:
    assert brier([]) is None


def test_log_loss_hand_computed() -> None:
    # single trade p=0.6, y=1 -> -ln(0.6)
    assert log_loss([_trade(0.6, 1, 60)]) == pytest.approx(-math.log(0.6))


def test_log_loss_clamps_confident_wrong() -> None:
    # p=1.0 but y=0 would be +inf without clamping; clamped stays finite.
    value = log_loss([_trade(1.0, 0, -100)])
    assert value is not None and math.isfinite(value)


def test_log_loss_empty_is_none() -> None:
    assert log_loss([]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -k "brier or log_loss" -v`
Expected: FAIL — `ImportError: cannot import name 'brier'`.

- [ ] **Step 3: Implement Brier + log loss**

Add to `core/eval/metrics.py` (add `import math` at the top, below `from __future__`):

```python
import math

_LOG_LOSS_EPS = 1e-9


def brier(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    return sum((t.prob_yes - t.outcome_yes) ** 2 for t in trades) / len(trades)


def log_loss(trades: list[Trade]) -> float | None:
    if not trades:
        return None
    total = 0.0
    for t in trades:
        p = min(max(t.prob_yes, _LOG_LOSS_EPS), 1.0 - _LOG_LOSS_EPS)
        total += t.outcome_yes * math.log(p) + (1 - t.outcome_yes) * math.log(1.0 - p)
    return -total / len(trades)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -k "brier or log_loss" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat(M5.4): Brier score + clamped log loss

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: P&L, Sharpe proxy, max drawdown

**Files:**
- Modify: `core/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

`pnl_cents = Σ realized_pnl_cents`. ROI per trade `= realized_pnl_cents / cost_basis_cents`. `sharpe_proxy = mean(roi) / stdev(roi)` using **sample** stdev (ddof=1); `None` when `n < 2` or stdev is `0`. `max_drawdown_cents` is the largest peak-to-trough drop over a bankroll balance series (a separate `list[int]` input, the running `balance_after_cents` from cash events); `0` for empty or monotonically non-decreasing series.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_metrics.py`:

```python
from core.eval.metrics import max_drawdown_cents, pnl_cents, sharpe_proxy


def test_pnl_sum() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40)]
    assert pnl_cents(trades) == 20


def test_pnl_empty_is_zero() -> None:
    assert pnl_cents([]) == 0


def test_sharpe_proxy_hand_computed() -> None:
    # rois: 60/100=0.6, -40/100=-0.4 ; mean=0.1, sample stdev=sqrt(0.5)
    import statistics

    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40)]
    expected = 0.1 / statistics.stdev([0.6, -0.4])
    assert sharpe_proxy(trades) == pytest.approx(expected)


def test_sharpe_proxy_single_trade_is_none() -> None:
    assert sharpe_proxy([_trade(0.6, 1, 60)]) is None


def test_sharpe_proxy_zero_variance_is_none() -> None:
    assert sharpe_proxy([_trade(0.6, 1, 50), _trade(0.6, 1, 50)]) is None


def test_max_drawdown_peak_to_trough() -> None:
    # peak 12000 -> trough 9000 = 3000 drop; later recovery doesn't reduce it
    assert max_drawdown_cents([10000, 12000, 9000, 11000]) == 3000


def test_max_drawdown_monotonic_up_is_zero() -> None:
    assert max_drawdown_cents([10000, 10500, 11000]) == 0


def test_max_drawdown_empty_is_zero() -> None:
    assert max_drawdown_cents([]) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -k "pnl or sharpe or drawdown" -v`
Expected: FAIL — `ImportError: cannot import name 'pnl_cents'`.

- [ ] **Step 3: Implement P&L, Sharpe proxy, drawdown**

Add to `core/eval/metrics.py` (add `import statistics` near the other imports):

```python
import statistics


def pnl_cents(trades: list[Trade]) -> int:
    return sum(t.realized_pnl_cents for t in trades)


def _rois(trades: list[Trade]) -> list[float]:
    return [t.realized_pnl_cents / t.cost_basis_cents for t in trades if t.cost_basis_cents]


def sharpe_proxy(trades: list[Trade]) -> float | None:
    rois = _rois(trades)
    if len(rois) < 2:
        return None
    sd = statistics.stdev(rois)  # sample stdev, ddof=1
    if sd == 0:
        return None
    return statistics.fmean(rois) / sd


def max_drawdown_cents(balances: list[int]) -> int:
    peak = None
    worst = 0
    for balance in balances:
        if peak is None or balance > peak:
            peak = balance
        drop = peak - balance
        if drop > worst:
            worst = drop
    return worst
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -k "pnl or sharpe or drawdown" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat(M5.4): P&L sum, Sharpe proxy, max drawdown

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: Posterior edge (Normal-Normal on per-trade ROI)

**Files:**
- Create: `core/eval/posterior.py`
- Test: `tests/test_eval_posterior.py`

Model `roi_i ~ N(μ, σ²)` with skeptical prior `μ ~ N(0, τ²)`. Conjugate update (design §6):

```
σ²_eff = sample_variance(rois)   when n >= 2   (floored at 1e-9)
       = τ²                       when n == 1   (no data-driven dispersion -> prior scale)
data_precision  = n / σ²_eff
post_precision  = 1/τ² + data_precision
post_mean       = (mean(rois) · data_precision) / post_precision
post_var        = 1 / post_precision
ci_low/high     = post_mean ∓ 1.96 · sqrt(post_var)
```

`n == 0` returns the prior directly (`mean=0`, CI `±1.96·τ`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_posterior.py
import math

import pytest

from core.eval.posterior import PosteriorEdge, posterior_edge


def test_zero_trades_returns_prior() -> None:
    edge = posterior_edge([], tau=0.5)
    assert edge.mean == 0.0
    assert edge.ci_low == pytest.approx(-1.96 * 0.5)
    assert edge.ci_high == pytest.approx(1.96 * 0.5)


def test_single_trade_is_wide_and_shrunk() -> None:
    # n==1 uses sigma^2_eff = tau^2: mean shrinks to r_bar/2, sd = tau/sqrt(2)
    edge = posterior_edge([0.2], tau=0.5)
    assert edge.mean == pytest.approx(0.1)
    half_width = 1.96 * (0.5 / math.sqrt(2))
    assert edge.ci_low == pytest.approx(0.1 - half_width)
    assert edge.ci_high == pytest.approx(0.1 + half_width)
    # genuinely wide: CI spans zero, so a lone trade never "demonstrates edge"
    assert edge.ci_low < 0 < edge.ci_high


def test_two_trades_hand_computed() -> None:
    rois = [0.1, 0.3]  # mean 0.2, sample var 0.02
    tau = 0.5
    s2 = 0.02
    data_precision = 2 / s2
    post_precision = 1 / tau**2 + data_precision
    expected_mean = (0.2 * data_precision) / post_precision
    expected_sd = math.sqrt(1 / post_precision)
    edge = posterior_edge(rois, tau=tau)
    assert edge.mean == pytest.approx(expected_mean)
    assert edge.ci_low == pytest.approx(expected_mean - 1.96 * expected_sd)
    assert edge.ci_high == pytest.approx(expected_mean + 1.96 * expected_sd)


def test_more_trades_tighten_the_interval() -> None:
    few = posterior_edge([0.1, 0.3], tau=0.5)
    many = posterior_edge([0.2] * 50 + [0.1, 0.3] * 25, tau=0.5)
    assert (many.ci_high - many.ci_low) < (few.ci_high - few.ci_low)


def test_identical_rois_stay_finite() -> None:
    edge = posterior_edge([0.05, 0.05, 0.05], tau=0.5)
    assert math.isfinite(edge.mean)
    assert math.isfinite(edge.ci_low) and math.isfinite(edge.ci_high)


def test_is_frozen_dataclass() -> None:
    edge = posterior_edge([0.1, 0.2], tau=0.5)
    assert isinstance(edge, PosteriorEdge)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_posterior.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.eval.posterior'`.

- [ ] **Step 3: Implement the posterior**

```python
# core/eval/posterior.py
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

_Z = 1.96  # ~95% normal credible interval
_VAR_FLOOR = 1e-9  # avoid divide-by-zero when all ROIs are identical


@dataclass(frozen=True)
class PosteriorEdge:
    mean: float
    ci_low: float
    ci_high: float


def posterior_edge(rois: list[float], *, tau: float = 0.5) -> PosteriorEdge:
    """Normal-Normal posterior on per-trade ROI with skeptical prior N(0, tau^2).

    See docs/design/m5-eval.md §6. Degenerate-n handling:
      n == 0 -> prior (mean 0, CI from tau)
      n == 1 -> prior-scale variance (tau^2): shrinks toward 0, stays wide
      n >= 2 -> sample variance (ddof=1), floored to stay finite
    """
    prior_precision = 1.0 / (tau**2)
    n = len(rois)
    if n == 0:
        sd = math.sqrt(1.0 / prior_precision)
        return PosteriorEdge(mean=0.0, ci_low=-_Z * sd, ci_high=_Z * sd)

    mean_roi = statistics.fmean(rois)
    if n == 1:
        sigma2 = tau**2
    else:
        sigma2 = max(statistics.variance(rois), _VAR_FLOOR)

    data_precision = n / sigma2
    post_precision = prior_precision + data_precision
    post_mean = (mean_roi * data_precision) / post_precision
    post_sd = math.sqrt(1.0 / post_precision)
    return PosteriorEdge(
        mean=post_mean,
        ci_low=post_mean - _Z * post_sd,
        ci_high=post_mean + _Z * post_sd,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_posterior.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/posterior.py tests/test_eval_posterior.py
git commit -m "feat(M5.4): Normal-Normal posterior edge on per-trade ROI

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: Calibration bins (deciles)

**Files:**
- Modify: `core/eval/metrics.py`
- Test: `tests/test_eval_calibration.py`

Partition trades by `prob_yes` into `n_bins` equal-width buckets over `[0, 1]` (default deciles). For each **non-empty** bin emit `CalibrationBin(lower, upper, predicted_mean, observed_freq, count)` where `predicted_mean = mean(prob_yes)`, `observed_freq = mean(outcome_yes)`. The top bin is right-inclusive so `prob_yes == 1.0` lands in the last bin.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_calibration.py
import pytest

from core.eval.metrics import Trade, calibration_bins


def _t(prob: float, outcome: int) -> Trade:
    return Trade(prob_yes=prob, outcome_yes=outcome, realized_pnl_cents=0, cost_basis_cents=100)


def test_empty_trades_no_bins() -> None:
    assert calibration_bins([]) == []


def test_bins_group_by_decile_and_omit_empty() -> None:
    trades = [_t(0.62, 1), _t(0.66, 0), _t(0.71, 1)]
    bins = calibration_bins(trades, n_bins=10)
    assert len(bins) == 2  # 0.6-0.7 bin and 0.7-0.8 bin; all others empty
    first = bins[0]
    assert first.lower == pytest.approx(0.6)
    assert first.upper == pytest.approx(0.7)
    assert first.count == 2
    assert first.predicted_mean == pytest.approx((0.62 + 0.66) / 2)
    assert first.observed_freq == pytest.approx(0.5)
    second = bins[1]
    assert second.count == 1
    assert second.observed_freq == pytest.approx(1.0)


def test_prob_one_lands_in_last_bin() -> None:
    bins = calibration_bins([_t(1.0, 1)], n_bins=10)
    assert len(bins) == 1
    assert bins[0].lower == pytest.approx(0.9)
    assert bins[0].upper == pytest.approx(1.0)
    assert bins[0].count == 1


def test_bins_are_sorted_ascending() -> None:
    bins = calibration_bins([_t(0.95, 1), _t(0.05, 0), _t(0.55, 1)], n_bins=10)
    lowers = [b.lower for b in bins]
    assert lowers == sorted(lowers)


def test_as_dict_shape() -> None:
    [bin_] = calibration_bins([_t(0.55, 1)], n_bins=10)
    assert bin_.as_dict() == {
        "lower": pytest.approx(0.5),
        "upper": pytest.approx(0.6),
        "predicted_mean": pytest.approx(0.55),
        "observed_freq": pytest.approx(1.0),
        "count": 1,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_calibration.py -v`
Expected: FAIL — `ImportError: cannot import name 'calibration_bins'`.

- [ ] **Step 3: Implement calibration bins**

Add to `core/eval/metrics.py`:

```python
@dataclass(frozen=True)
class CalibrationBin:
    lower: float
    upper: float
    predicted_mean: float
    observed_freq: float
    count: int

    def as_dict(self) -> dict[str, object]:
        # dict[str, object] (not float | int) so the JSON column's
        # Mapped[list[dict[str, object]]] assignment type-checks under mypy invariance.
        return {
            "lower": self.lower,
            "upper": self.upper,
            "predicted_mean": self.predicted_mean,
            "observed_freq": self.observed_freq,
            "count": self.count,
        }


def calibration_bins(trades: list[Trade], *, n_bins: int = 10) -> list[CalibrationBin]:
    if not trades:
        return []
    width = 1.0 / n_bins
    buckets: list[list[Trade]] = [[] for _ in range(n_bins)]
    for t in trades:
        idx = int(t.prob_yes / width)
        if idx >= n_bins:  # prob_yes == 1.0 (or float fuzz) -> last bin
            idx = n_bins - 1
        if idx < 0:
            idx = 0
        buckets[idx].append(t)
    bins: list[CalibrationBin] = []
    for idx, bucket in enumerate(buckets):
        if not bucket:
            continue
        bins.append(
            CalibrationBin(
                lower=idx * width,
                upper=(idx + 1) * width,
                predicted_mean=statistics.fmean(b.prob_yes for b in bucket),
                observed_freq=statistics.fmean(b.outcome_yes for b in bucket),
                count=len(bucket),
            )
        )
    return bins
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_calibration.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/metrics.py tests/test_eval_calibration.py
git commit -m "feat(M5.4): decile calibration bins

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: `compute_metrics` aggregator + `EvalMetrics`

**Files:**
- Modify: `core/eval/metrics.py`
- Test: `tests/test_eval_metrics.py`

One call that bundles every metric for a (strategy, window) into an `EvalMetrics` result. Takes the trade list, the bankroll balance series (for drawdown), and `tau`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_eval_metrics.py`:

```python
from core.eval.metrics import EvalMetrics, compute_metrics


def test_compute_metrics_empty() -> None:
    m = compute_metrics([], balances=[10000], tau=0.5)
    assert isinstance(m, EvalMetrics)
    assert m.n_trades == 0
    assert m.n_wins == 0
    assert m.hit_rate is None
    assert m.brier is None
    assert m.log_loss is None
    assert m.pnl_cents == 0
    assert m.sharpe_proxy is None
    assert m.max_drawdown_cents == 0
    assert m.posterior_edge_mean == 0.0  # prior
    assert m.posterior_edge_ci_low == pytest.approx(-1.96 * 0.5)
    assert m.calibration_bins == []


def test_compute_metrics_populated() -> None:
    trades = [_trade(0.6, 1, 60), _trade(0.4, 0, -40), _trade(0.7, 1, 30)]
    m = compute_metrics(trades, balances=[10000, 10060, 10020, 10050], tau=0.5)
    assert m.n_trades == 3
    assert m.n_wins == 2
    assert m.hit_rate == pytest.approx(2 / 3)
    assert m.brier == pytest.approx((0.16 + 0.16 + 0.09) / 3)
    assert m.pnl_cents == 50
    assert m.max_drawdown_cents == 40  # 10060 -> 10020
    # three trades at 0.4, 0.6, 0.7 fall in three distinct deciles -> 3 non-empty bins
    assert len(m.calibration_bins) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -k compute_metrics -v`
Expected: FAIL — `ImportError: cannot import name 'EvalMetrics'`.

- [ ] **Step 3: Implement the aggregator**

Add to `core/eval/metrics.py` (add `from core.eval.posterior import posterior_edge` to the imports):

```python
from core.eval.posterior import posterior_edge


@dataclass(frozen=True)
class EvalMetrics:
    n_trades: int
    n_wins: int
    hit_rate: float | None
    brier: float | None
    log_loss: float | None
    pnl_cents: int
    sharpe_proxy: float | None
    max_drawdown_cents: int
    posterior_edge_mean: float
    posterior_edge_ci_low: float
    posterior_edge_ci_high: float
    calibration_bins: list[CalibrationBin]


def compute_metrics(
    trades: list[Trade],
    *,
    balances: list[int],
    tau: float = 0.5,
    n_bins: int = 10,
) -> EvalMetrics:
    edge = posterior_edge(_rois(trades), tau=tau)
    return EvalMetrics(
        n_trades=n_trades(trades),
        n_wins=n_wins(trades),
        hit_rate=hit_rate(trades),
        brier=brier(trades),
        log_loss=log_loss(trades),
        pnl_cents=pnl_cents(trades),
        sharpe_proxy=sharpe_proxy(trades),
        max_drawdown_cents=max_drawdown_cents(balances),
        posterior_edge_mean=edge.mean,
        posterior_edge_ci_low=edge.ci_low,
        posterior_edge_ci_high=edge.ci_high,
        calibration_bins=calibration_bins(trades, n_bins=n_bins),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Run the M5.4 gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_metrics.py tests/test_eval_posterior.py tests/test_eval_calibration.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/eval/metrics.py tests/test_eval_metrics.py
git commit -m "feat(M5.4): compute_metrics aggregator + EvalMetrics

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

# M5.5 — `eval_metric_snapshot` writer + recompute (Linear APP-211)

## Task 7: `EvalWindow` enum + `eval_metric_snapshot` model + migration `003`

**Files:**
- Modify: `core/db/enums.py`
- Modify: `core/db/models.py`
- Create: `migrations/per_env/versions/003_eval_metric_snapshot.py`
- Test: `tests/test_eval_snapshot_model.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_snapshot_model.py
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow, StrategyState as DbStrategyState
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.utils.time import utc_now


def _seed_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name, enabled=True, state=DbStrategyState.SEEDED,
            bankroll_cents=0, initial_deposit_cents=0, bankroll_hwm_cents=0,
            hwm_reset_at=None, kelly_fraction=0.25, config_jsonb={},
            consecutive_min_position_rejections=0,
            last_state_change_at=now, created_at=now, updated_at=now,
        )
    )
    session.commit()


def test_eval_metric_snapshot_round_trip(per_env_sqlite_urls: tuple[str, str]) -> None:
    _, per_env_url = per_env_sqlite_urls
    engine = create_engine(per_env_url)
    with Session(engine) as session:
        _seed_strategy(session, "strat_a")
        session.add(
            EvalMetricSnapshotRow(
                id="snap-1",
                strategy_name="strat_a",
                computed_at=datetime(2026, 6, 2, tzinfo=UTC),
                window=EvalWindow.D7,
                n_trades=3,
                n_wins=2,
                hit_rate=2 / 3,
                brier_score=0.13,
                log_loss=0.5,
                pnl_cents=50,
                sharpe_proxy=0.4,
                max_drawdown_cents=40,
                posterior_edge_mean=0.1,
                posterior_edge_ci_low=-0.2,
                posterior_edge_ci_high=0.4,
                calibration_bins_jsonb=[
                    {"lower": 0.6, "upper": 0.7, "predicted_mean": 0.63,
                     "observed_freq": 0.5, "count": 2}
                ],
            )
        )
        session.commit()

        row = session.scalar(select(EvalMetricSnapshotRow))
        assert row is not None
        assert row.window == EvalWindow.D7
        assert row.n_trades == 3
        assert row.hit_rate == 2 / 3
        assert row.calibration_bins_jsonb[0]["count"] == 2

        # nullable float metrics accept None (n=0 windows)
        session.add(
            EvalMetricSnapshotRow(
                id="snap-2", strategy_name="strat_a",
                computed_at=datetime(2026, 6, 2, tzinfo=UTC), window=EvalWindow.ALL,
                n_trades=0, n_wins=0, hit_rate=None, brier_score=None, log_loss=None,
                pnl_cents=0, sharpe_proxy=None, max_drawdown_cents=0,
                posterior_edge_mean=0.0, posterior_edge_ci_low=-0.98,
                posterior_edge_ci_high=0.98, calibration_bins_jsonb=[],
            )
        )
        session.commit()
        assert session.get(EvalMetricSnapshotRow, "snap-2").hit_rate is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_snapshot_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'EvalWindow'`.

- [ ] **Step 3: Add the `EvalWindow` enum**

In `core/db/enums.py`, append:

```python
class EvalWindow(StrEnum):
    D7 = "7d"
    D30 = "30d"
    ALL = "all"
```

- [ ] **Step 4: Add the model**

In `core/db/models.py`: add `Float` to the `from sqlalchemy import (...)` block, add `EvalWindow` to the `from core.db.enums import (...)` block, then append:

```python
class EvalMetricSnapshotRow(Base):
    __tablename__ = "eval_metric_snapshot"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    strategy_name: Mapped[str] = mapped_column(
        String(128), ForeignKey("strategy_instance.name"), index=True
    )
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    window: Mapped[EvalWindow] = mapped_column(str_enum_column(EvalWindow))
    n_trades: Mapped[int] = mapped_column(Integer)
    n_wins: Mapped[int] = mapped_column(Integer)
    hit_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    brier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    log_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    pnl_cents: Mapped[int] = mapped_column(BigInteger)
    sharpe_proxy: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_cents: Mapped[int] = mapped_column(BigInteger)
    posterior_edge_mean: Mapped[float] = mapped_column(Float)
    posterior_edge_ci_low: Mapped[float] = mapped_column(Float)
    posterior_edge_ci_high: Mapped[float] = mapped_column(Float)
    calibration_bins_jsonb: Mapped[list[dict[str, object]]] = mapped_column(JSON)
```

- [ ] **Step 5: Create the migration**

```python
# migrations/per_env/versions/003_eval_metric_snapshot.py
"""eval_metric_snapshot table

Revision ID: 003_eval_metric_snapshot
Revises: 002_strategy_ledger
Create Date: 2026-06-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "003_eval_metric_snapshot"
down_revision: str | None = "002_strategy_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

eval_window_enum = sa.Enum("7d", "30d", "all", name="eval_window", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "eval_metric_snapshot",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "strategy_name",
            sa.String(length=128),
            sa.ForeignKey("strategy_instance.name"),
            nullable=False,
        ),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window", eval_window_enum, nullable=False),
        sa.Column("n_trades", sa.Integer(), nullable=False),
        sa.Column("n_wins", sa.Integer(), nullable=False),
        sa.Column("hit_rate", sa.Float(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("log_loss", sa.Float(), nullable=True),
        sa.Column("pnl_cents", sa.BigInteger(), nullable=False),
        sa.Column("sharpe_proxy", sa.Float(), nullable=True),
        sa.Column("max_drawdown_cents", sa.BigInteger(), nullable=False),
        sa.Column("posterior_edge_mean", sa.Float(), nullable=False),
        sa.Column("posterior_edge_ci_low", sa.Float(), nullable=False),
        sa.Column("posterior_edge_ci_high", sa.Float(), nullable=False),
        sa.Column("calibration_bins_jsonb", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_eval_metric_snapshot_strategy_window_computed",
        "eval_metric_snapshot",
        ["strategy_name", "window", sa.text("computed_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_eval_metric_snapshot_strategy_window_computed",
        table_name="eval_metric_snapshot",
    )
    op.drop_table("eval_metric_snapshot")
```

- [ ] **Step 6: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_snapshot_model.py -v`
Expected: PASS (the conftest fixture migrates per-env to head, including `003`).

- [ ] **Step 7: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass (no regressions; `test_db_smoke` uses `IN (...)` filters so the new table is fine).

- [ ] **Step 8: Commit**

```bash
git add core/db/enums.py core/db/models.py migrations/per_env/versions/003_eval_metric_snapshot.py tests/test_eval_snapshot_model.py
git commit -m "feat(M5.5): eval_metric_snapshot table + EvalWindow enum

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: Trade-extraction queries

**Files:**
- Create: `core/eval/queries.py`
- Test: `tests/test_eval_queries.py`

`resolved_trades` joins per-env `paper_position → paper_fill → signal` (for `prob_yes`), filters to `RESOLVED` positions for the strategy in the window, then reads each ticker's outcome from the shared `contract_resolution` (excluding `VOID` and tickers with no resolution row). `bankroll_balance_series` returns the chronological `balance_after_cents` series for the strategy in the window.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_queries.py
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import StrategyState as DbStrategyState
from core.db.models import SignalRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.eval.queries import bankroll_balance_series, resolved_trades
from core.ledger import writer
from core.utils.time import utc_now

NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


def _create_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name, enabled=True, state=DbStrategyState.SEEDED,
            bankroll_cents=0, initial_deposit_cents=0, bankroll_hwm_cents=0,
            hwm_reset_at=None, kelly_fraction=0.25,
            config_jsonb={"min_bankroll_cents": 10_000, "max_input_age_seconds": 900,
                          "auto_resume_on_deposit": True},
            consecutive_min_position_rejections=0,
            last_state_change_at=now, created_at=now, updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "setup", AuditActor.USER, "rq")
    session.commit()


def _insert_signal(session: Session, *, signal_id: str, name: str, ticker: str,
                   prob_yes: str) -> None:
    session.add(
        SignalRow(
            id=signal_id, strategy_name=name, ticker=ticker, evaluated_at=utc_now(),
            prob_yes=Decimal(prob_yes), confidence=Decimal("0.6"),
            features_snapshot_jsonb={}, market_state_jsonb={},
            outcome=SignalOutcome.ORDER_PLACED, rejection_reason=None,
        )
    )
    session.flush()


def _seed_resolution(shared: Session, ticker: str, resolution: ContractResolution) -> None:
    shared.add(
        ReferenceMarketRow(
            ticker=ticker, series="S", title="t", settlement_source=None,
            settlement_ref=None, open_time=None, close_time=None,
            settlement_time=None, status="settled", raw_jsonb={},
        )
    )
    shared.flush()
    shared.add(
        ContractResolutionRow(
            ticker=ticker, resolved_at=NOW, resolution=resolution,
            settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
            source_evidence_jsonb={},
        )
    )
    shared.commit()


def _open_and_resolve(per_env: Session, *, name: str, signal_id: str, ticker: str,
                      side: PositionSide, resolution: ContractResolution) -> None:
    pos, _ = writer.open_paper_position(
        per_env, strategy_name=name, order_ticker=ticker, side=side, qty=10,
        price=Decimal("0.40"), cost_basis_cents=400, signal_id=signal_id, fees_cents=0,
        simulator_assumptions={}, actor=AuditActor.SCHEDULER, request_id="rq-open",
    )
    writer.resolve_position(
        per_env, position=pos, resolution=resolution,
        settlement_value=Decimal("1") if resolution == ContractResolution.YES else Decimal("0"),
        actor=AuditActor.SCHEDULER, request_id="rq-res",
    )
    per_env.commit()


def test_resolved_trades_joins_signal_and_outcome(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_a"

    with Session(shared_engine) as shared:
        _seed_resolution(shared, "KX-WIN", ContractResolution.YES)
        _seed_resolution(shared, "KX-VOID", ContractResolution.VOID)

    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
    _insert_signal(per_env, signal_id="sig-win", name=name, ticker="KX-WIN", prob_yes="0.6")
    _insert_signal(per_env, signal_id="sig-void", name=name, ticker="KX-VOID", prob_yes="0.5")
    _open_and_resolve(per_env, name=name, signal_id="sig-win", ticker="KX-WIN",
                      side=PositionSide.YES, resolution=ContractResolution.YES)
    _open_and_resolve(per_env, name=name, signal_id="sig-void", ticker="KX-VOID",
                      side=PositionSide.YES, resolution=ContractResolution.VOID)

    with Session(shared_engine) as shared:
        trades = resolved_trades(
            per_env_session=per_env, shared_session=shared,
            strategy_name=name, window="all", now=NOW,
        )

    assert len(trades) == 1  # void excluded
    assert trades[0].prob_yes == 0.6
    assert trades[0].outcome_yes == 1  # market resolved YES
    assert trades[0].realized_pnl_cents == 600
    assert trades[0].cost_basis_cents == 400
    per_env.close()


def test_resolved_trades_excludes_unsignaled_position(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_b"
    with Session(shared_engine) as shared:
        _seed_resolution(shared, "KX-NOSIG", ContractResolution.YES)
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
    _open_and_resolve(per_env, name=name, signal_id=None, ticker="KX-NOSIG",
                      side=PositionSide.YES, resolution=ContractResolution.YES)
    with Session(shared_engine) as shared:
        trades = resolved_trades(
            per_env_session=per_env, shared_session=shared,
            strategy_name=name, window="all", now=NOW,
        )
    assert trades == []  # no signal_id -> not evaluable
    per_env.close()


def test_window_cutoff_excludes_old_trades(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_c"
    with Session(shared_engine) as shared:
        _seed_resolution(shared, "KX-OLD", ContractResolution.YES)
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
    _insert_signal(per_env, signal_id="sig-old", name=name, ticker="KX-OLD", prob_yes="0.6")
    _open_and_resolve(per_env, name=name, signal_id="sig-old", ticker="KX-OLD",
                      side=PositionSide.YES, resolution=ContractResolution.YES)
    # backdate the position's closed_at to 40 days ago
    from core.db.models import PaperPositionRow
    pos = per_env.query(PaperPositionRow).one()
    pos.closed_at = NOW - timedelta(days=40)
    per_env.commit()

    with Session(shared_engine) as shared:
        in_30d = resolved_trades(per_env_session=per_env, shared_session=shared,
                                 strategy_name=name, window="30d", now=NOW)
        in_all = resolved_trades(per_env_session=per_env, shared_session=shared,
                                 strategy_name=name, window="all", now=NOW)
    assert in_30d == []        # outside 30-day window
    assert len(in_all) == 1    # always in 'all'
    per_env.close()


def test_bankroll_balance_series_chronological(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    name = "strat_d"
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)  # deposit 10000 -> one cash event
    series = bankroll_balance_series(
        per_env_session=per_env, strategy_name=name, window="all", now=NOW
    )
    assert series == [100_00]
    per_env.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_queries.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.eval.queries'`.

- [ ] **Step 3: Implement the queries**

```python
# core/eval/queries.py
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import PositionStatus
from core.db.models import CashEventRow, PaperFillRow, PaperPositionRow, SignalRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow
from core.eval.metrics import Trade

_WINDOW_DAYS: dict[str, int] = {"7d": 7, "30d": 30}


def _window_cutoff(window: str, now: datetime) -> datetime | None:
    days = _WINDOW_DAYS.get(window)
    return None if days is None else now - timedelta(days=days)


def resolved_trades(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    window: str,
    now: datetime,
) -> list[Trade]:
    """Resolved, signal-linked, non-void trades for a strategy in a window.

    prob_yes comes from the originating signal (per-env); outcome_yes comes from
    the shared contract_resolution. Positions without a signal, or whose market
    voided / has no resolution row, are excluded (design §5/§10).
    """
    cutoff = _window_cutoff(window, now)
    stmt = (
        select(PaperPositionRow, SignalRow.prob_yes)
        .join(PaperFillRow, PaperFillRow.position_id == PaperPositionRow.id)
        .join(SignalRow, SignalRow.id == PaperFillRow.signal_id)
        .where(
            PaperPositionRow.strategy_name == strategy_name,
            PaperPositionRow.status == PositionStatus.RESOLVED,
        )
    )
    if cutoff is not None:
        stmt = stmt.where(PaperPositionRow.closed_at >= cutoff)
    rows = per_env_session.execute(stmt).all()
    if not rows:
        return []

    tickers = {pos.ticker for pos, _ in rows}
    resolutions = {
        r.ticker: ContractResolution(r.resolution)
        for r in shared_session.scalars(
            select(ContractResolutionRow).where(ContractResolutionRow.ticker.in_(tickers))
        ).all()
    }

    trades: list[Trade] = []
    seen: set[str] = set()
    for pos, prob_yes in rows:
        if pos.id in seen:  # one trade per position even if multiple fills
            continue
        seen.add(pos.id)
        resolution = resolutions.get(pos.ticker)
        if resolution is None or resolution == ContractResolution.VOID:
            continue
        trades.append(
            Trade(
                prob_yes=float(prob_yes),
                outcome_yes=1 if resolution == ContractResolution.YES else 0,
                realized_pnl_cents=pos.realized_pnl_cents or 0,
                cost_basis_cents=pos.cost_basis_cents,
            )
        )
    return trades


def bankroll_balance_series(
    *,
    per_env_session: Session,
    strategy_name: str,
    window: str,
    now: datetime,
) -> list[int]:
    cutoff = _window_cutoff(window, now)
    stmt = (
        select(CashEventRow.balance_after_cents)
        .where(CashEventRow.strategy_name == strategy_name)
        .order_by(CashEventRow.occurred_at)
    )
    if cutoff is not None:
        stmt = stmt.where(CashEventRow.occurred_at >= cutoff)
    return [int(balance) for balance in per_env_session.scalars(stmt).all()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_queries.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/queries.py tests/test_eval_queries.py
git commit -m "feat(M5.5): resolved-trade + bankroll-series extraction queries

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: Snapshot writer + recompute

**Files:**
- Create: `core/eval/snapshot.py`
- Test: `tests/test_eval_snapshot.py`

`write_snapshot` inserts one `eval_metric_snapshot` row from an `EvalMetrics`. `recompute_strategy` computes and writes all three windows for one strategy (reading `τ` from `config_jsonb`). `recompute_all` does it for every strategy. None of these commit — the caller owns the transaction.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_eval_snapshot.py
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow, StrategyState as DbStrategyState
from core.db.models import EvalMetricSnapshotRow, SignalRow, StrategyInstanceRow
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, PositionSide, SignalOutcome
from core.eval.snapshot import recompute_all, recompute_strategy
from core.ledger import writer
from core.utils.time import utc_now

NOW = datetime(2026, 6, 2, 12, 0, tzinfo=UTC)


def _create_strategy(session: Session, name: str, config: dict[str, object]) -> None:
    now = utc_now()
    session.add(
        StrategyInstanceRow(
            name=name, enabled=True, state=DbStrategyState.SEEDED,
            bankroll_cents=0, initial_deposit_cents=0, bankroll_hwm_cents=0,
            hwm_reset_at=None, kelly_fraction=0.25, config_jsonb=config,
            consecutive_min_position_rejections=0,
            last_state_change_at=now, created_at=now, updated_at=now,
        )
    )
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "setup", AuditActor.USER, "rq")
    session.commit()


def _seed_resolution(shared: Session, ticker: str) -> None:
    shared.add(ReferenceMarketRow(
        ticker=ticker, series="S", title="t", settlement_source=None, settlement_ref=None,
        open_time=None, close_time=None, settlement_time=None, status="settled", raw_jsonb={}))
    shared.flush()
    shared.add(ContractResolutionRow(
        ticker=ticker, resolved_at=NOW, resolution=ContractResolution.YES,
        settlement_value=Decimal("1"), source_evidence_jsonb={}))
    shared.commit()


def _signal_and_position(per_env: Session, *, name: str, ticker: str, prob: str) -> None:
    sid = f"sig-{ticker}"
    per_env.add(SignalRow(
        id=sid, strategy_name=name, ticker=ticker, evaluated_at=utc_now(),
        prob_yes=Decimal(prob), confidence=Decimal("0.6"), features_snapshot_jsonb={},
        market_state_jsonb={}, outcome=SignalOutcome.ORDER_PLACED, rejection_reason=None))
    per_env.flush()
    pos, _ = writer.open_paper_position(
        per_env, strategy_name=name, order_ticker=ticker, side=PositionSide.YES, qty=10,
        price=Decimal("0.40"), cost_basis_cents=400, signal_id=sid, fees_cents=0,
        simulator_assumptions={}, actor=AuditActor.SCHEDULER, request_id="rq-open")
    writer.resolve_position(
        per_env, position=pos, resolution=ContractResolution.YES,
        settlement_value=Decimal("1"), actor=AuditActor.SCHEDULER, request_id="rq-res")
    per_env.commit()


def test_recompute_strategy_writes_three_windows(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_a"
    with Session(shared_engine) as shared:
        _seed_resolution(shared, "KX-A")
    per_env = per_env_session_factory()
    _create_strategy(per_env, name, {"posterior_tau": 0.5})
    _signal_and_position(per_env, name=name, ticker="KX-A", prob="0.6")

    with Session(shared_engine) as shared:
        recompute_strategy(per_env_session=per_env, shared_session=shared,
                           strategy_name=name, now=NOW)
        per_env.commit()

    rows = per_env.scalars(
        select(EvalMetricSnapshotRow).where(EvalMetricSnapshotRow.strategy_name == name)
    ).all()
    assert {r.window for r in rows} == {EvalWindow.D7, EvalWindow.D30, EvalWindow.ALL}
    all_window = next(r for r in rows if r.window == EvalWindow.ALL)
    assert all_window.n_trades == 1
    assert all_window.n_wins == 1
    assert all_window.brier_score == (0.6 - 1) ** 2  # 0.16
    assert all_window.pnl_cents == 600
    per_env.close()


def test_recompute_strategy_uses_config_tau(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "strat_tau"
    per_env = per_env_session_factory()
    _create_strategy(per_env, name, {"posterior_tau": 1.0})  # no trades -> prior from tau
    with Session(shared_engine) as shared:
        recompute_strategy(per_env_session=per_env, shared_session=shared,
                           strategy_name=name, now=NOW)
        per_env.commit()
    row = per_env.scalars(
        select(EvalMetricSnapshotRow).where(EvalMetricSnapshotRow.window == EvalWindow.ALL)
    ).one()
    assert row.n_trades == 0
    assert row.posterior_edge_ci_high == 1.96 * 1.0  # prior CI from tau=1.0
    per_env.close()


def test_recompute_all_covers_every_strategy(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    per_env = per_env_session_factory()
    _create_strategy(per_env, "s1", {})
    _create_strategy(per_env, "s2", {})
    with Session(shared_engine) as shared:
        recompute_all(per_env_session=per_env, shared_session=shared, now=NOW)
        per_env.commit()
    rows = per_env.scalars(select(EvalMetricSnapshotRow)).all()
    assert len(rows) == 6  # 2 strategies x 3 windows
    per_env.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_snapshot.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.eval.snapshot'`.

- [ ] **Step 3: Implement the writer + recompute**

```python
# core/eval/snapshot.py
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db.enums import EvalWindow
from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
from core.eval.metrics import EvalMetrics, compute_metrics
from core.eval.queries import bankroll_balance_series, resolved_trades

_WINDOWS: tuple[EvalWindow, ...] = (EvalWindow.D7, EvalWindow.D30, EvalWindow.ALL)
_DEFAULT_TAU = 0.5


def _strategy_tau(strategy: StrategyInstanceRow) -> float:
    raw = strategy.config_jsonb.get("posterior_tau", _DEFAULT_TAU)
    if isinstance(raw, (int, float)):
        return float(raw)
    return _DEFAULT_TAU


def write_snapshot(
    session: Session,
    *,
    strategy_name: str,
    window: EvalWindow,
    metrics: EvalMetrics,
    computed_at: datetime,
) -> EvalMetricSnapshotRow:
    row = EvalMetricSnapshotRow(
        id=str(uuid4()),
        strategy_name=strategy_name,
        computed_at=computed_at,
        window=window,
        n_trades=metrics.n_trades,
        n_wins=metrics.n_wins,
        hit_rate=metrics.hit_rate,
        brier_score=metrics.brier,
        log_loss=metrics.log_loss,
        pnl_cents=metrics.pnl_cents,
        sharpe_proxy=metrics.sharpe_proxy,
        max_drawdown_cents=metrics.max_drawdown_cents,
        posterior_edge_mean=metrics.posterior_edge_mean,
        posterior_edge_ci_low=metrics.posterior_edge_ci_low,
        posterior_edge_ci_high=metrics.posterior_edge_ci_high,
        calibration_bins_jsonb=[b.as_dict() for b in metrics.calibration_bins],
    )
    session.add(row)
    session.flush()
    return row


def recompute_strategy(
    *,
    per_env_session: Session,
    shared_session: Session,
    strategy_name: str,
    now: datetime,
) -> None:
    strategy = per_env_session.get(StrategyInstanceRow, strategy_name)
    if strategy is None:
        return
    tau = _strategy_tau(strategy)
    for window in _WINDOWS:
        trades = resolved_trades(
            per_env_session=per_env_session,
            shared_session=shared_session,
            strategy_name=strategy_name,
            window=window.value,
            now=now,
        )
        balances = bankroll_balance_series(
            per_env_session=per_env_session,
            strategy_name=strategy_name,
            window=window.value,
            now=now,
        )
        metrics = compute_metrics(trades, balances=balances, tau=tau)
        write_snapshot(
            per_env_session,
            strategy_name=strategy_name,
            window=window,
            metrics=metrics,
            computed_at=now,
        )


def recompute_all(
    *,
    per_env_session: Session,
    shared_session: Session,
    now: datetime,
) -> None:
    names = list(
        per_env_session.scalars(select(StrategyInstanceRow.name)).all()
    )
    for name in names:
        recompute_strategy(
            per_env_session=per_env_session,
            shared_session=shared_session,
            strategy_name=name,
            now=now,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_snapshot.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/eval/snapshot.py tests/test_eval_snapshot.py
git commit -m "feat(M5.5): eval snapshot writer + per-strategy/all recompute

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: Post-resolution recompute in the resolution tick

**Files:**
- Modify: `core/engine/resolution.py`
- Test: `tests/test_resolution_tick.py` (add a case)

After resolving positions, recompute snapshots for the strategies whose positions just resolved — in the **same** transaction (before the existing `commit()`), reusing the shared + per-env sessions the tick already holds.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_resolution_tick.py` (the imports `SignalRow`, `SignalOutcome`, `EvalMetricSnapshotRow`, `EvalWindow`, `Decimal`, `select` may need adding at the top — check and add any that are missing):

```python
def test_resolution_tick_writes_eval_snapshots(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    from decimal import Decimal

    from sqlalchemy import select

    from core.db.enums import EvalWindow
    from core.db.models import EvalMetricSnapshotRow, SignalRow
    from core.domain.enums import SignalOutcome

    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    ticker = "KX-EVAL"

    with Session(shared_engine) as shared:
        shared.add(ReferenceMarketRow(
            ticker=ticker, series="S", title="t", settlement_source=None, settlement_ref=None,
            open_time=None, close_time=None, settlement_time=None, status="settled", raw_jsonb={}))
        shared.flush()
        shared.add(ContractResolutionRow(
            ticker=ticker, resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
            resolution=ContractResolution.YES, settlement_value=Decimal("1"),
            source_evidence_jsonb={}))
        shared.commit()

    per_env = per_env_session_factory()
    name = "strat_a"
    _create_strategy(per_env, name)
    per_env.add(SignalRow(
        id="sig-eval", strategy_name=name, ticker=ticker, evaluated_at=utc_now(),
        prob_yes=Decimal("0.6"), confidence=Decimal("0.6"), features_snapshot_jsonb={},
        market_state_jsonb={}, outcome=SignalOutcome.ORDER_PLACED, rejection_reason=None))
    per_env.flush()
    writer.open_paper_position(
        per_env, strategy_name=name, order_ticker=ticker, side=PositionSide.YES, qty=10,
        price=Decimal("0.40"), cost_basis_cents=400, signal_id="sig-eval", fees_cents=0,
        simulator_assumptions={}, actor=AuditActor.SCHEDULER, request_id="rq-open")
    per_env.commit()

    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared, per_env_session=per_env, request_id="res-tick")
    assert stats["resolved"] == 1

    all_window = per_env.scalars(
        select(EvalMetricSnapshotRow).where(
            EvalMetricSnapshotRow.strategy_name == name,
            EvalMetricSnapshotRow.window == EvalWindow.ALL,
        )
    ).one()
    assert all_window.n_trades == 1
    assert all_window.pnl_cents == 600
    per_env.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_resolution_tick.py::test_resolution_tick_writes_eval_snapshots -v`
Expected: FAIL — `NoResultFound` (no `eval_metric_snapshot` rows written yet).

- [ ] **Step 3: Wire recompute into the tick**

In `core/engine/resolution.py`: add the import near the top — `from core.utils.time import utc_now` — then collect affected strategy names and recompute before the commit. Replace the resolve loop + commit (current lines, the `for position in open_positions:` block through `per_env_session.commit()`) with:

```python
        affected: set[str] = set()
        for position in open_positions:
            res = resolutions_by_ticker.get(position.ticker)
            if res is None:
                continue
            writer.resolve_position(
                per_env_session,
                position=position,
                resolution=ContractResolution(res.resolution),
                settlement_value=res.settlement_value,
                actor=AuditActor.SCHEDULER,
                request_id=tick_id,
            )
            affected.add(position.strategy_name)
            resolved += 1
        if affected:
            from core.eval.snapshot import recompute_strategy

            now = utc_now()
            for strategy_name in sorted(affected):
                recompute_strategy(
                    per_env_session=per_env_session,
                    shared_session=shared_session,
                    strategy_name=strategy_name,
                    now=now,
                )
    per_env_session.commit()
```

> Keep the existing structure otherwise: `affected`/recompute live inside the `if open_positions:` block (so they share its indentation); `per_env_session.commit()` stays at the outer level so it always runs. The `recompute_strategy` import is local to avoid a circular import (`core.eval.snapshot` imports models, not the engine, so a top-level import is also safe — local keeps the engine module lean).

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_resolution_tick.py -v`
Expected: PASS (the new case plus the two existing cases — existing ones write no snapshots because their positions have no signal/resolution-linked trades, but they still resolve correctly).

- [ ] **Step 5: Commit**

```bash
git add core/engine/resolution.py tests/test_resolution_tick.py
git commit -m "feat(M5.5): recompute eval snapshots after each resolution tick

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: Nightly recompute in the scheduler

**Files:**
- Modify: `core/scheduler.py`
- Test: `tests/test_scheduler.py` (add a case)

Add a `run_nightly_recompute()` method that recomputes all strategies in a fresh session pair, and a daily loop task that calls it. The method is what tests drive directly (the sleeping loop mirrors `_run_cycle_loop` and is not unit-tested, consistent with the existing pattern).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_run_nightly_recompute_writes_snapshots_for_all_strategies(
    per_env_sqlite_urls: tuple[str, str],
) -> None:
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session

    from core.db.enums import StrategyState as DbStrategyState
    from core.db.models import EvalMetricSnapshotRow, StrategyInstanceRow
    from core.domain.enums import AuditActor
    from core.ledger import writer
    from core.utils.time import utc_now

    shared_url, per_env_url = per_env_sqlite_urls
    settings = Settings(
        REQUIRE_DBS=False, CONTROL_PLANE_TOKEN="dev-token",
        DATABASE_URL_SHARED=shared_url, DATABASE_URL_PER_ENV=per_env_url,
        SCHEDULER_ENABLED=False,
    )
    engine = create_engine(per_env_url)
    with Session(engine) as session:
        now = utc_now()
        session.add(StrategyInstanceRow(
            name="s1", enabled=True, state=DbStrategyState.SEEDED, bankroll_cents=0,
            initial_deposit_cents=0, bankroll_hwm_cents=0, hwm_reset_at=None,
            kelly_fraction=0.25, config_jsonb={}, consecutive_min_position_rejections=0,
            last_state_change_at=now, created_at=now, updated_at=now))
        session.commit()
        writer.deposit(session, "s1", 100_00, "seed", AuditActor.USER, "rq")
        writer.activate_strategy(session, "s1", "setup", AuditActor.USER, "rq")
        session.commit()

    scheduler = Scheduler.create(
        settings, clock=FakeClock(start=datetime(2026, 6, 2, 12, 0, tzinfo=UTC)))
    scheduler.run_nightly_recompute()

    with Session(engine) as session:
        rows = session.scalars(select(EvalMetricSnapshotRow)).all()
    assert len(rows) == 3  # 1 strategy x 3 windows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_scheduler.py::test_run_nightly_recompute_writes_snapshots_for_all_strategies -v`
Expected: FAIL — `AttributeError: 'Scheduler' object has no attribute 'run_nightly_recompute'`.

- [ ] **Step 3: Add the method + nightly loop**

In `core/scheduler.py`: add a module constant near `_cycle_request_id` and the method on `Scheduler`. First add the constant after the existing helper functions:

```python
_NIGHTLY_INTERVAL_SECONDS = 86_400.0
```

Add the method to the `Scheduler` class (place it after `run_cycle`). `shared_session` and `per_env_session` are already imported at the top of `core/scheduler.py`; only `recompute_all` is a new local import:

```python
    def run_nightly_recompute(self) -> None:
        """Recompute eval metric snapshots for every strategy (PDD §8.4)."""
        from core.eval.snapshot import recompute_all

        now = self.clock.now()
        with shared_session(self.settings) as shared, per_env_session(self.settings) as per_env:
            recompute_all(per_env_session=per_env, shared_session=shared, now=now)
            per_env.commit()
```

Then add the loop task. In `start()`, after the existing `self._tasks.append(asyncio.create_task(self._run_cycle_loop()))`, add:

```python
        self._tasks.append(asyncio.create_task(self._run_nightly_loop()))
```

And add the loop method (mirrors `_run_cycle_loop`):

```python
    async def _run_nightly_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=_NIGHTLY_INTERVAL_SECONDS)
                return  # stop requested
            except TimeoutError:
                pass
            try:
                self.run_nightly_recompute()
            except Exception:
                logger.exception("nightly eval recompute failed")
```

> `_run_nightly_loop` waits up to `_NIGHTLY_INTERVAL_SECONDS` on the stop event each iteration: a `TimeoutError` means the interval elapsed (run the recompute), a clean return means stop was requested.

- [ ] **Step 4: Run test to verify it passes**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_scheduler.py -v`
Expected: PASS (new nightly test plus all existing scheduler tests).

- [ ] **Step 5: Run the full gate**

Run: `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add core/scheduler.py tests/test_scheduler.py
git commit -m "feat(M5.5): nightly eval recompute loop + run_nightly_recompute

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: End-to-end integration test (seed → open → resolve → eval)

**Files:**
- Create: `tests/test_eval_recompute_integration.py`

One test that exercises the whole M5 loop through the public seams: seed shared reference + resolution, seed a per-env strategy with a signal-linked open position, run the resolution tick, and assert both the realized `cash_event`/bankroll **and** the resulting `eval_metric_snapshot` rows. This is the design §12 / milestone "integration" verification.

- [ ] **Step 1: Write the test**

```python
# tests/test_eval_recompute_integration.py
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from core.db.enums import EvalWindow, PositionStatus
from core.db.enums import StrategyState as DbStrategyState
from core.db.models import (
    CashEventRow,
    EvalMetricSnapshotRow,
    PaperPositionRow,
    SignalRow,
    StrategyInstanceRow,
)
from core.db.shared_enums import ContractResolution
from core.db.shared_models import ContractResolutionRow, ReferenceMarketRow
from core.domain.enums import AuditActor, CashEventKind, PositionSide, SignalOutcome
from core.engine.resolution import run_resolution_tick
from core.ledger import writer
from core.utils.time import utc_now


def _create_strategy(session: Session, name: str) -> None:
    now = utc_now()
    session.add(StrategyInstanceRow(
        name=name, enabled=True, state=DbStrategyState.SEEDED, bankroll_cents=0,
        initial_deposit_cents=0, bankroll_hwm_cents=0, hwm_reset_at=None,
        kelly_fraction=0.25,
        config_jsonb={"min_bankroll_cents": 10_000, "max_input_age_seconds": 900,
                      "auto_resume_on_deposit": True, "posterior_tau": 0.5},
        consecutive_min_position_rejections=0,
        last_state_change_at=now, created_at=now, updated_at=now))
    session.commit()
    writer.deposit(session, name, 100_00, "seed", AuditActor.USER, "rq")
    writer.activate_strategy(session, name, "setup", AuditActor.USER, "rq")
    session.commit()


def test_full_loop_seed_open_resolve_eval(
    per_env_sqlite_urls: tuple[str, str],
    per_env_session_factory: sessionmaker[Session],
) -> None:
    shared_url, _ = per_env_sqlite_urls
    shared_engine = create_engine(shared_url)
    name = "weather_demo"
    win_ticker, lose_ticker = "KX-WIN", "KX-LOSE"

    # --- shared: two settled markets, one YES one NO ---
    with Session(shared_engine) as shared:
        for ticker, resolution, value in (
            (win_ticker, ContractResolution.YES, "1"),
            (lose_ticker, ContractResolution.NO, "0"),
        ):
            shared.add(ReferenceMarketRow(
                ticker=ticker, series="S", title="t", settlement_source=None,
                settlement_ref=None, open_time=None, close_time=None,
                settlement_time=None, status="settled", raw_jsonb={}))
            shared.flush()
            shared.add(ContractResolutionRow(
                ticker=ticker, resolved_at=datetime(2026, 6, 2, tzinfo=UTC),
                resolution=resolution, settlement_value=Decimal(value),
                source_evidence_jsonb={}))
        shared.commit()

    # --- per-env: strategy + two signal-linked YES positions ---
    per_env = per_env_session_factory()
    _create_strategy(per_env, name)
    for sid, ticker, prob in (
        ("sig-win", win_ticker, "0.6"),
        ("sig-lose", lose_ticker, "0.7"),
    ):
        per_env.add(SignalRow(
            id=sid, strategy_name=name, ticker=ticker, evaluated_at=utc_now(),
            prob_yes=Decimal(prob), confidence=Decimal("0.6"), features_snapshot_jsonb={},
            market_state_jsonb={}, outcome=SignalOutcome.ORDER_PLACED, rejection_reason=None))
        per_env.flush()
        writer.open_paper_position(
            per_env, strategy_name=name, order_ticker=ticker, side=PositionSide.YES, qty=10,
            price=Decimal("0.40"), cost_basis_cents=400, signal_id=sid, fees_cents=0,
            simulator_assumptions={}, actor=AuditActor.SCHEDULER, request_id="rq-open")
    per_env.commit()

    # --- resolution tick: settles + recomputes eval ---
    with Session(shared_engine) as shared:
        stats = run_resolution_tick(
            shared_session=shared, per_env_session=per_env, request_id="res-tick")
    assert stats["resolved"] == 2

    # ledger side: YES@0.40 win -> +600 ; YES@0.40 (market NO) lose -> -400 ; net +200
    strat = per_env.get(StrategyInstanceRow, name)
    assert strat is not None and strat.bankroll_cents == 100_00 + 200
    realized = [
        e for e in per_env.scalars(select(CashEventRow)).all()
        if e.kind == CashEventKind.REALIZED_PNL.value
    ]
    assert sorted(e.amount_cents for e in realized) == [-400, 600]
    assert all(
        p.status == PositionStatus.RESOLVED
        for p in per_env.scalars(select(PaperPositionRow)).all()
    )

    # eval side: 'all' window snapshot has 2 trades, 1 win, hand-checked Brier
    snap = per_env.scalars(
        select(EvalMetricSnapshotRow).where(
            EvalMetricSnapshotRow.strategy_name == name,
            EvalMetricSnapshotRow.window == EvalWindow.ALL,
        )
    ).one()
    assert snap.n_trades == 2
    assert snap.n_wins == 1
    assert snap.hit_rate == 0.5
    # win: (0.6-1)^2=0.16 ; lose: market NO so outcome_yes=0, (0.7-0)^2=0.49
    assert snap.brier_score == (0.16 + 0.49) / 2
    assert snap.pnl_cents == 200
    per_env.close()
```

- [ ] **Step 2: Run the integration test**

Run: `REQUIRE_DBS=0 ./.venv/bin/pytest tests/test_eval_recompute_integration.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_eval_recompute_integration.py
git commit -m "test(M5.5): end-to-end seed -> open -> resolve -> eval integration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Final verification (whole plan)

- [ ] **Full gate:** `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 ./.venv/bin/pytest -q` — all green.
- [ ] **Migration applies cleanly:** every DB test runs `run_upgrade("per_env", ...)` through `003`; `tests/test_eval_snapshot_model.py` proves the table round-trips.
- [ ] **Purity intact:** `core/eval/metrics.py` and `core/eval/posterior.py` have no I/O, no clock, no DB imports. `tests/test_ledger_purity_guard.py` and `tests/test_strategy_purity_guard.py` stay green.
- [ ] **Eval units vs hand-computed fixtures:** Brier, log-loss, hit-rate, posterior — incl. `n=0` (prior), single-trade (wide CI), all-wins/all-losses — pass (`tests/test_eval_metrics.py`, `tests/test_eval_posterior.py`, `tests/test_eval_calibration.py`).
- [ ] **Integration green:** `tests/test_eval_recompute_integration.py` proves seed → open → resolve → tick → expected `realized_pnl` `cash_event` **and** `eval_metric_snapshot` rows.
- [ ] **Ledger invariant unaffected:** `tests/test_ledger_invariant_property.py` still passes (eval writes touch no `cash_event`/bankroll).
- [ ] Update `docs/milestones/M5-eval/milestone.md`: check off **M5.4** and **M5.5**; leave M5.6/M5.7 unchecked.

## Self-review notes (carried for the implementer)

- **`config_jsonb["posterior_tau"]` key name** — chosen as the per-strategy `τ` override (design §6/§10). It is new; no seed strategy sets it yet, so all strategies use the `0.5` default until an operator adds it. If a different key is later standardized, change `_strategy_tau` only.
- **`outcome_yes` source** — read from the shared `contract_resolution`, *not* derived from position side + P&L sign. This keeps calibration honest for either side and correctly excludes voids. The trade-extraction query therefore requires the shared session; `recompute_strategy`/`recompute_all` pass it through, and both call sites (resolution tick, nightly loop) already hold a shared session.
- **Calibration bins storage** — a JSON column on the snapshot, extending PDD §5.2's illustrative column list. The M5.6 read API will surface `calibration_bins_jsonb` directly.
- **Posterior `n==1` interpretation** — uses prior-scale variance `τ²` (not a tiny epsilon floor) so a single trade yields a wide, zero-spanning CI rather than false confidence. This is the concrete, statistically-defensible reading of design §6's "finite and wide" requirement; the epsilon floor is reserved for the `n≥2` all-identical-ROI divide-by-zero guard.
- **Sharpe / variance convention** — sample stdev/variance (ddof=1) throughout (`statistics.stdev`/`statistics.variance`); `sharpe_proxy` is `None` for `n<2` or zero variance.
- **Nightly loop** — `_run_nightly_loop` sleeps `_NIGHTLY_INTERVAL_SECONDS` between runs and is not unit-tested directly (mirrors the untested `_run_cycle_loop`); `run_nightly_recompute()` is the tested seam. If a precise wall-clock nightly time is later required, replace the fixed interval with a next-midnight computation — out of scope here.
- **Two windows can be empty while `all` is populated** — `7d`/`30d` snapshots legitimately have `n_trades=0` (and `None` rate metrics, prior posterior) when no trade closed in the window; this is expected, not a bug.
</content>
</invoke>
