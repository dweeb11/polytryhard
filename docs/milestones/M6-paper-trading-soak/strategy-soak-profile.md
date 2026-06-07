# M6 Strategy Soak Profile

The M6 soak uses the existing seeded weather strategies with explicit,
reviewable configuration. Startup seed config applies only when a strategy row
does not already exist; existing rows are not rewritten by startup.

## Seeded Strategies

### `weather_ensemble_disagreement`

- `confidenceFloor`: `0.55`
- `disagreementThreshold`: `2.0`
- `spreadMarginMultiplier`: `1.5`
- `max_input_age_seconds`: `900`
- `exposureCapPct`: `0.10`
- `correlationCapPct`: `0.05`

### `weather_stale_quote`

- `confidenceFloor`: `0.55`
- `wideSpreadThreshold`: `0.08`
- `max_input_age_seconds`: `900`
- `exposureCapPct`: `0.10`
- `correlationCapPct`: `0.05`

## Visibility

The effective config is visible from:

- `GET /v1/strategies`
- `GET /v1/strategies/{name}`
- the strategy detail page's read-only **Soak config** panel

The profile intentionally keeps the current hourly cadence and existing
strategy implementations. If live strategies are too quiet during pre-soak
verification, add a tightly gated staging-only proof path in a later slice
instead of weakening these defaults silently.
