# M3: Ingestion

> Real Kalshi market + Open-Meteo forecast data lands in the shared DB on a schedule, with health visible from the dashboard.

## Process
- [x] Vision — `docs/PDD.md` §1.2, §4.1
- [x] Design — `docs/design/m3-ingestion.md`
- [x] Milestone — this doc
- [x] **Implement** <- current stage (spine plan: `.cursor/plans/m3_ingestion_spine.plan.md`)
- [ ] Verify
- [ ] Ship — ordered PRs to `staging`

## Tasks (PR slices, ordered)
- [x] M3.1 Shared schema `002` — reference + raw + `source_run` tables ([APP-188](https://linear.app/critterhaus/issue/APP-188))
- [x] M3.2 `Clock` interface + `WallClock` ([APP-189](https://linear.app/critterhaus/issue/APP-189))
- [x] M3.3 `IngestionSource` ABC + explicit registry ([APP-190](https://linear.app/critterhaus/issue/APP-190))
- [x] M3.4 Scheduler (asyncio supervisor + health) + FastAPI lifespan ([APP-191](https://linear.app/critterhaus/issue/APP-191))
- [x] M3.5 `reference_location` seed + Kalshi discovery ([APP-192](https://linear.app/critterhaus/issue/APP-192))
- [x] M3.6 Kalshi snapshot source (auth/signing) ([APP-193](https://linear.app/critterhaus/issue/APP-193))
- [x] M3.7 Open-Meteo source (GFS + ECMWF) ([APP-194](https://linear.app/critterhaus/issue/APP-194))
- [x] M3.8 `/v1/sources` endpoint + OpenAPI regen ([APP-195](https://linear.app/critterhaus/issue/APP-195))
- [x] M3.9 UI Source Health panel ([APP-196](https://linear.app/critterhaus/issue/APP-196))

## Out of scope (M4+)
- Feature providers, strategies, risk/sizing, paper executor, eval metrics
- Replay clock, dirty-set propagation, WebSocket push, tunable circuit breakers, NWS source
- Manifest/filesystem plugin discovery

## Verification
- `./.venv/bin/ruff check . && ./.venv/bin/mypy core tests && REQUIRE_DBS=0 pytest -q`
- `docker compose up`: `/healthz` ok; scheduler runs sources; `GET /v1/sources` returns per-source health with bearer token; raw rows present in shared DB.

## Notes
- Plan produced incrementally: spine slices (M3.1–M3.4) detailed in `.cursor/plans/m3_ingestion_spine.plan.md`; source/API/UI slices (M3.5–M3.9) planned just-in-time after a Kalshi + Open-Meteo API research pass (design §11 open questions).
- Linear: milestone **M3 — Ingestion** in the `polytryhard` project (team Apps); issues chained in dependency order.
- Ingestion writes only to the shared DB; the ledger AST purity guard stays green.
