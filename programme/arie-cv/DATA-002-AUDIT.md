# ARIE-CV DATA-002 audit

Retrieved 2026-09-23 from branch `cursor/arie-cv-foundation-7886`, HEAD `41f58271781d4e81a3ea97207b302f66ec6d9ddc`, plus the uncommitted Phase 2 tree. The code was read. This prompt was not treated as the source of truth.

## What is already in the tree

PR #23 (`41f5827`) is a fail-closed commercial-van engine: identity, provenance, tax, auction costs, append-only observations, comps, valuation, landed cost, max bid, gates, `/cv`, backtest, and tests.

Uncommitted Phase 2 adds Mid Ulster owner-catalogue parsing, a dealer-feed parser, an eBay van mapper that stays off without keys, a DVSA contract that does not call the API without keys, owner documents, image-condition gating, `cv_evaluations` / `cv_source_state` / `cv_owner_evidence`, worker job names, and a `/cv` candidate board.

`enabled_live_fetchers()` is empty unless eBay keys or `CV_DEALER_FEED_URLS` are set. `cv-market-refresh` does not fetch a remote dealer URL. `cv-revalue` returns idle. No Irish observation has been stored from a live source.

## Baseline failures

A full non-live run on Windows reported five failures. They are portability and test-harness issues, not weakened gates.

| Failure | Cause | Decision |
|---|---|---|
| `test_job_lease_heartbeat_does_not_refresh_worker` | `os.uname` in `app/jobs/queue.py` | FIX |
| `test_worker_death_becomes_stale_while_job_lease_held` | same | FIX |
| `test_process_heartbeat_survives_45s_blocking_job` | `os.uname` in `app/jobs/worker.py` | FIX |
| `test_health_router_module_is_not_mounted` | FastAPI 0.141 keeps included routers as `_IncludedRouter`, so a flat `APIRoute` scan sees no `/health` | FIX the walker |
| `test_every_async_route_passes_blocking_audit` | same walker | FIX the walker |

Linux CI still has `os.uname`. The hostname helper must use it there and `platform.node()` on Windows. The route walker must accept both flat routes and nested included routers. Tests are not skipped. The blocking-token audit stays in force.

## Autoza, verified 2026-09-23

Documented interfaces, read from `https://autoza.ie/api/openapi.json`, `https://autoza.ie/.well-known/ai-agent.json`, and `https://autoza.ie/agents.txt`:

| Interface | Auth | Use for valuation |
|---|---|---|
| `GET /api/v1/vehicles` | OpenAPI says none for basic search. A live call returned HTTP 200 JSON. | PRIMARY |
| `GET /api/v1/vehicles/{id}` | Same spec | Detail when a search row is thin |
| `POST /api/agent/mark` | None, 30 requests/hour, LLM reply | NOT a market book |
| `https://autoza.ie/api/mcp` tools `search_vehicles`, `get_vehicle` | None, manifest says 60/hour | Alternative agent transport. The worker uses the REST search, not HTML. |
| `GET /api/public/market-stats` | None, CC BY 4.0, hourly aggregates | Context only. Not a comp. |
| HTML `/cars` | Agents file says it returns HTML | DO NOT SCRAPE |

Search filters in the spec: `make`, `model`, `min_year`, `max_year`, `min_price`, `max_price`, `fuel_type` (`petrol|diesel|electric|hybrid`), `transmission` (`manual|automatic`), `body_type` (`suv|hatchback|saloon|van|estate|coupe`), `location`, `page`, `limit` (max 50).

A live `body_type=van&limit=5` response included a Renault Kangoo and Peugeot Partners, plus at least one non-van make. Fields actually present: `id`, `url`, `make`, `model`, `variant`, `year`, `price`, `currency`, `mileage`, `mileage_unit`, `fuel_type`, `transmission`, `body_type`, `color`, `location`, `images`, `listed_at`, `updated_at`. Registration, VIN, VAT, wheelbase, roof, seats, and generation were not in that payload. Those stay unknown. Cache-Control was `public, max-age=300`. No rate-limit header was returned on that call. The public-aggregate rule is 60 requests/minute. The MCP rule is 60/hour. The worker will stay well under both: cache for five minutes, pause between pages, and stop on HTTP 429.

`body_type=van` is not trusted as a commercial-van proof. Listings still pass the existing family parser. Sibling platforms stay separate families. Passenger and parts titles stay rejected.

## Decisions

### KEEP

- Camera pipeline and its source register.
- Vehicle domain isolation, fail-closed gates, tax, provenance, auction costs, landed cost, max bid.
- Append-only `MarketObservation` / `MarketBook.as_of` (no lookahead).
- Comp hard rejects for family, generation, body, fuel, wheelbase, mileage ratio, salvage, and duplicate registration.
- Asking haircut labelled as an estimate. Disappearance is not a sale.
- Mid Ulster owner catalogue. No unattended crawl.
- DoneDeal, Carzone, CarsIreland, and Adverts stay `BLOCKED_POLICY`.
- Cartell, Brego, MotorCheck, and MTP are not called and are not required for a shadow candidate.
- Certification stays unmeasured until real shadow outcomes exist.
- Golden Transit Custom economics: twelve identical fresh comps at €18,000 ex VAT, 15% asking haircut, `BUY_CANDIDATE` only with the existing evidence.

### FIX

- POSIX-only hostname in the worker heartbeat.
- Route audit so it sees nested FastAPI routers and still rejects blocking async handlers.
- `PRICE_INCREASED` is not derived. A higher asking price currently stays `ACTIVE`.
- Autoza is absent from the source register.
- `cv-market-refresh` does not query a permitted Irish inventory API.
- Valuation reports a median and a min/max asking range. It does not yet report effective sample size, model version, VAT basis, or a rounded trade downside.
- Unknown VAT is stored but not kept from mixing with a known VAT basis.
- Duplicate detection is registration-only. The same van on two sources can be counted twice.
- `/cv` does not yet show the Irish comps behind a number.

### REPLACE

Nothing in the deterministic engine is replaced. The native book is a provider and a tighter estimator on the existing observation, comp, and valuation types.

### REMOVE

Nothing. Paid-provider absence must not delete history gates that already fail closed when a check was not run.

### DEFER

- Gradient boosting or any model that has not beaten this estimator out of sample. Promotion needs a stored observation history, several model families, a longitudinal window, and a backtest win. None of that exists yet.
- Revenue OMSP as a live fetch. Revenue publishes VRT/OMSP context for tax, not a commercial-van resale feed. It may later be stored as an anomaly flag. It is not a resale substitute, and no bulk OMSP download is automated in this phase.
- Unattended Mid Ulster, Wilsons, BCA, Manheim, and Copart.
- Paid Cartell, Brego, MotorCheck, and MTP calls. A manual calibration row can be stored later. No subscription is purchased.
- Image-condition inference. The feature gate stays off.
- Treating Autoza aggregates or the Hugging Face price index as vehicle comps. They are cohort medians, not listings.

## Valuation defaults that stay

These already exist and are defensible for a common van. An obscure van correctly stays unvalued.

| Rule | Value |
|---|---|
| Freshness | 14 days |
| Minimum eligible comps for a shadow candidate | 8 |
| Minimum close comps | 5 |
| Minimum comp score / close score | 55 / 75 |
| Asking-only confidence cap | 0.62 |
| Candidate confidence floor | 0.60 |
| Base asking-to-achievable haircut | 0.15, labelled estimated, cap 0.30 |
| Realised sales required before the haircut can drop | 3 explicit realised prices |

Thin markets withhold the resale value. That remains the correct output.
