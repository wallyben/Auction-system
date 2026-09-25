# ARIE-CV programme ledger

Status date: 2026-09-22. This file describes the code on this branch, not a target state.

ARIE-CV is a commercial-van decision engine inside the existing ARIE repository. It does not bid, buy, or pay. `BUY_CANDIDATE` in this build is a shadow result. `purchasing_recommendation` is hard-coded false.

## CV-000 — repository audit

Status: **IMPLEMENTED**. Evidence: `programme/arie-cv/ARCHITECTURE.md`.

The production system on `main` (`f5cf05d`) is an Irish reseller engine for cameras and other goods, not vehicles. Preserved: FastAPI web process, Postgres queue, dedicated worker, coherent book generation, fail-closed `BUY_READY` gates, Decimal margin kernel, source registry, ECB FX, eBay privacy webhooks. Camera identity stays in `app/identity` and `app/sold`. Commercial vans live in `app/domains/vehicles` and do not call that identity code.

Camera coupling is isolated, not retired. The worker was not given a van job. There is no live van source to poll, and a new heavy job would contend with the camera pipeline lease.

## Phase ledger

| Phase | Status | What exists | What does not |
|---|---|---|---|
| CV-001 domain model | IMPLEMENTED, TESTED | `app/domains/vehicles` types for identity, evidence, costs, decisions | Not a second database product catalogue beyond market observations |
| CV-002 auction sources | PARTIAL | Mid Ulster owner-catalogue parser. No unattended crawl | Wilsons, BCA, Manheim, and Copart remain blocked. See PHASE2-AUDIT.md |
| CV-003 identity | IMPLEMENTED, TESTED | Family parser, VIN/listing split, reappearance keys, passenger and parts rejection | No DVLA/NVDF register lookup |
| CV-004 history | PARTIAL, TESTED logic | Mileage rollback, supplied check results, and a DVSA contract that stays off without keys | Cartell and Motorcheck need a subscription. NCT and CVRT have no public API |
| CV-005 provenance | IMPLEMENTED, TESTED | Seven states. Plate shape is not customs status | Revenue still verifies documents. ARIE does not |
| CV-006 tax | IMPLEMENTED, TESTED | Version `ie-cv-tax-2026-09-22`. Separate VRT, NOx, duty, import VAT, auction VAT | Not tax advice. No assumed 10% van duty. No live OMSP lookup |
| CV-007 auction costs | IMPLEMENTED, TESTED | Versioned schedules, whole-hammer premium bands, VAT on premium and lot | No production van fee schedule is loaded |
| CV-008 market book | PARTIAL, TESTED | Append-only Autoza asking observations and dealer feeds. Unknown VAT caps confidence | No realised Irish sale feed. Autoza does not publish VAT or registration |
| CV-009 comps | IMPLEMENTED, TESTED | Scored comps. Generation, wheelbase, fuel, salvage, and duplicate-registration mismatches are rejected | Not an LLM selector |
| CV-010 valuation | IMPLEMENTED, TESTED | Asking, achievable, conservative, quick-sale, confidence cap when sales are thin | No calibration against realised Irish van sales |
| CV-011 reconditioning | PARTIAL, TESTED | Declared-fault reserves plus a non-zero unknown-mechanical reserve | No image model. Photographs are not read |
| CV-012 landed cost | IMPLEMENTED, TESTED | Line-level stack. Unknown lines block the total | — |
| CV-013 risk | IMPLEMENTED | Separate risk lines on the report | No single hidden score |
| CV-014 maximum bid | IMPLEMENTED, TESTED | Cent search over the real fee and tax function | — |
| CV-015 gates | IMPLEMENTED, TESTED | Fail closed. Zero candidates is valid | — |
| CV-016 report | IMPLEMENTED, TESTED | Structured report and `/cv` HTML | — |
| CV-017 dashboard | PARTIAL, TESTED | `/cv` defaults to shadow candidates and can reload stored evaluations | Empty until a case is evaluated. Not a live auction floor |
| CV-018 backtest | PARTIAL, TESTED harness | `evaluate_as_of` hides later observations | No historical auction corpus. Not validated |
| CV-019 shadow live | NOT STARTED | A catalogue paste freezes a snapshot. Native valuation withholds a weak book | No owner-supplied auction catalogue has been run against a stored Autoza book |
| CV-020 certification | NOT CERTIFIED | Thresholds are defined. An empty sample is `NOT_STARTED`, not a pass | None of the thresholds have been measured |

## Why this order

Tax, provenance, and the bid solver do not need a live crawl. Source adapters that would scrape Wilsons, DoneDeal, Adverts.ie, or Carzone were not built. The existing repository already marks those as policy-blocked, and this programme keeps that constraint. A market feed without a licence would make the valuation look live when it is not.

## Acceptance for a shadow candidate

All of these gates must pass: identity, commercial class (homologated N1 goods body, under four seats), history, mileage, provenance, tax, VRT, auction cost, market evidence, valuation confidence, liquidity, condition, reconditioning, downside, profit, freshness, price.

`BUY_CANDIDATE` still has `purchasing_recommendation = false`.

## Promotion thresholds (not met)

Shadow results stay uncertified until all of the following are measured on a pre-registered set, with no lookahead:

- at least 30 historical van evaluations with an outcome known after the decision time
- identity accuracy at least 95% where a VIN or registration was later confirmed
- median absolute percentage error of the conservative value at most 12% where a realised resale exists
- false-positive shadow-candidate rate at most 5%
- zero cases in which an unknown check was treated as a pass
- tax rule version retrieved within 120 days
- market observations for the cohort median age at most 14 days
- an explicit owner decision to allow certified recommendations, which the code does not currently honour

Until then the certification posture is `SHADOW`.

## Tests

`tests/test_cv_engine.py` and `tests/test_cv_http.py`. They cover NI-plate/GB-keeper, €200 VRT without weights, crew van versus panel van, mileage rollback, duplicate observations, sibling comps, stale rules, disappearance versus sale, fee changes, lookahead, and a current bid above the maximum.
