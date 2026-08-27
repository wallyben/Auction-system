# Sold-data provider recommendation

ARIE needs market-wide realised transactions (evidence class A/B) to answer a real-money buy question. Asking prices (F) and guides (G) are not that.

## Facts

1. **eBay Marketplace Insights** is the only official programmatic source of eBay completed sales. The documented endpoint is `GET /buy/marketplace_insights/v1_beta/item_sales/search` with required `category_ids`. It is Limited Release. Current eBay documentation says it is restricted and not open to new users. Prior Production probe (2026-08-25) returned **HTTP 403 / NOT_ENTITLED**. This environment has no credentials, so the local probe is **AUTH_ERROR**. Status: `EBAY_MARKETPLACE_INSIGHTS = BLOCKED_EXTERNAL_ACCESS`. Stop trying to circumvent it.

2. **eBay Product Research / Terapeak** is a Seller Hub dashboard (~3 years of aggregated research). There is **no official API** and **no licensed bulk automation**. Browser scraping of `/sh/research/api/search` is out of bounds. The owner may use Seller Hub by hand and upload an export they are allowed to download. Aggregates stay class **E**. They are never exploded into fake tickets.

3. **Owner Fulfillment OAuth** works and is connected in Production. `last_ingest_count = 0` because the owner has no eBay sales. Even after sales exist, those rows are class **C** (owner realised), not market-wide comps.

4. **Licensed third parties** that actually match cameras/phones/GPUs with eBay ticket-level rights were **not found**. PriceCharting is a legitimate paid API but for games/collectibles guides. MPB and KEH are real dealers with no public licensed sold-ticket API. WorthPoint ToS forbids commercial reuse of their content. SoldComps / Apify / RapidAPI sold scrapers are scrape-without-rights and are rejected.

## Chosen strategy

Priority 1 is Marketplace Insights **if actually entitled**. It is not.

Priority 2 is a licensed commercial sold-data provider **if commercially sensible**. None cleared the bar for the first camera category.

Priority 3 is the bootstrap that is actually available:

- Owner-exported official Product Research/Terapeak files (class E if aggregate; ticket-level only when a real sold date+price row exists).
- Owner OAuth / owner CSV as class C calibration once the owner actually sells.
- Empty Irish realised panel until genuine tickets exist.
- Reverb remains class F, DJ/pro-AV only, strict identity, never Ireland expected resale.
- Scryfall remains class G for cards only.

This is **not** continuous automated sold coverage. The system must stay `ARIE_DATA_VALIDATION_REQUIRED` until genuine realised evidence exists.

## Why this is the honest commercial path

One empty but truthful book is better than 10,000 rows priced from US Reverb asks. Integrating a scrape API would manufacture BUY_READY from stolen sold data. We will not do that.
