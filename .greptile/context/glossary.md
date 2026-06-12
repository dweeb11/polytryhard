# Glossary (pinned for code review)

Domain vocabulary for polytryhard. The PDD §11 glossary plus a few cross-cutting terms a reviewer needs to read code accurately.

---

## Trading / strategy terms

- **Signal**: a strategy's belief about a market at a moment in time — `(prob_yes, confidence, features_snapshot, market_state)`. Persisted **even when rejected**, with the rejection reason. Reading a strategy by signals only (without the rejection column) misreads its behavior.
- **Strategy**: a **pure function** of `(market_state_at_t, features_as_of_t) → Signal`. No I/O, no clock access, no LLM calls. If you see network or clock access inside strategy code, that is a bug, not a style issue.
- **Risk / sizing**: deterministic layer that turns signals into orders (fractional Kelly, exposure cap, correlation cap, freshness check). Not pluggable. Lives in `core/risk/`.
- **Executor**: places orders. Two implementations: `paper_executor` (MVP) and a future `kalshi_live_executor`. Same interface. Live executor is gated and off by default.
- **Paper executor**: simulates fills against historical/live orderbook snapshots; writes to the per-env ledger; same interface as live.
- **HWM (high-water mark)**: running max of a strategy's bankroll; baseline for drawdown. **Resets only on explicit operator action** — never silently bumped by deposits.
- **Drawdown**: `(hwm - bankroll) / hwm`. Crossing the configured threshold trips `drawdown_paused`. Open positions are not auto-closed.
- **Free cash**: `bankroll - SUM(open_position.cost_basis)`. Bound on both withdrawals and order sizing.
- **Fractional Kelly**: position sizing as a fraction of the full-Kelly bet (default < 1.0). `kellyFraction = 0` means the strategy emits no orders.

## Data / feature terms

- **Feature provider**: pluggable module turning raw data into a named, versioned, time-stamped numeric feature. Each `feature_value` row is `(provider, version, subject, as_of, value)`.
- **Rubric**: a versioned `(prompt, schema, model, temperature)` artifact used by an LLM-backed feature provider to score unstructured input into bounded numeric features. **The only place an LLM call belongs.** Cached by `(rubric_name, rubric_version, input_hash)`.
- **As-of timestamp**: the moment a piece of data first became knowable. Every feature query is gated `WHERE as_of <= clock.now()`. This is the look-ahead-bias defense.
- **Plugin manifest**: per-plugin `manifest.toml` declaring name, version, schedule / inputs / outputs, config schema, enable state. The plugin contract.
- **FeatureValue.kind**: discriminated union `present | missing | stale`. **`missing` is a first-class value, not an error.** Strategies refuse to emit on missing required features unless they opt-in.

## State / control-plane terms

- **`pause_system` / kill switch**: single atomic flag. Tripped manually or automatically (drawdown > 10% in 24h, > N executor errors, op failure). All executors return `rejected_system_paused`. **Open positions are NOT auto-closed.** Resume requires reason.
- **`request_id`**: identifier that flows through one tick (scheduler → source → feature → strategy → sizing → executor → ledger). Grep one ID to reconstruct a tick. Never regenerated mid-tick.
- **Audit event**: append-only record of every state change. Schema: `actor, action, target_type, target_id, before_state, after_state, reason, request_id`.
- **Environment (`env`)**: `main` or `staging`. Separate per-env DBs and Coolify services. **Per-env data (ledgers, signals) is never merged** — promotion is code-merge plus migration.

## UI prototype terms

- **`actions.ts` mutation surface**: the only file in `ui/` allowed to mutate stores. Ledger/system mutations go through exported functions here; in **live** mode they call `/v1/*` and re-hydrate stores from the API.
- **API mode (`live` \| `mock`)**: derived from `PUBLIC_BACKEND_URL` + `/healthz`. Live uses bearer auth against the FastAPI control plane; mock uses fixtures + `localStorage` key `polytryhard`.
- **Generated API types**: `ui/src/lib/api/types.ts` from OpenAPI — do not hand-edit. Prototype-only shapes (Toast, fixtures) stay in `ui/src/lib/types.ts`.
