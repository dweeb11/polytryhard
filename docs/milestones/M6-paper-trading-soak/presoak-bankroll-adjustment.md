# M6 Pre-Soak Bankroll Adjustment

This slice adds an API-only pre-soak control for setting a strategy's starting
paper bankroll without direct database edits.

## Endpoint

```http
POST /v1/strategies/{name}/set-starting-bankroll
Authorization: Bearer $CONTROL_PLANE_TOKEN
```

Body:

```json
{
  "amountCents": 25000,
  "reason": "M6 pre-soak starting bankroll"
}
```

The response is the updated strategy instance.

## Guardrails

- The amount must be positive.
- A reason is required.
- The strategy must not be decommissioned.
- The system kill switch must not be active.
- The strategy must have no signals, fills, or positions. Rejected evaluation
  signals count as activity and block this endpoint.
- The adjustment updates `initial_deposit_cents`, `bankroll_hwm_cents`, and the
  strategy config baseline fields `min_bankroll_cents` and
  `min_tradeable_bankroll_cents`.

When the requested amount differs from the current bankroll, the adjustment is
written as a normal ledger delta cash event. A higher target creates a deposit;
a lower target creates a withdrawal. The operation then updates the starting
baseline fields and writes a single `set_starting_bankroll` audit event.

If the requested amount equals the current bankroll, the endpoint can still be
used before activity exists to correct the initial/HWM baseline. In that case no
cash event is written, but the baseline audit event is still recorded.
