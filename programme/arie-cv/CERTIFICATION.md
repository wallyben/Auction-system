# ARIE-CV certification

Current posture: **NOT CERTIFIED**. Shadow only.

`BUY_CANDIDATE` means every coded gate passed on the evidence in that case. It does not mean the owner should buy. `purchasing_recommendation` is false and there is no code path that places a bid.

## Measured

- Unit and HTTP tests in `tests/test_cv_engine.py` and `tests/test_cv_http.py` pass, including the adversarial cases named in the programme.
- The non-live ARIE suite was run on this branch after the van package was added.

## Not measured

- Identity accuracy on real vans
- Tax classification against NCTS outcomes
- Valuation error against realised Irish resales
- Quick-sale calibration
- Repair-reserve calibration
- False-positive and false-negative rates
- Live source uptime
- A historical corpus without lookahead leakage, beyond the harness that hides future observations

## Blocked external work

Live auction inventory, DVSA MOT, and Irish history/finance providers need credentials or a licence. DoneDeal, Adverts.ie, Carzone, and Wilsons pages are not scraped.

## Promotion

The numeric thresholds are in `PROGRAMME.md`. None have been scored. Do not describe this build as production-ready, buy-ready, or certified.
