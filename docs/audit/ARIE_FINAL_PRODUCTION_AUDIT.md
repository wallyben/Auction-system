# ARIE FINAL PRODUCTION AUDIT

Recorded 2026-08-29 against `main` `f9a2549c37cee9c743eb4b30c4455b904bd7e8af` (valuation **2.1.5** live) and this hardening branch (**2.1.6**).

Production host: `https://auction-system-l6je.onrender.com`

## 1. EXECUTIVE VERDICT

**B. CURRENT ARCHITECTURE NEEDS A SMALL STRUCTURAL CHANGE FIRST**

The engine pipeline is real: CompSniper sold tickets, identity gate, UK-proxy valuation, Ireland cost stack, 16 money-ready gates, SAFE_START, fail-closed BUY_READY. That is not vapourware.

It cannot be a reliable production engine on a **single Render uvicorn worker** while:

* scan, sold-refresh, revalue, sold-revalidate, dashboard buttons, and HTTP `/ops/*` all run **in-process on the asyncio event loop**;
* only `_running` serialised **scans**;
* `live_camera_body_certification` reloaded the sold table **per listing evaluate**;
* listing eval could spend CompSniper quota;
* known kit titles (SEL / Sigma / TTArtisan) were still accepted as body comps after 2.1.5.

During this audit, `/health` itself timed out. That is the single-worker pin, not a flaky network blip.

Smallest robust change (implemented here): **one global pipeline lease + HTTP 202 enqueue + event-loop yield + no paid CompSniper on listing eval + kit matcher 2.1.6**. Not a second Render worker tonight (that is the next infrastructure step if the lease ever saturates).

## 2. CURRENT SYSTEM MAP

```
eBay Browse (LIVE if production keys) ─┐
Reverb / RSS / CSV / manual ────────────┼─► persist_listing
Scryfall (cards, dealer guides) ───────┘         │
                                                   ▼
                                         identify + condition
                                                   │
CompSniper (sold only, scheduled) ──► sold_evidence ──► _comps_for
                                                   ▼
                              value_from_comps → landed + tax + exits
                                                   ▼
                              liquidity + risk → ENGINE_DECISION
                                                   ▼
                              16 gates → MONEY_READY_DECISION
                                                   ▼
                              Opportunity row + paper trade + dashboard
```

Entrypoint: `app/main.py` → FastAPI + APScheduler in lifespan. Start: `scripts/start.sh` → one uvicorn process.

Heavy HTTP (now 202 + lease): `POST /scans`, `/ops/revalue`, `/ops/sold-refresh`, `/ops/sold-revalidate`, dashboard scan/revalue/sold-refresh.

## 3. CURRENT PRODUCTION STATE

At audit start:

| Probe | Result |
|---|---|
| `GET /health` | 200, `valuation_algorithm=2.1.5`, `git_sha=f9a2549…` then **later timed out** |
| `GET /health/db`, `/health/jobs`, `/health/sources`, `/config`, `/scans`, `/paper` | **timed out 8–25s, 0 bytes** |

Do not POST heavy ops against a wedged worker. Last merged work was PR #14 (stop per-listing rematch). Open PR #15 (kit matcher) was not on production.

Honest live book (from prior artefacts + this code): BUY_READY can be zero and **must stay zero** until kits are rejected, the book is revalued on 2.1.6, and a listing actually clears every gate.

## 4. P0 BLOCKERS

| Defect | Consequence | Location | Fix in this PR |
|---|---|---|---|
| Overlapping heavy jobs on one worker | `/health` dies; partial revalue | `app/jobs/scheduler.py` `_running` scan-only | Global `pipeline_jobs` lease |
| Sync CPU in request handlers | Render connection timeout; cancel mid-job | `ops.py` POST revalue/scan/sold-* | HTTP 202 `dispatch_http` |
| Certification sold-table reload on evaluate | O(listings × sold) after 45s TTL | `pipeline/service.py` → `category_is_certified` | Snapshot once per scan/revalue; 10 min cache; no per-listing sold.all |
| CompSniper on listing eval cache miss | Quota + pin during scan | `ensure_sold_for_listing` | Skip paid refresh on eval |
| Known kit false accepts in valuation | Max-buy from lens kits | `identity_gate.py` | SEL/Sigma/TTArtisan/plural lenses (2.1.6) |
| Optimistic downside (missing exit fees) | DOWNSIDE_PASS too easy | `costs/landed.py` | Include payment/returns/warranty on p25 path |
| Double-counted €0.25 in max-buy | Slightly wrong bid cap | `landed.py` extra `+ 0.25` | Removed |

## 5. P1 BLOCKERS

| Defect | Consequence | Fix |
|---|---|---|
| Persist N+1 fingerprint SELECT | Slow revalidate | Bulk `IN` lookup |
| Failed CompSniper cache uses full TTL | 18h lockout after 401/5xx | Error TTL 0h / 1h |
| LOCALISATION_PASS via conf ≥ 0.85 | High-N UK book bypasses local/UK-proxy rules | Removed |
| Cert hardcoded exit/risk True | Cert without measuring exits | Require exit coverage + SAFE_START controls |
| Dashboard/camera-pipeline N+1 listings | Pin on GET | Bulk listing load |
| `/health/evidence` 5000-row scan | Health that isn't cheap | SQL COUNT |

## 6. ROOT CAUSES

1. **Process model:** web + scheduler + CPU valuation share one event loop.
2. **Work is nested:** refresh → revalidate → revalue; scan → eval → cert → sold.all.
3. **Matcher is regex-vs-title**, so kit language keeps leaking; production 2.1.5 still accepted live SEL/Sigma kits (PR #15).
4. **Market coverage is eBay Browse + CompSniper GB sold.** Not Irish classifieds. Bargains can exist on eBay GB/IE/DE; they cannot appear from DoneDeal.

## 7. PERFORMANCE COMPLEXITY

Notation: A ≤ 400 active listings, S = sold_evidence rows, C ≈ 12 camera bodies, Q ≈ 12 queries.

| Path | Before | After |
|---|---|---|
| `/ops/sold-revalidate` | O(S) rematch + O(A) revalue, **blocking HTTP** | Lease + 202 + yield every 25 rows |
| `/ops/revalue` | O(A) × (sold lookup + **live cert**) | Cert once; yield every 4 listings; 202 |
| `POST /scans` | Src×Q×L HTTP + eval + possible CompSniper | CompSniper not on eval; 202 |
| Scheduled scan / sold / revalue | Could overlap | One `pipeline` lease |
| Certification | sold.all + N× evidence_freshness queries | One sold load; 600s TTL |
| Camera pipeline GET | cert + rematch all titles + N+1 | rematch=False; bulk listings |
| `/health` | blocked when loop busy | Yields in heavy loops; health stays a dict |

## 8. DATA QUALITY STATUS

Matcher (after 2.1.6) rejects kits, accessories, lenses, wrong generation, parts, Best Offer upper bounds at ingest.

**Not proven on production until sold-revalidate runs against live rows.** Do not treat unit tests as live false-accept = 0.

Irish realised panel is empty by design; UK CompSniper is the valuation source (`UK_REALIZED_PROXY`).

## 9. VALUATION QUALITY STATUS

* Expected sale = weighted median of realised/binding comps (MAD outliers only if N≥4).
* Quick sale = p25 if N≥3 else 0.88×expected.
* UK prices converted ECB mid (units per EUR). No Ireland premium.
* Best Offer excluded.
* Kits excluded **if the matcher catches them**.
* Condition buckets are **not** separated (`grades_compatible` unused). P2.
* Low N: N<3 VALIDATED caps confidence at 0.58; N=1 can still be VALIDATED UK proxy. Gates still require comps≥3 and realised≥1 for BUY_READY.
* Asking-only expected sale is **€0**.

## 10. ECONOMIC MODEL STATUS

UK purchase → IE resale:

| Line | Class |
|---|---|
| Purchase FX (ECB) | VERIFIED rate |
| FX spread 1.2% | CONFIGURED ASSUMPTION |
| Inbound shipping listed / corridor default | VERIFIED if listed else CONFIGURED |
| Buyer payment 1.9%+€0.25 | CONFIGURED |
| Import VAT 23% on GB | ACCOUNTANT REQUIRED (modelled, cash) |
| Duty | CONFIGURED, default 0 |
| Handling | **NOT MODELED** |
| Returns / warranty / refurb | CONFIGURED |
| eBay IE FVF 12.9% + VAT on fee | CONFIGURED |
| Outbound ship + pack | CONFIGURED |

Max-buy: reverse acquisition so target margin remains after resale fees. Pipeline overwrites **net/profit** from best exit but **does not recompute max-buy** off that quote (P2).

## 11. GATE / CERTIFICATION STATUS

ENGINE_DECISION ≠ MONEY_READY. BUY_READY needs engine BUY, zero failures, `assert_money_ready`.

`TAX_PASS` is still “tax_modelled=True” from the pipeline (always). Soft gate. P2.

`CATEGORY_CERT_PASS` uses live camera snapshot, not owner override (override stays false).

SAFE_START camera: €1000, N≥8, conf≥0.85, ROI≥0.20, downside≥0, velocity known, liq conf≥0.40, capital-at-risk ≤ €150. Enforced in `_safe_start_pass`.

## 12. INFRASTRUCTURE / SCHEDULER STATUS

Single worker. Required jobs: scan, sold-refresh, revalue-after-evidence, revalue-all-active.

Stale lease steal after 12 minutes without heartbeat. Crash: in-memory flag dies; DB row expires.

No second Render Background Worker in this change (owner would have to add a service). Lease + 202 is the tonight-sized architecture.

## 13. SOURCE COVERAGE STATUS

**Engine can work. Market coverage is not “all of Ireland.”**

LIVE acquisition: eBay Browse (when production keys work), optional Reverb, RSS, CSV/manual. CompSniper is sold evidence, not listings.

BLOCKED_POLICY: DoneDeal, Adverts, auction houses, CeX. Do not scrape.

Fastest legitimate extra source: **Allegro official API** if the owner supplies keys — not tonight. Highest leverage: keep eBay production Browse healthy.

## 14. EXACT REMAINING BUILD PLAN

1. **This PR** — lease, 202, yields, kit 2.1.6, no eval CompSniper, cert snapshot, economics fixes. Tests. Deploy once.
2. **Owner Manual Deploy** on Render (this agent cannot push Render).
3. Confirm `/health` 200, algorithm 2.1.6, new SHA.
4. `POST /ops/sold-revalidate` (202). Watch `/ops/jobs` + `/health` stays up. Zero quota.
5. When job success: matcher_false_accepts on `/ops/sold-quality` = 0 for known kit titles.
6. `POST /ops/revalue` (202). Algorithm 2.1.6 on opportunities. No CompSniper during revalue.
7. Optional `POST /ops/sold-refresh` only if cache stale and quota remains.
8. `GET /ops/camera-pipeline` — cert, top20, BUY_READY (0 is acceptable).
9. Next scheduled scan/revalue must skip if lease held; after idle, succeed.
10. Manual trace of any BUY_READY (if one exists) before spending money.

Stop if `/health` dies, quota 401/429, or matcher still accepts a known kit.

## 15. ACCEPTANCE TESTS

See PHASE 16 in the owner brief. Code-level: `pytest tests -m "not live"`. Live: health during 202 jobs; SHA/version; revalidate; revalue; no CompSniper on revalue; scheduler lease; BUY_READY only with 16 gates.

## 16. FAILURE RISKS

| Risk | Mitigation or blocker |
|---|---|
| Render not deployed | Owner must Manual Deploy — **unresolved until they do** |
| CompSniper 401/quota | Fail closed; no eval scrape; short error TTL |
| Lease table missing if migrate fails | `start.sh` alembic 8 tries; health still serves |
| 202 job dies after acquire | 12 min stale steal |
| SQLAlchemy session in background | Own session in `_background` |
| Kit regex miss next title | Fail closed; add title; do not weaken |
| No qualifying listing | Level 2 is “ONLY IF a live opportunity exists” |
| Tax/duty estimates | Accountant required — not a code ship blocker for Level 1 |
| Event loop still blocked between yields | Yields every 4 listings / 25 tickets; if still pinned, Option D (Render worker) is P1 next |

## 17. TONIGHT VERDICT

**Can ARIE realistically reach Level 1 — technically production ready tonight?**

**YES, if this branch is deployed and the production certification run in §14 succeeds.** Level 1 is “engine runs unattended, health stays up, evidence is clean, BUY_READY is fail-closed.” Zero BUY_READY is a pass.

**Can ARIE realistically reach Level 2 — safe for a first small live trade tonight?**

**ONLY IF A QUALIFYING LIVE OPPORTUNITY EXISTS** after 2.1.6 revalidate+revalue, every gate passes, and a human traces max-buy and the cost stack. This agent would not risk €250–€1,500 on a 2.1.5 book that still accepted kit comps and a worker that could not answer `/health`.
