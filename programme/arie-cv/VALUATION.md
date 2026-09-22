# ARIE-CV valuation and bid

Deterministic given the observations supplied. Not calibrated to Irish realised sales. Confidence is capped at 0.62 when fewer than three realised sales support the cohort.

## Comps

Same manufacturer and model family are required. Berlingo does not comp Partner, Combo, Doblò, or Proace City. Fuel and goods-versus-people body mismatches are rejected. Year gaps over six years and mileage ratios outside 0.45 to 2.2 are rejected. Remaining comps need a score of at least 55. Close comps score at least 75.

The report lists accepted comps and the points that produced the score.

## Four values

- Market asking: median asking price after a MAD screen.
- Expected achievable: median of realised prices when at least three exist, blended with haircut asking prices. Otherwise asking median times 0.85.
- Conservative: the lower of expected achievable and the 25th percentile of haircut asking prices (realised prices included when present).
- Quick sale: conservative times a liquidity haircut (deep 5%, adequate 8%, thin 15%, illiquid or unknown 25%).

The 15% asking haircut is an estimate, not a measured clearance rate. Disappeared, withdrawn, expired, and unknown rows are not sales.

## Liquidity

Adequate means at least 12 active asking listings and a median age of at most 45 days. Deep means at least 25 and a median age of at most 30 days. Illiquid and thin fail the liquidity gate. The gate therefore requires adequate or deep supply.

## Freshness and sample

Observations older than 14 days are out of the current book. A shadow candidate needs at least eight eligible comps and five close comps, confidence at least 0.60, and a fresh book. Asking-only confidence cannot exceed 0.62, so the sample has to be tight to pass.

## Repairs

Declared faults map to configured expected and downside reserves. An uninspected van adds €450 expected and €1,500 downside, and the condition gate stays failed. An inspected van still carries €150 expected and €400 downside. These are policy reserves, not quotes.

## Landed cost and maximum hammer

Expected all-in and downside all-in are the sum of visible lines: hammer, premium, premium VAT, lot VAT treatment, payment, transport, duty, import VAT, VRT, NOx, registration, and repairs. A missing line blocks the total.

Selling friction is the greater of 8% of the conservative value and €350, labelled estimated.

The maximum hammer is the highest cent at which all of the following hold, using the actual premium band and the tax function at that hammer:

- conservative resale minus selling friction minus expected all-in is at least €800
- that profit divided by expected all-in is at least 15%
- quick-sale minus selling friction minus downside all-in is at least zero

A current bid above that hammer, with every other gate passed, is `PRICE_TOO_HIGH`.

## Rank

Shadow candidates sort by expected profit at the current bid, times valuation confidence, times a liquidity factor (deep 1, adequate 0.85, thin 0.5, otherwise 0). Ties break on headroom, then confidence, then the liquidity factor. The factors are in `policy.py`.
