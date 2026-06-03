# M6: Functional Paper Trading Soak

> Turn the implemented ingestion -> engine -> paper executor -> resolution -> eval spine into a live staging system that can run unattended for two weeks, with explicit starting capital, observable source health, bounded paper risk, and a runbook for intervention.

## Current State

As of 2026-06-03, `staging` has the M3-M5 code paths merged and the deployed staging API is healthy:

- API `/healthz`: shared DB `ok`, per-env DB `ok`, scheduler cycle `ok`.
- UI `/healthz`: `ok`.
- `/v1/sources`: `open_meteo` enabled and healthy; `kalshi_markets` and `kalshi_resolution` disabled because Kalshi credentials are not configured.
- `/v1/strategies`: both seeded weather strategies are active with `bankrollCents=10000`.
- `/v1/signals`, `/v1/positions`: empty.
- `/v1/eval`: both strategies have `nTrades=0`.

So the remaining work is not another broad architecture milestone. It is an operational readiness slice: configure real market ingestion, make the paper bankroll/profile explicit, prove one end-to-end paper cycle, then soak and watch.

## Goal

Run `staging` in live paper mode for two weeks with:

- Kalshi market and resolution sources enabled and healthy.
- Open-Meteo forecasts continuing to ingest.
- Strategies emitting persisted signals from live market + forecast data.
- Paper orders placed only through the executor/ledger path.
- Resolved positions updating realized P&L and eval snapshots.
- Operator-visible bankroll, positions, source health, signals, and eval metrics.
- Clear controls for pause/resume, bankroll adjustment, and soak abort.

## Non-Goals

- No real-money Kalshi executor.
- No production `main` promotion until after the soak review.
- No backtest replay clock.
- No plugin manifest system.
- No automatic top-up or auto-rebalancing. Recovery remains operator-initiated.

## Readiness Definition

Functional paper trading is ready to soak when all of these are true on deployed staging:

- `GET /healthz` returns `status=ok` with scheduler cycle `ok`.
- `GET /v1/sources` shows `open_meteo`, `kalshi_markets`, and `kalshi_resolution` enabled; disabled is acceptable only for a source deliberately parked in the runbook.
- Kalshi market rows and orderbook snapshots are landing in shared DB.
- At least one engine tick has evaluated at least one live Kalshi weather market and written a signal row.
- Paper order placement has either occurred naturally or been proven by a controlled staging-only canary fixture/test path.
- Starting paper bankroll and strategy thresholds are visible in API/UI and can be changed without direct DB edits.
- The operator can pause the system and individual strategies from the UI/API.
- Daily soak notes have a queryable source of truth: health, signals, positions, cash events, and eval roster.

## Plan

### M6.1 Paper Bankroll Profile

Add an explicit paper-capital configuration layer.

Implementation:

- Add settings for default initial paper bankroll, e.g. `PAPER_INITIAL_BANKROLL_CENTS`.
- Add optional per-strategy overrides, e.g. `PAPER_STRATEGY_BANKROLL_CENTS_JSON`.
- Keep startup idempotent: settings apply only when creating missing strategy rows, never silently rewrite an existing ledger.
- Set `initial_deposit_cents` and initial `bankroll_hwm_cents` to the configured starting bankroll for newly seeded strategies.
- Preserve existing ledger invariant: all bankroll changes still go through `cash_event` + `audit_event`.
- Add tests for default seed, per-strategy override, idempotency, and initial HWM.

Operator adjustment:

- Add a guarded "set starting bankroll" control for pre-soak use only.
- Allow it only when the strategy has no signals, fills, or positions.
- Implement it as a ledger delta deposit/withdraw plus audit event.
- Update `initial_deposit_cents` and HWM baseline only in this pre-trade state.
- After the first signal/fill exists, use normal deposit/withdraw only.

Acceptance:

- Fresh staging DB seeds each strategy with the configured bankroll.
- Current staging can be reset or adjusted to the desired starting bankroll without manual SQL.
- API/UI shows the selected bankroll baseline.

### M6.2 Strategy Soak Profile

Make live soak thresholds explicit and reviewable.

Implementation:

- Move seeded strategy thresholds into a named profile documented in code and `.env.example`.
- Support per-strategy config overrides at seed time without hand-editing DB JSON.
- Include at least:
  - `confidenceFloor`
  - `disagreementThreshold`
  - `spreadMarginMultiplier`
  - `wideSpreadThreshold`
  - `max_input_age_seconds`
  - `exposureCapPct`
  - `correlationCapPct`
- Add a read-only API/UI display of effective strategy config if not already visible enough.

Initial soak recommendation:

- Start with small bankroll and conservative exposure caps.
- Prefer threshold values that produce occasional signals, but keep sizing bounded.
- If the existing strategies remain too quiet, add a documented staging-only canary strategy or debug mode rather than silently weakening production defaults.

Acceptance:

- The soak profile can be reviewed in git.
- Deploying staging from a clean DB produces the same effective config every time.
- Existing staged ledgers are not mutated automatically by startup config changes.

### M6.3 Kalshi Source Enablement

Turn on live market and resolution ingestion in staging.

Operations:

- Configure Coolify env vars:
  - `KALSHI_API_KEY_ID`
  - `KALSHI_PRIVATE_KEY`
  - `KALSHI_API_BASE`
  - `KALSHI_SERIES_PREFIXES`
- Keep using demo/sandbox API if available and appropriate for paper soak.
- Confirm the selected series are exact Kalshi `series_ticker` values and map to seeded weather locations.
- Redeploy API after env changes.

Code hardening if needed:

- Improve source health messages when credentials are absent, malformed, or unauthorized.
- Add a startup/operator checklist that distinguishes disabled, degraded, and healthy sources.
- Check TLS certificate chain from normal `curl`; local verification currently required `-k`, which is fine for diagnosis but not for monitoring.

Acceptance:

- `/v1/sources` shows `kalshi_markets` enabled with a recent success.
- `reference_market` and `raw_market_snapshot` rows are increasing.
- `kalshi_resolution` is enabled and not failing all candidate fetches.

### M6.4 End-to-End Trading Verification

Prove the automated path before starting the clock on the soak.

Checks:

- Run the backend gate:
  - `./.venv/bin/ruff check .`
  - `./.venv/bin/mypy core tests`
  - `REQUIRE_DBS=0 pytest -q`
- Run the UI gate:
  - `cd ui && npm run check && npm run lint && npm run test && npm run build`
- On staging:
  - verify `/healthz`
  - verify `/v1/sources`
  - verify `/v1/strategies`
  - verify `/v1/signals?limit=20`
  - verify `/v1/positions?limit=20`
  - verify `/v1/eval`

Functional proof:

- Let the scheduler run long enough to ingest Open-Meteo and Kalshi in the same cycle.
- Confirm feature rows are computed for the selected markets.
- Confirm engine ticks write either orders or explicit rejection signals.
- If no strategy naturally emits a trade within the pre-soak window, use a controlled staging-only canary path to place one tiny paper order through the normal executor/ledger stack.
- Do not start the two-week soak until the normal paper executor path has written at least one position/fill in staging or a canary has proven that path.

Acceptance:

- Source -> feature -> strategy -> risk -> paper executor -> ledger path is proven on deployed staging.
- Rejections are understandable when no order is placed.
- The dashboard shows live signals/positions without falling back to mock state.

### M6.5 Soak Observability

Add enough monitoring to make the two weeks useful.

Minimum daily snapshot:

- Source status and last success timestamps.
- Scheduler cycle health.
- Number of signals by strategy and outcome.
- Open positions by strategy.
- Realized/unrealized P&L.
- Cash events.
- Eval roster metrics.
- Any source errors or stale input rejections.

Implementation options:

- Add a lightweight `scripts/staging_soak_snapshot.py` that prints the above via API.
- Or add a read-only `/v1/soak-summary` endpoint if the query is useful in UI too.
- Add a docs runbook with the exact commands and expected thresholds.

Acceptance:

- One command produces a human-readable daily summary.
- Summary output does not require direct DB access.
- Soak notes can be compared day over day.

### M6.6 Risk Guardrails

Keep the soak boring in the best possible way.

Guardrails:

- Use paper-only executor.
- Keep real-money executor unavailable or disabled by construction.
- Cap per-strategy exposure.
- Cap global exposure.
- Preserve stale-input rejection.
- Keep kill switch tested and visible.
- Add a maximum paper order notional if current Kelly sizing can exceed the intended soak size.
- Add alert/runbook triggers:
  - source degraded for more than two cycles
  - scheduler cycle error
  - no Kalshi snapshots for more than expected cadence
  - positions open past expected settlement window
  - unexpected 5xx from API

Acceptance:

- A bad source state produces rejections, not trades.
- Operator can stop all trading immediately.
- A single unexpected strategy signal cannot consume more than the configured paper cap.

### M6.7 Two-Week Soak Runbook

Write the operational runbook before starting.

Runbook sections:

- Start date/time and target end date/time.
- Exact staging URL and API health URLs.
- Current git SHA and deploy timestamp.
- Paper bankroll per strategy.
- Strategy config profile.
- Kalshi series monitored.
- Daily check command.
- Intervention rules:
  - when to pause a strategy
  - when to pause the system
  - when to redeploy
  - when to discard/restart soak
- End-of-soak review template:
  - data completeness
  - signal count
  - order count
  - realized P&L
  - calibration
  - posterior edge
  - source failure summary
  - bugs/follow-ups

Acceptance:

- The runbook lives in `docs/operations/`.
- The soak can be handed to another operator without extra oral tradition.

## Suggested PR Slices

1. **M6.1: configurable paper bankroll seed**
   - Settings, seed logic, HWM baseline, tests, `.env.example`, docs.

2. **M6.2: strategy soak profile and config visibility**
   - Seed config overrides, API/UI visibility as needed, tests.

3. **M6.3: soak observability script/runbook**
   - API-based daily summary script, docs, no DB secrets required.

4. **M6.4: staging source enablement and first-cycle verification**
   - Coolify env setup, deploy, source health proof, first signal/order proof.

5. **M6.5: soak start checklist**
   - Record baseline, start date, bankroll/profile, and first daily snapshot.

## Open Decisions

- Desired starting bankroll per strategy for the soak.
- Whether to reset current staging per-env DB before the soak or adjust the existing empty ledger in place.
- Whether to add a staging-only canary strategy/debug trade path if real strategies are too quiet.
- Whether the two-week soak should use Kalshi demo/sandbox API or production read-only market data with paper execution.
- Expected source cadence for the soak: hourly is simplest with current scheduler behavior; faster Kalshi polling requires scheduler cadence changes.

## Decision Log

- M6.1: Initial high-water mark equals the initial paper bankroll for newly seeded strategies.
- M6.1: `PAPER_INITIAL_BANKROLL_CENTS` and `PAPER_STRATEGY_BANKROLL_CENTS_JSON` apply only when creating missing strategy rows. Startup skips existing rows and never rewrites an existing ledger.

## Verification Commands

Local:

```bash
./.venv/bin/ruff check .
./.venv/bin/mypy core tests
REQUIRE_DBS=0 ./.venv/bin/pytest -q
cd ui && npm run check && npm run lint && npm run test && npm run build
```

Staging:

```bash
curl https://api.staging-event-market.critterhaus.net/healthz
curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  https://api.staging-event-market.critterhaus.net/v1/sources
curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "https://api.staging-event-market.critterhaus.net/v1/signals?limit=20"
curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "https://api.staging-event-market.critterhaus.net/v1/positions?limit=20"
curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  https://api.staging-event-market.critterhaus.net/v1/eval
```

## Completion Criteria

M6 is complete when:

- The soak has run for two weeks or has been deliberately stopped with documented cause.
- Daily summaries exist for the soak window.
- At least one live-data signal path has been exercised.
- If trades occurred, resolution and eval snapshots updated as expected.
- Bugs/follow-ups are filed and prioritized.
- A go/no-go note exists for continuing staging, resetting and rerunning, or preparing a later production paper deployment.
