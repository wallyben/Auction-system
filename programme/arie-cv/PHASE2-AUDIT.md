# ARIE-CV Phase 2 audit

Audit date: 2026-09-23. Branch `cursor/arie-cv-foundation-7886`. Base SHA before this phase: `41f58271781d4e81a3ea97207b302f66ec6d9ddc` (PR #23, draft, not merged).

This file records what was inspected, which sources are actually reachable, and which blockers are external rather than unimplemented.

## 1. Repository state that was audited

PR #23 is not on `main`. It is the open draft pull request "Add ARIE-CV shadow engine for commercial vans" on `wallyben/Auction-system`. The engine lives in `app/domains/vehicles` and does not call the camera identity path.

Inspected and left in place, because the deterministic tests still pass:

- fail-closed evidence, provenance, tax/VRT, auction costs, landed cost, maximum bid, gates
- append-only `cv_market_observations` and migration `20260922_0011`
- comparable scoring and the four-way valuation
- `/cv` owner page and `tests/test_cv_engine.py`, `tests/test_cv_http.py`
- worker queue and scheduler, which previously had no van jobs

Defects this phase changed, with tests:

- the candidate board was process-local
- comparable selection penalised a different generation or wheelbase instead of rejecting it
- the same listing could be counted once per price observation
- damaged or duplicate listings were not rejected
- UK auction VAT was forced through the Irish 23% rate
- a flat buyer-premium band could not be represented
- Cartell/Motorcheck was marked `BLOCKED_EXTERNAL` even though the blocker is a subscription the owner can buy

`enabled_live_fetchers()` stays empty until `EBAY_CLIENT_ID`/`EBAY_CLIENT_SECRET` are set or `CV_DEALER_FEED_URLS` is set. No auction website is crawled.

## 2. Source classification

| Source | Class | Why |
|---|---|---|
| Mid Ulster Auctions ("Dulster") | MANUAL_ONLY | Public timed commercial-van catalogues exist at `online.midulsterauctions.com`. `robots.txt` allows a crawl with `Crawl-delay: 120` and disallows only `/login`, `/signup`, and `/search`. The terms separately say website text may not be copied without written consent. No official catalogue API was found. Owner paste/upload is implemented. Unattended download is not. |
| Wilsons Auctions | BLOCKED_POLICY | Public commercial catalogues exist for Dublin, Belfast, and Portadown. No official public API was found. Third-party scrapers are not a permitted feed. A plant-auction fee note is not loaded as a van schedule. |
| BCA | BLOCKED_CREDENTIALS | Buyer login. No ARIE credential and no public developer feed is configured. |
| Manheim | BLOCKED_CREDENTIALS | Buyer login. No credential. |
| Copart Ireland | BLOCKED_CREDENTIALS | Trade membership. Fees vary by volume. No credential. |
| Merlin, Herman & Wilkinson, and other ROI general auctions | NOT_REQUIRED | Not the first van source. No official van feed was verified in this pass. They are not scraped. |
| Fleet and leasing disposals (Ayvens, ALD, Arval and similar) | NOT_REQUIRED | Stock is normally sold through BCA, Manheim, or Wilsons, not a public van API. |
| Government / council disposals | NOT_REQUIRED | Often entered through Wilsons or Mid Ulster. eTenders is a tender board, not a van catalogue. |
| eBay Browse, van search | BLOCKED_CREDENTIALS until keys exist, then LIVE_AUTHENTICATED | Official Buy Browse API already used for cameras. A separate van query is implemented and stays off until the eBay app keys are present. It does not use the camera category filter. |
| DoneDeal | BLOCKED_POLICY | A dealer API exists and is restricted to that dealer's own site. The published API usage policy prohibits aggregation and comparison platforms unless DoneDeal approves it in writing. |
| Carzone | BLOCKED_POLICY | No public stock API or export. The site's internal JSON is not a permitted feed. |
| CarsIreland | BLOCKED_POLICY | No public inventory API was found. |
| Adverts.ie | BLOCKED_POLICY | No public aggregation API. |
| Owner-consented dealer CSV/JSON/URL | BLOCKED_CREDENTIALS until a feed is configured, then LIVE_AUTHENTICATED | This is the lawful Irish asking-price path. The parser is implemented. A URL is fetched only from `CV_DEALER_FEED_URLS`. |
| DVSA MOT History API | BLOCKED_CREDENTIALS | Official REST API, including Northern Ireland tests since 2017. Registration is free. The client contract and env vars are implemented. No call is made without keys. |
| Cartell | BLOCKED_CREDENTIALS | Paid Irish history, finance, write-off, and stolen checks. The owner can subscribe. No key is configured, so those checks stay `NOT_CHECKED`. |
| Motorcheck | BLOCKED_CREDENTIALS | Same position as Cartell. A trade subscription is the blocker, not an unavailable provider. |
| NCTS / NCT | MANUAL_ONLY | No public history API. The owner can attach an NCT report. |
| RSA CVRT | MANUAL_ONLY | No public history API. MOT/PSV expiry printed on a Mid Ulster lot is a catalogue claim, not a register check. |
| Irish Revenue VRT calculator | NOT_REQUIRED for this phase | OMSP lookup is not an inventory feed. Tax rules already in `tax.py` stay versioned. Absence of weight data still fails VRT. |

## 3. Mid Ulster (Dulster)

The owner name "Dulster" is Mid Ulster Auctions, Magherafelt, `midulsterauctions.com` / `online.midulsterauctions.com`. Current public sales include vans, cars, and HGVs. Lot pages that are publicly described expose, when the vendor filled them in:

- lot id and title
- registration (`Serial/Reg#`)
- year
- mileage and miles/km unit
- VAT Yes/No
- vendor and vendor disclosure
- document status
- MOT/PSV expiry
- buyer premium by reference to the catalogue header
- photos on the lot page
- current or starting bid on some lots
- auction close on the catalogue header

VIN is not on the public summary. Buyer premium for cars and vans, when printed in the catalogue, is a flat sterling band (£75 / £100 / £175 / £250 / £300) plus VAT, not a percentage. HGV and council entries use different bands. The parser loads the cars/vans table only when that table is in the paste. It does not invent the band if the paste omits it.

UK lot VAT is 20% when the lot says VAT Yes. It is not the Irish 23% import VAT. Import VAT and VRT remain separate and still fail closed without provenance and homologation.

## 4. What was implemented after the audit

- Owner catalogue capture at `POST /cv/capture/mid-ulster`, parser `mid-ulster-catalogue-1`, feeding `evaluate_vehicle`
- Append-only dealer feed parser and runtime market book
- eBay van observation mapper, executed only with official credentials
- Listing lifecycle: `ACTIVE`, `PRICE_REDUCED`, `DISAPPEARED`, `RELISTED`, `RETURNED`, `UNKNOWN`. A disappearance is not a sale
- Latest observation per listing is the comp. Generation, wheelbase, fuel, salvage, and duplicate registration mismatches are rejected
- Asking-to-achievable haircut stays at least 15% without realised sales, and widens when listings age or prices are cut. No sold price is invented
- DVSA setup contract and payload parser that refuses to invent NI jurisdiction
- Owner document types. `force_pass` is rejected. Structured V5C, CoC, NI declaration, and VIN fields are the only ones applied
- Image analyzer interface. No provider means no findings and no programme block
- Postgres tables `cv_evaluations`, `cv_source_state`, `cv_owner_evidence` in migration `20260923_0012`
- Worker jobs `cv-auction-ingest`, `cv-market-refresh`, `cv-history-enrich`, `cv-revalue`, `cv-shadow-refresh`
- Schedules: market and auction health every 6 hours, history every 12 hours, shadow report daily. No near-close poll, because no unattended auction fetcher is enabled
- `/cv` defaults to shadow candidates and downgrades a cached buy that is older than 14 days or past its close

## 5. What is not live

No Irish retail feed and no auction catalogue were fetched during this phase. Shadow certification has not started on real outcomes. `BUY_CANDIDATE` remains `purchasing_recommendation = false`.
