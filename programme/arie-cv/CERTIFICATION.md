# ARIE-CV certification

Current posture: **NOT CERTIFIED**. Shadow only.

`BUY_CANDIDATE` means every coded gate passed on the evidence in that case. It does not mean the owner should buy. `purchasing_recommendation` is false and there is no code path that places a bid.

## Measured

- Unit and HTTP tests in `tests/test_cv_engine.py` and `tests/test_cv_http.py` pass, including the adversarial cases named in the programme.
- The non-live ARIE suite was run on this branch after the van package was added.

## Not measured

- Identity accuracy on real vans
- Commercial classification precision against confirmed homologation
- Tax and provenance correctness against later NCTS or Revenue outcomes
- A live Autoza search on 2026-09-23 returned commercial-van asking prices. That probe was not stored as a market book and it is not a certification sample.
- Valuation error against realised Irish resales
- Quick-sale calibration
- Candidate precision and false-positive rate
- Repair-reserve calibration
- Data freshness on a live book
- Source reliability over 30 attempts
- Max-bid calibration against later all-in outcomes
- Live source uptime
- A historical corpus without lookahead leakage, beyond the harness that hides future observations

An empty sample is `NOT_STARTED`. It is not a pass. The numeric definitions are in `app/domains/vehicles/certification_metrics.py` and are not relaxed.

## Blocked external work

Live auction inventory is owner-captured for Mid Ulster and credential-blocked for BCA, Manheim, Copart, and eBay. DVSA MOT needs the owner to register. Cartell or Motorcheck need a paid subscription. DoneDeal, Adverts.ie, Carzone, CarsIreland, and Wilsons pages are not scraped. A consented dealer feed is the Irish asking-price path.

## Promotion

The numeric thresholds are in `PROGRAMME.md`. None have been scored. Do not describe this build as production-ready, buy-ready, or certified.
