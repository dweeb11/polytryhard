# M3 design — Ingestion (Kalshi markets + Open-Meteo forecasts)

> Real raw market and forecast data lands in the shared DB on a schedule, with health visible from the dashboard. This starts the historical record that future backtests need.

**Status:** Approved design, pre-implementation-plan.
**Depends on:** M2 (ledger + `/v1/*` control plane + hybrid live/mock UI), merged to `staging`.
**PDD references:** §3.2–§3.4 (deploy topology, core vs plugins, repo layout), §4.1 (live tick), §5.1/§5.3 (shared schema + invariants), §6 (fail-closed), §8.3 (contract tests), §9 (stack).

---

## 1. Goal & rationale

M2 delivered the safety floor and control plane. The remaining MVP work (PDD §1.2: "paper-trade Kalshi end-to-end on weather markets") is essentially the entire engine: clock, plugin registry/contracts, ingestion, feature providers, strategy engine, risk/sizing, paper executor, scheduler, eval metrics, WebSocket push. That is far more than one milestone.

M3 takes the **ingestion-first** slice. Rationale: the PDD's own open questions (§10) flag that Kalshi's history API is limited and "we may need to start recording snapshots forward." Forecast history is likewise only obtainable going forward at fidelity. So the sooner real data is landing in the shared DB, the sooner there is a historical record to backtest against later. M3 starts that clock ticking.

The deterministic engine spine (strategies → sizing → paper executor → ledger, driven by a replay clock) is the **M4** slice and is explicitly out of scope here.

## 2. Scope

### In scope

- **Engine spine (minimal):** `Clock` interface + `WallClock`; typed `IngestionSource` ABC; explicit source registry; asyncio `Scheduler` wired into the FastAPI lifespan.
- **Shared-DB schema:** first real shared migration (`002`) adding `reference_location`, `reference_market`, `raw_market_snapshot`, `raw_forecast_run`, `source_run`.
- **Two sources:**
  - `kalshi_markets` — discovery (enumerate active weather markets → upsert `reference_market`) + snapshot (orderbook + last trade → `raw_market_snapshot`). RSA-signed auth via env; fail-closed (`degraded`) when unconfigured.
  - `open_meteo` — GFS + ECMWF ensemble forecasts per curated location → `raw_forecast_run`. Public API, no auth.
- **Reference seed:** curated `reference_location` list (cities + lat/lon/timezone), idempotent upsert on startup.
- **Health surfacing:** `GET /v1/sources` REST endpoint + read-only **Source Health** UI panel; OpenAPI → TS regen.
- **Tests:** recorded cassettes (parse-correctly contract tests); unit tests (health transitions, scheduler interval logic with fake clock, discovery upsert, RSA signing); one integration test (scheduler → cassette → rows in test-Postgres).

### Out of scope (later milestones)

- Feature providers, strategies, risk/sizing, paper executor, eval metrics (M4+).
- Replay clock (arrives with the backtest milestone).
- Dirty-set dependency propagation (no features/strategies to propagate to yet).
- WebSocket push (source health read via REST poll for now).
- Tunable circuit breakers per PDD §6.1 (M3 ships a simple consecutive-failure → degraded mechanism).
- NWS source (M4+; Open-Meteo covers GFS + ECMWF in M3).
- Manifest/filesystem plugin discovery (Approach C: typed contract + explicit registration; discovery added when the third plugin type lands).

## 3. Architectural decisions

### 3.1 Ingestion-first over engine-spine-first

Chosen so the historical record begins accumulating immediately. Trade-off accepted: the satisfying end-to-end paper-trade is deferred to M4, and the flakiest (external-API) work comes first.

### 3.2 Two sources: Kalshi + Open-Meteo

Open-Meteo exposes both GFS and ECMWF ensemble through one HTTP API, collapsing two of the four PDD sources into one plugin. Kalshi gives market history; Open-Meteo gives the ensemble-forecast history a weather strategy needs to backtest. NWS deferred to M4.

### 3.3 Approach C — typed contract, explicit registration

Sources subclass a real, typed `IngestionSource` ABC (declares `name`, `schedule`, `async fetch`), but registration is an explicit list in code — no `manifest.toml`, no filesystem discovery yet. The typed contract is the load-bearing seam the scheduler talks to and that features/strategies will mirror; discovery/manifest machinery only pays off with many plugins and is deferred. Matches the existing explicit, typed structure of `core/ledger` and `core/domain`.

### 3.4 Kalshi credentials are config, fail-closed

Credentials (`KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY`, `KALSHI_API_BASE`) come from env vars. Missing/invalid → the source reports `degraded`, the scheduler logs it, and the app still boots. Dev and PR CI run on recorded cassettes; no live network in CI. This honors PDD §2.1 (fail closed) and §9 (secrets via env, never committed).

### 3.5 Reference data: seeded locations + discovered markets

Locations are a small curated seed file (stable). Markets are discovered automatically: the Kalshi source enumerates currently-active markets within configured weather series and upserts them into `reference_market`, so daily contracts refresh without manual ticker editing.

### 3.6 Health surfacing depth: REST + UI

`/v1/sources` plus a read-only Source Health panel closes the loop on "is ingestion running?" from the dashboard, rather than requiring DB/log inspection. M3 surfaces ingestion *health*, not data *content* — the readable aggregated forecast view (e.g. a "Houston 7-day" card) is a feature-layer concern (`ensemble_mean_temp`) and arrives in a later milestone. Raw rows remain queryable directly for eyeballing.

## 4. Engine spine

```
core/
  clock.py        Clock protocol: now() -> datetime (UTC).  WallClock impl.
  contracts/
    source.py     IngestionSource ABC: name; schedule (interval secs);
                  async fetch(clock, ctx) -> FetchResult
  sources/
    registry.py   explicit list [KalshiMarkets(), OpenMeteo()]; enabled filter
    seed.py       reference_location curated seed; idempotent upsert
  scheduler.py    asyncio supervisor: per-source loop on its interval →
                  fetch → persist raw rows → record source_run → update health;
                  consecutive-failure → degraded; started/stopped via FastAPI lifespan
```

- `fetch(clock, ctx)` returns a typed `FetchResult` (raw records + count + optional discovery upserts). The **scheduler**, not the source, owns DB writes and health bookkeeping — sources do external I/O only; persistence is centralized.
- Each source declares its own `schedule` (Kalshi snapshots more frequent than forecast runs).
- `ctx` carries `request_id` (PDD §6.1 — one ID per tick), the shared-DB session factory, and source config (env-derived).
- Failure handling: N consecutive `fetch` failures → source marked `degraded`, `last_error` recorded; scheduler keeps the loop alive and retries on the next interval. No crash, no blind tight-retry.
- Only the live/wall clock is exercised in M3, but sources take `clock` as a parameter so the replay clock drops in later without signature changes.

## 5. Shared-DB schema (additive migration `002`)

All append-only, all `as_of`-stamped (PDD §5.3 — `as_of` is the load-bearing look-ahead defense). Additive-only per shared-migration discipline.

- **`reference_location`** — `id, station_code, name, lat, lon, timezone, source`. Seeded.
- **`reference_market`** — `ticker PK, series, title, settlement_source, settlement_ref, open_time, close_time, settlement_time, status, raw_jsonb`. Upserted by Kalshi discovery.
- **`raw_market_snapshot`** — `id, ticker FK, as_of, bid_yes, ask_yes, mid_yes, bid_size, ask_size, last_trade_price, last_trade_size, source_run_id, raw_jsonb`; `INDEX (ticker, as_of DESC)`.
- **`raw_forecast_run`** — `id, source ENUM('gfs','ecmwf'), run_time, ingested_at, location_id FK, valid_window_start, valid_window_end, variable, value, ensemble_member NULL, raw_jsonb`; `INDEX (source, location_id, variable, run_time DESC)`.
- **`source_run`** — health/run log: `id, source_name, started_at, finished_at, status ENUM('ok','degraded','error'), rows_written, error_text NULL, request_id`. Backing store for `/v1/sources`.

Deferred (land with their consuming milestones): `feature_value`, `rubric_score`, `raw_news_article`, `contract_resolution`. Keeping `002` honest to what M3 actually writes.

## 6. The two sources + reference data

### `reference_location` seed

`core/sources/seed.py`, mirroring the existing ledger seed pattern. A curated city list — Houston, NYC, Chicago, Austin, Miami, LA — each with lat/lon/timezone/station. Idempotent upsert on startup.

### `kalshi_markets`

- Config from env: `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY` (RSA), `KALSHI_API_BASE` (prod vs demo). Missing/invalid → `degraded`, app still boots.
- **Discovery step:** enumerate active markets in configured weather series (config: series prefixes), upsert into `reference_market`.
- **Snapshot step:** for each active reference market, fetch orderbook + last trade → `raw_market_snapshot` rows, `as_of = clock.now()`.
- RSA request signing in a small `kalshi/auth.py` helper; the key is never logged.

### `open_meteo`

- No auth (public API). For each `reference_location`, request GFS + ECMWF ensemble for the temperature variable(s) → `raw_forecast_run` rows (one per member/day/variable), `run_time` from the API payload, `as_of = clock.now()`.
- Emits distinct `source='gfs'` and `source='ecmwf'` rows from the one plugin (plugin name is `open_meteo`; rows are tagged by model).

## 7. Health surfacing

- **`GET /v1/sources`** (bearer-auth, read-only) returns one entry per registered source from the latest `source_run` rows: `name, enabled, status ('ok'|'degraded'|'error'), last_run_at, last_success_at, rows_last_run, last_error`. Fail-closed display: unknown fields render as `—`, never `0`.
- **OpenAPI → TS regen** runs; the existing CI drift check covers the new schema.
- **UI Source Health panel** (read-only, under the existing `/settings` area or a `/sources` view): a table of sources with a status pill, last-success age, rows-last-run, and last error. Renders explicit loading/empty/error states. Works in both live (real `/v1/sources`) and mock (fixture) mode per the existing hybrid pattern.

## 8. Testing (PDD §8.3)

- **Recorded contract tests** — cassettes for Kalshi + Open-Meteo; the source parses a recorded response into expected raw rows. No live network in PR CI.
- **Unit tests** — source-health transitions (ok → degraded after N failures → ok on recovery); scheduler interval logic driven by a fake clock; Kalshi discovery upsert (insert new + update existing); RSA signing helper produces stable headers from a test key.
- **Integration test** — testcontainers Postgres (existing pattern): run the scheduler for one source against a cassette; assert raw rows + a `source_run` row land in the shared DB with `as_of` set.
- **Ledger AST purity guard stays green** — new source modules write only to the shared DB and never import `core/ledger` or touch `bankroll_cents`, so `tests/test_ledger_purity_guard.py` is untouched.

## 9. PR slicing (one concern each, ordered)

| # | PR | Concern |
|---|----|---------|
| M3.1 | Shared schema `002` — reference + raw + `source_run` tables, SQLAlchemy models | Backend/migration |
| M3.2 | `Clock` interface + `WallClock` | Backend |
| M3.3 | `IngestionSource` ABC + explicit source registry | Backend |
| M3.4 | Scheduler (asyncio supervisor, health/breaker) + FastAPI lifespan wiring | Backend |
| M3.5 | `reference_location` seed + Kalshi discovery (+ cassette tests) | Backend domain |
| M3.6 | Kalshi snapshot source (auth/signing, cassette tests) | Backend domain |
| M3.7 | Open-Meteo source (GFS+ECMWF, cassette tests) | Backend domain |
| M3.8 | `/v1/sources` endpoint + OpenAPI regen | Backend/API |
| M3.9 | UI Source Health panel | UI |

Nine slices, each independently reviewable and roughly within the ~300-line target. Tests ride with the slice whose behavior they lock.

## 10. Invariants honored

- Every raw row is `as_of`-stamped (look-ahead defense, PDD §5.3).
- Shared migration `002` is additive-only (PDD §5.3 #3).
- Sources fail closed to `degraded` and never crash the app (PDD §2.1, §6).
- `request_id` flows through each ingestion tick (PDD §6.1).
- No money/ledger code touched — M3 writes only to the shared DB; the ledger AST guard stays green (PDD §7.1).
- Secrets via env vars only; `.env.example` gains Kalshi entries (PDD §9).

## 11. Open questions carried into implementation

- **Kalshi API specifics** — confirm the current auth scheme (key ID + RSA signing) and the exact market/orderbook endpoints + which weather series prefixes to configure. Provisioned before live run; cassettes drive dev/CI until then.
- **Open-Meteo ensemble endpoint** — confirm the ensemble API URL, model names, and the temperature variable(s) and forecast horizon to request per location.
- **Schedule cadences** — concrete intervals for Kalshi snapshots vs forecast runs (forecast model runs are a few times daily; market snapshots more frequent).
- **`source_run` retention** — append-only for M3; a retention/rollup policy can come later if the table grows.
