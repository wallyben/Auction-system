# Production proof (this environment, 2026-08-23)

## Pipeline

`source → listing → identity → comps → valuation → landed cost → max buy → score → postgres → dashboard`

Scryfall search `sol ring` retrieved real Cardmarket EUR guides, persisted listings, built dealer comps, haircut expected sale (e.g. €1.53 ask → €1.38 expected), applied Irish fee/shipping stack, and scored **REVIEW** with **negative** expected profit. That is the correct commercial result for a ~€1.50 card with ~€8 outbound postage.

## Live sources

| Source | Result | Proof |
|---|---|---|
| Scryfall | LIVE | Named Sol Ring + search `!"Sol Ring"` HTTP 200, EUR prices stored |
| ECB FX | LIVE | Daily XML 2026-08-21, GBP present, 120 quotes ingested |
| CSV / manual | LIVE | Always-on owner capture |
| Reverb | BLOCKED_TECHNICAL | HTTP 403 HTML challenge from this datacentre IP |
| eBay Browse | BLOCKED_CREDENTIALS | No `EBAY_CLIENT_ID` |
| IE/UK/EU classifieds & auction houses | BLOCKED_POLICY | No scrape |

## Opportunities

24 scored rows. **BUY count = 0.** Flag: `NO_CURRENT_OPPORTUNITY_PASSED_THRESHOLDS`.

Example: Sol Ring print €1.53 → expected Irish resale €1.38, confidence 0.25 (asking/dealer only), expected profit ≈ −€64, max buy €0, decision REVIEW (identity + confidence gates).

## Scan-now

`python -m app.cli scan-source scryfall --query "sol ring" --limit 6` → `status=success`, `listings_seen=6`, `opportunities_written=6`.

Continuous scan: worker APScheduler job `scan-live-sources` when `SCAN_ENABLED=true`. Web does not run the scheduler.

## Tests

- `pytest tests -m "not live"`: 24 passed
- `pytest tests -m live`: 3 passed (Reverb asserted as honest BLOCKED_TECHNICAL on 403)

## Would I spend my own money on ARIE’s BUY button today?

**No.** LIVE evidence is FX + Cardmarket guides, not Irish realised sold comps, and the only scored stock is low-value cards that fail after postage. The engine is useful as a fail-closed desk; it is not a licensed Irish sold-price oracle.
