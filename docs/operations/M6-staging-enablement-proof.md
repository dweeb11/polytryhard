# M6 Staging Enablement and Proof

This checklist is the final pre-soak operating procedure for proving staging is
ready for the M6 paper-trading soak. It does not enable real-money execution.

## Preconditions

- PRs for M6.1-M6.4 are reviewed and merged to `staging`.
- API and UI are redeployed from the latest `staging` SHA.
- `CONTROL_PLANE_TOKEN` is available to the operator.
- Staging paper bankroll is set through the guarded API path, not direct SQL.

## Coolify Environment

Set or confirm these API environment variables:

```env
KALSHI_API_KEY_ID=...
KALSHI_PRIVATE_KEY=...
KALSHI_API_BASE=https://api.elections.kalshi.com
KALSHI_SERIES_PREFIXES=KXHIGHNY
PAPER_INITIAL_BANKROLL_CENTS=10000
PAPER_STRATEGY_BANKROLL_CENTS_JSON={}
SCHEDULER_ENABLED=1
```

Use Kalshi demo/sandbox credentials when available. Production market data is
acceptable only because execution remains paper-only.

## Deploy

1. Redeploy the API service.
2. Redeploy the UI service if UI artifacts changed.
3. Record the deployed git SHA and deploy timestamp in the soak notes.

## API Checks

```bash
API=https://api.staging-event-market.critterhaus.net

curl "$API/healthz"

curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "$API/v1/sources"

curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "$API/v1/strategies"

curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "$API/v1/signals?limit=20"

curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "$API/v1/positions?limit=20"

curl -H "Authorization: Bearer $CONTROL_PLANE_TOKEN" \
  "$API/v1/eval"
```

Expected:

- `/healthz` is `ok`.
- Scheduler cycle is `ok` after one cycle.
- `open_meteo`, `kalshi_markets`, and `kalshi_resolution` are enabled unless a
  source is deliberately parked in the notes.
- Strategy bankroll and HWM match the selected starting baseline.
- Strategy config is visible in `/v1/strategies` and the UI strategy detail
  page after the M6.3 slice is merged.

## Source-to-Ledger Proof

Wait for at least one scheduler cycle after Kalshi credentials are configured.
Then collect evidence for each step:

1. `kalshi_markets` source has a recent `lastSuccessAt` and nonzero rows.
2. `open_meteo` source has a recent `lastSuccessAt`.
3. At least one signal row exists for a live Kalshi weather market, or the
   rejection reason explains why no order was placed.
4. If an order is placed, `/v1/positions` shows the paper position and the
   cash-event history remains consistent with the ledger.
5. If no order is naturally placed during the pre-soak proof window, do not
   weaken production thresholds silently. File a follow-up for a tightly gated
   staging-only canary/proof path and document why it is needed.

Do not start the two-week soak clock until the paper executor path has either
placed a natural paper position or the team has explicitly accepted a controlled
canary proof.

## Daily Snapshot

After M6.4 is merged, run:

```bash
SOAK_API_BASE_URL=https://api.staging-event-market.critterhaus.net \
SOAK_API_TOKEN=$CONTROL_PLANE_TOKEN \
python scripts/staging_soak_snapshot.py
```

Save the output with the soak notes for that date.

## Abort Conditions

Abort or pause the soak if:

- Any evidence suggests real-money execution is enabled.
- A source is degraded for more than two scheduler cycles.
- Scheduler cycle health reports `error`.
- Paper positions exceed the intended exposure.
- Starting bankroll/profile was wrong after the first signal.
