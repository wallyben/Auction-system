# Irish valuation methodology

Resale value is the expected achievable **Irish** exit, not a global internet average.

## Evidence types (never mixed)

- `realised_sale` — completed transaction
- `current_asking` — live ask
- `dealer_retail` — shop/guide (Scryfall/Cardmarket)
- `trade_in` / `auction_hammer` / `owner_recorded` / `estimate`

## Weighting

`weight = evidence × recency × territory × product_match × condition_match`

Territory: IE 1.00, NI 0.85, GB 0.70, core EU ~0.55–0.60, other lower. No invented “Ireland premium”.

## Robust stats

Weighted median, MAD outlier rejection, asking-only haircut (×0.90) and confidence cap 0.48.

## What high confidence requires

Exact identity, understood condition, multiple comps, known evidence type, explainable geography, recent observations. A single Irish ask is not an Irish valuation.

## Provenance

Every valuation stores the comps, weights, outliers, and method on `valuations.provenance`.
