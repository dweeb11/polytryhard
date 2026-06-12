# M6 Paper Trading Soak Runbook

This runbook is for the two-week staging paper-trading soak. Execution remains
paper-only; do not enable real-money execution during M6.

## Start Record

- Start time: TBD
- Target end time: TBD
- Staging API: `https://api.staging-event-market.critterhaus.net`
- Staging UI: `https://staging-event-market.critterhaus.net`
- Git SHA: record at soak start
- Deploy timestamp: record at soak start

## Daily Snapshot

Run once per operating day:

```bash
SOAK_API_BASE_URL=https://api.staging-event-market.critterhaus.net \
SOAK_API_TOKEN=$CONTROL_PLANE_TOKEN \
python scripts/staging_soak_snapshot.py
```

Save the output in the soak notes for that date. The script reads only API
endpoints; it does not require direct database access.

For scheduled runs, let the script save the note, raw JSON, and repeated-check
state automatically:

```bash
SOAK_API_BASE_URL=https://api.staging-event-market.critterhaus.net \
SOAK_API_TOKEN=$CONTROL_PLANE_TOKEN \
python scripts/staging_soak_snapshot.py \
  --write-notes \
  --notes-dir docs/operations/soak-notes \
  --fail-on-intervention
```

Exit codes:

- `0`: snapshot completed and no intervention trigger was found.
- `1`: snapshot collection failed.
- `2`: snapshot completed, but at least one runbook intervention trigger was
  found.

If a source or strategy is deliberately parked in the daily notes, include that
exception in the scheduled command so automation does not keep flagging the
known state:

```bash
python scripts/staging_soak_snapshot.py \
  --write-notes \
  --parked-source kalshi_resolution \
  --paused-strategy weather_ensemble_disagreement \
  --fail-on-intervention
```

The automation reports and records intervention triggers only. It must not pause
strategies, pause the system, redeploy, or restart the soak clock without an
operator decision during M6.

The snapshot includes:

- API, database, and scheduler health.
- Source status and last success timestamps.
- Strategy state, bankroll, HWM, and Kelly fraction.
- Latest signal counts by strategy and outcome.
- Latest positions and P&L summaries.
- Recent cash events by strategy.
- Eval roster metrics.

## Expected Healthy State

- `/healthz` returns `status=ok`.
- Scheduler cycle is `ok` after the first cycle completes.
- `open_meteo` is enabled and healthy.
- `kalshi_markets` and `kalshi_resolution` are enabled for the soak, unless a
  source is deliberately parked in the notes.
- Strategy states are `active` unless deliberately paused.
- Stale inputs produce rejected signals, not orders.

## Intervention Rules

Pause a strategy when:

- It produces unexpected order volume.
- It repeatedly rejects for a reason that indicates bad config rather than
  temporary source staleness.
- Its open positions exceed the intended soak exposure.

Pause the system when:

- A source is degraded for more than two scheduler cycles.
- Scheduler cycle health reports `error`.
- The API returns unexpected 5xx responses during daily checks.
- Any evidence suggests real-money execution could be active.

Discard and restart the soak clock when:

- Starting bankroll/profile was wrong after the first signal.
- The normal paper executor path was bypassed for a proof trade.
- Source data was unavailable for a material part of the soak window.

## End-of-Soak Review

Record:

- Actual start and end timestamps.
- Data completeness by source.
- Signal count by strategy and outcome.
- Order and position count.
- Realized and unrealized P&L.
- Calibration and posterior edge summary.
- Source failure summary.
- Bugs and follow-up issues.
- Go/no-go recommendation for another staging soak or later production paper
  deployment.
