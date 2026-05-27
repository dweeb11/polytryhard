# polytryhard — Architectural Review

> Independent simplicity review against `staging` HEAD (post-M1-infra-skeleton merge, commit `08a2e8d`). Verdict: **C — meaningfully overbuilt and worth simplifying** — but the overbuild is on the UI side; the backend skeleton is appropriately scoped.

## 1. What this project actually is
- **What the app appears to do:** A SvelteKit single-page dashboard prototype for a (future) prediction-market research lab, paired with a deliberately scoped FastAPI backend skeleton (M1) that today only exposes `/healthz`. The dashboard runs entirely against fixture data in Svelte stores, persisted to `localStorage` per "environment", with a ~3s `setInterval` that simulates ticks. The FastAPI side stands up settings, sync SQLAlchemy session helpers, request-id middleware, alembic trees (shared = empty, per-env = one `audit_event` table), and four backend tests including a Testcontainers Postgres integration test. Per M1 milestone notes: "UI remains mock-authoritative" — the two halves are not yet wired together for domain data; the `BackendStatusBadge` in the header is the only live link.
- **Current maturity/stage:** UI is a mature-looking prototype (~3000 LOC TS/Svelte). Backend is ~150 LOC of platform scaffolding with one health endpoint and one empty audit_event table. No `/v1/*`, no domain code, no ingestion, no executor, no strategies.
- **What "simple and good enough" should mean here:** The UI should be a clickable mock just rich enough to validate UX and PDD invariants. The backend should be just enough to deploy and prove the operating model (build → migrate → healthcheck). Anything more in either layer is speculative.

## 2. Architecture map

**Frontend (`ui/`):**
- **Entrypoint:** `ui/src/routes/+layout.svelte` (header, nav, modals, kill-switch UI, BackendStatusBadge). `+layout.ts` disables SSR + prerenders everything.
- **Domain types:** `ui/src/lib/types.ts` — 188 lines mirroring most of the PDD schema (StrategyInstance, Signal, Plugin, CashEvent, PaperPosition, AuditEvent, SourceHealth, EnvSnapshot, etc.).
- **State ownership:** 10 module-level `writable` stores in `ui/src/lib/stores/index.ts`, each a slice of the same `EnvSnapshot`. Snapshot is hydrated from `FIXTURES[env]` or `localStorage`; every store change re-serializes the entire snapshot to `localStorage` via a global subscription.
- **Mutation surface:** `ui/src/lib/actions.ts` (447 lines). Every UI mutation funnels here. Enforced by a custom CI grep (`ledger-discipline`) that fails the build if `bankrollCents:` writes appear outside `actions.ts` / `types.ts` / `fixtures.ts`.
- **UI structure:**
  - `/` overview (`+page.svelte`)
  - `/strategies/[name]` detail (327 lines — bankroll/calibration SVGs, deposit/withdraw/kelly/force-close/decommission)
  - `/settings/{sources,plugins,audit}`
  - `/plugins`, `/audit`, `/sources`, and `/settings` itself — all `redirect(302, …)` aliases to `/settings/*`
- **API/data boundary:** `BackendStatusBadge.svelte` hits `${PUBLIC_BACKEND_URL}/healthz` every 30s. That's the only crossing. The simulated tick lives in `ui/src/lib/mocks/tick.ts` and pokes the same Svelte stores directly.
- **Persistence (UI):** `localStorage`, key `polytryhard:<env>`, full snapshot per env.
- **Charts:** hand-rolled SVG (`BankrollChart`, `CalibrationChart`). PDD lists uPlot / Layercake / ECharts as TBD.

**Backend (`core/`, `migrations/`, `tests/`):**
- **Entrypoint:** `core/api/main.py` → `create_app(settings)` returns a FastAPI app with CORS, request-id middleware, and a single `/healthz` (returns version, git_sha, request_id, checked_at, db_shared, db_per_env; 200 ok / 503 degraded).
- **DB:** `core/db/session.py` — sync SQLAlchemy `sessionmaker` per database URL plus a `check_database` ping. `make_engine` is called fresh per check (no caching).
- **Migrations:** `core/migrations.py` builds an alembic `Config` programmatically; `migrations/shared/` and `migrations/per_env/` are separate trees with one revision each. Shared `001` is an intentional no-op; per-env `001` creates `audit_event` with two indexes.
- **Settings:** `core/settings.py` — `pydantic-settings` BaseSettings with five fields and `@lru_cache get_settings()`.
- **Tests:** `tests/test_healthz.py`, `test_request_id.py`, `test_time.py`, `test_db_smoke.py` (the testcontainers one — skips locally without docker, runs in CI). No UI tests.
- **CI:** Five jobs — `ui` (svelte-check/lint/build), `docker-ui`, `backend` (ruff/mypy/pytest), `docker-api`, `ledger-discipline` (grep).
- **Deploy:** `docker-compose.yml` (local) and `docker-compose.coolify.yml` (staging). Two Dockerfiles (`Dockerfile` = api, `Dockerfile.ui` = nginx static). Coolify app `event-market-staging` on lxc-107, domain `staging-event-market.critterhaus.net`.

## 3. Simplicity review

### 3.1 The PDD schema is implemented in TypeScript before the backend can satisfy it
- **Evidence:** `types.ts` (full strategy state machine, signal outcomes, feature-value kind union, cash-event kinds, plugin types, audit events); `fixtures.ts` (388 LOC of seed); `actions.ts` (kill switch / pre-pause state restoration / circuit breaker on `probeSource`). The backend currently exposes none of this — only `/healthz`.
- **Why too complex:** The mock encodes `low_bankroll_paused` vs `drawdown_paused` vs `graduated_under_review`, HWM tracking, free-cash-vs-reserved math, circuit-breaker states, plugin `requires`/`provides` resolution, prePauseState restoration. When `/v1/*` lands, this will all be re-derived in Python and the TS side will need to be regenerated (or kept manually in sync). Right now you have two domain models with no contract between them.
- **Simpler version:** Pare types down to what the rendered screens actually show. Drop `prePauseState`, `circuitBreaker`, `consecutiveFailures`, kelly restoration, the `requires`/`provides` resolver. Keep the *shape* (status enum, bankroll, signals) so screens can be re-wired to API types later.
- **Risk:** low — it's all mock anyway. **Recommendation:** simplify. Ideally generate the TS types from FastAPI/pydantic when the control plane starts landing (`datamodel-code-generator` or similar).

### 3.2 Two "environments" backed by separate `localStorage` keys
- **Evidence:** `EnvName = 'main' | 'staging'`, `loadEnv`, `resetEnvToFixtures`, `switchEnv`, staging fixture is `0.85 * main`.
- **Why too complex:** Real env separation is at the deploy boundary now (Coolify `event-market-staging` vs an eventual main). The UI env switcher is no longer the model of where envs live; it's just two flavors of the same mock with smaller numbers. Costs an extra dimension everywhere (snapshot, persistence, hydration, header dropdown, reset modal).
- **Simpler version:** Single env in the UI; deploy-time env labels live in `PUBLIC_BACKEND_URL` / build-time config.
- **Risk:** low. **Recommendation:** simplify / delete.

### 3.3 Hand-rolled plugin registry / `strategyBlockedBy` resolver in the mock
- **Evidence:** `ui/src/lib/stores/index.ts:133-145` (derived store walking plugins to compute missing requirements), `ui/src/routes/settings/plugins/+page.svelte:15-30` (a second walker, `strategiesWouldBlock`, that does basically the same thing pre-toggle).
- **Why too complex:** This is the **backend's** core/registry. Modelling it in mock-UI land is fake extensibility; two implementations of the same resolver already.
- **Simpler version:** Show the plugin list with toggles; don't compute blocking. Or pre-bake a `blocked` flag into the fixture.
- **Risk:** low. **Recommendation:** simplify.

### 3.4 Custom CI grep guarding an invariant that lives in a layer the grep can't see
- **Evidence:** `.github/workflows/ci.yml` `ledger-discipline` job. Greps `bankrollCents:` writes outside an allowlist in `ui/src/lib/`.
- **Why too complex:** It guards the **mock**'s mutation surface. The real ledger is going to be Python and won't be touched by this rule. Either the rule should be rewritten to police the Python ledger when it exists, or it should sit out until then.
- **Simpler version:** Delete the job; reintroduce as a Python check when the ledger module lands.
- **Risk:** low. **Recommendation:** delete (or comment out with a one-liner pointing to the future location).

### 3.5 Per-store snapshot subscription causing N+1 writes
- **Evidence:** `subscribePersistence()` in `stores/index.ts` subscribes to all 10 stores; each subscribe fires immediately on register and on every `set`, calling `persistCurrent()` which pulls **all** stores and JSON.stringifies the whole snapshot to `localStorage`. Every action also calls `persistCurrent()` directly via `toastResult`.
- **Why too complex:** A single `deposit()` triggers many full serializations (one per `update` on strategies/cashEvents/audit/bankrollHistory + the explicit one). Two redundant persistence paths.
- **Simpler version:** Keep the explicit `persistCurrent()` after actions; drop the subscribe-all loop. Or vice versa.
- **Risk:** low. **Recommendation:** simplify — pick one path.

### 3.6 Redirect routes for sections that are subroutes of `/settings`
- **Evidence:** `ui/src/routes/{plugins,audit,sources,settings}/+page.ts` all do `redirect(302, '/settings/...')`.
- **Why too complex:** Either link directly to `/settings/plugins` or expose them as top-level. The double indirection is dead weight.
- **Risk:** low. **Recommendation:** delete the four stubs and update any inbound links.

### 3.7 `make_engine` not cached
- **Evidence:** `core/db/session.py:38-49` — `check_database` builds a fresh `Engine` per call and disposes it. Called twice per `/healthz` (shared + per_env). `BackendStatusBadge` polls every 30s.
- **Why too complex:** Engine creation is cheap-ish but not free; the badge → healthz → 2× engine create/dispose every 30s is silly. The session helpers (`shared_session`, `per_env_session`) also build a fresh engine per call via `_session_factory`.
- **Simpler version:** `@lru_cache` `make_engine(url)` keyed by URL.
- **Risk:** low. **Recommendation:** simplify (one-line fix).

### 3.8 `EnvSnapshot.system.killSwitchTrippedAt` etc. unused in UI
- **Evidence:** Header shows `System: {state}` only; the timestamp/reason are stored, never read into the UI beyond the kill modal flow.
- **Why too complex:** Carrying audit state that nobody renders.
- **Risk:** low. **Recommendation:** defer until a screen actually shows it.

### 3.9 `signal.featuresSnapshot` populated in fixtures but never displayed
- **Evidence:** Strategy detail signals table shows time/ticker/probYes/outcome only. `featuresSnapshot` is generated in fixtures + tick but read nowhere.
- **Why too complex:** Pure ballast in `localStorage` (gets persisted 200 deep × N strategies).
- **Risk:** low. **Recommendation:** defer or expose it (an expandable row would justify keeping it; otherwise drop from fixtures).

## 4. Underbuilt areas
A prototype + an explicitly-scoped infra skeleton, so under-built is mostly fine by design. A few real ones:

- **No UI tests.** *Evidence:* Backend has four; `ui/` has zero. *Why it matters:* The actions module already has non-trivial logic (auto-resume on deposit considering `prePauseState`, free-cash gating, force-close → cash_event chain). When you port to FastAPI you'll want behavior tests to drive parity. *Minimal fix:* a single vitest file covering `deposit`, `withdraw`, `forceCloseAndWithdraw`, `pauseStrategy` happy/sad paths (12–15 cases).
- **`localStorage` can desync from in-memory snapshot.** *Evidence:* `loadEnv` calls `currentEnv.set(env)`; the global subscription then immediately re-persists the **new** env's snapshot under the **new** env key. `syncFromSnapshot()` then issues 10 sequential `set`s, each triggering a full persist. Possibility of races on rapid switch. *Minimal fix:* drop the global subscription; persist only after actions.
- **`probeSource` and `tick` use `Math.random()` for state transitions.** *Evidence:* `actions.ts:341,446`, `tick.ts`. *Why it matters:* unreproducible mock UX; fine for clicking around, bad if you write tests. *Minimal fix:* inject a seeded RNG, default to `Math.random`.
- **No validation on deposit/withdraw amount inputs.** *Evidence:* strategy page passes `Number(amountDollars) * 100` directly. Non-numeric input → NaN → store gets NaN. *Minimal fix:* guard `Number.isFinite` before calling the action.
- **`Settings` has no `model_validator` checking that DB URLs are set in production.** *Evidence:* `core/settings.py`, both DB fields default to `None`; `check_database` returns `"unconfigured"` and `/healthz` returns 200 ok. In Coolify, if the env var fails to land, the API will look healthy with no databases. *Why it matters:* fail-closed semantics from PDD §6 should apply to startup too. *Minimal fix:* if `APP_VERSION != "0.1.0"` or via an explicit `REQUIRE_DBS` flag, refuse to start when either URL is `None`; or downgrade unconfigured to "degraded".

## 5. Delete / consolidate candidates

| Candidate | Why | Replace with | Confidence |
|---|---|---|---|
| `.github/workflows/ci.yml` `ledger-discipline` job | Guards a mock invariant; will need to be rewritten for the Python ledger anyway | nothing | high |
| `ui/src/routes/{plugins,audit,sources,settings}/+page.ts` redirect stubs | Pointless indirection | direct links to `/settings/*` | high |
| `EnvName` plumbing (`switchEnv`, `resetEnv`, `staging` fixture, dropdown) | Real env separation is at the deploy boundary now | single UI env | medium |
| `subscribePersistence` (in `stores/index.ts`) | Redundant with explicit `persistCurrent()` in `toastResult` | keep one path | high |
| `strategyBlockedBy` derived + `strategiesWouldBlock` in plugins page | Two implementations of the same fake resolver | precompute on fixture or drop | medium |
| `StrategyInstance.prePauseState`, `kellyFraction` restore logic in `deposit/resume` | Behavior nobody is going to test in a prototype | `state: 'active'` on resume | medium |
| `featuresSnapshot` field in `Signal` + fixture generation | Stored, never rendered | drop, or add UI | medium |
| Most of `types.ts` enums beyond what screens render | Will be regenerated from the backend | trim to rendered shape; regen later | medium |
| Hand-rolled `BankrollChart` / `CalibrationChart` | PDD already says these are TBD; will be swapped | keep for now | low (keep) |

## 6. Minimal cleanup plan

### 1 hour
1. Delete the four `+page.ts` redirect stubs (`plugins/`, `audit/`, `sources/`, `settings/+page.ts`); update any links that hit the bare paths.
2. Remove the `ledger-discipline` CI job — leave a one-line comment in the workflow noting it will return targeting Python when the ledger module lands.
3. Drop `subscribePersistence()` from `+layout.svelte`'s `onMount`. Verify deposit/withdraw still persist via the explicit `persistCurrent()` path.
4. `@lru_cache` the engine factory in `core/db/session.py`.

### 1 day
5. Collapse `EnvName` to a single env. Delete `switchEnv`, `resetEnv` UI, `seedStaging`, the dropdown, the reset modal. If you want a "reset to fixtures" button, keep just that.
6. Trim `types.ts`: drop `prePauseState`, `graduatedMaxDrawdownPctFromHwm`, the `graduated`/`graduated_under_review` states (unused in UI), `CircuitBreakerState`, `consecutiveFailures`, `requires`/`provides` on `Plugin`. Re-add when the backend can produce them.
7. Delete `strategyBlockedBy`, `strategiesWouldBlock`, and the "blocked" badge on the roster. Plugins page becomes a flat toggle list.
8. Add a minimal vitest suite (10–15 cases) over `actions.ts` covering deposit/withdraw/pause/resume/forceClose. Aim for behavior parity targets, not coverage.
9. Number-input validation on deposit/withdraw.
10. Tighten startup: if either DB URL is unset, return `degraded` from `/healthz` (or refuse to boot in non-default mode).

### 1 week
Not needed for the current goal. The next material step is the `/v1/*` control plane. Don't pre-clean the UI prototype further until you can co-design TS types with backend types — ideally generated.

### Explicitly DO NOT clean up yet
- Hand-rolled SVG charts. They work; replacement is in the PDD's TBD list.
- Tailwind v4 / Svelte 5 runes choices. Recent and intentional.
- The two Dockerfiles + two compose files. Slight duplication, but the local vs Coolify divergence (`POSTGRES_PASSWORD` required, healthcheck wired, different volume name, no port publish) is real and shouldn't be merged.
- The empty `001_initial_shared` migration. Cheap baseline; trying to make it "useful" before the first real shared table would create more churn than it saves.
- The Settings BaseSettings shape. It's small and right-sized.
- The audit page in the UI (the only place `beforeState`/`afterState` rendering exists — strongest part of the prototype).

## 7. Tests needed before cleanup

Smallest behavioral suite that protects the cleanup work — UI side, since the backend already has its skeleton tests:

1. **`deposit`** — happy path increments bankroll, writes `cash_event`, appends audit, bumps history; rejects amount ≤ 0; rejects on kill switch; rejects on `decommissioned`; auto-resumes from `low_bankroll_paused` when crossing `minBankrollCents`.
2. **`withdraw`** — rejects > free cash (with at least one open position so free < bankroll); rejects on kill switch; writes negative `cash_event`.
3. **`pauseStrategy` / `resumeStrategy`** — only from PAUSABLE/RESUMABLE states; resume returns to `active` (not `graduated`) under default config.
4. **`forceCloseAndWithdraw`** — closes all open positions for that strategy only, sums unrealizedPnl into bankroll, writes one `cash_event` per position.
5. **`tripKillSwitch` / `resumeKillSwitch`** — require reason; flip system state; block subsequent `deposit`.
6. **`canEmitSignals` / `resolveSignalOutcome`** — invariants given paused vs active states, kelly = 0.
7. **Persistence round-trip** — mutate via action, simulate reload by re-hydrating from `localStorage`, assert state matches.

All seven are pure unit tests against `actions.ts` + `stores`. No DOM. ~150–200 lines total.

## 8. Final verdict

**C — meaningfully overbuilt and worth simplifying.**

Plain English: the M1 backend skeleton is appropriately scoped — small, deliberate, ships infra without overreaching into domain code. Good. The **UI prototype** is the part that's overbuilt: it has internalized the full production PDD before the backend can satisfy any of it. The TypeScript domain model encodes a strategy state machine, plugin dependency resolver, circuit-breaker state, pre-pause restoration logic, dual-environment persistence, and a custom CI grep guarding a "ledger discipline" invariant that polices the wrong layer — all in a 3000-LOC frontend backed by `localStorage` and `setInterval`. None of it is wrong, but most of it will be re-derived in Python (and ideally regenerated as TS) when `/v1/*` lands. Keeping it in sync until then is pure cost.

It's not tangled — the seams are clean and the mutation funnel through `actions.ts` is genuinely nice. So it isn't D. But it's also not "slightly" overbuilt; it's reproducing the architecture document instead of validating UX. The cleanup is small, safe, and mostly deletions, and doing it now means less to keep in sync with the backend as the control plane grows.

The most valuable things in this repo: the strategy-detail UX, the audit-log diff view, the kill-switch flow, and the M1 backend skeleton. Keep those. Strip the rest down to what they need.
