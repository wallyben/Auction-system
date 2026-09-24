# DATA-006B — autonomous Irish market intelligence

Recorded 24 September 2026. `arie-native-v2` is unchanged. CV-019 cohort 001 was not replayed and its snapshot was not edited.

## Architecture

Auction ingest still comes from an owner-supplied catalogue. After parse, ARIE groups ordinary vans by family, body, fuel, and a three-year window, then enqueues `cv-market-search-harvest` on the existing worker queue.

The harvest asks Brave Web Search (`GET https://api.search.brave.com/res/v1/web/search`, header `X-Subscription-Token`) with `site:` queries, `country=IE`, and `extra_snippets=true`. A hit becomes a market observation only when the URL is an individual listing and the snippet contains a year and a plausible full asking price. Common Crawl is enrichment for that URL: the newest collections come from `https://index.commoncrawl.org/collinfo.json`, then the CDX row and WARC range. Archived HTML is not stored. If the capture is missing, the search-index observation remains.

Accepted rows are appended to `cv_market_observations`. They do not replace Autoza rows. Cross-source duplicates share `cross_source_duplicate_group_id` and only the primary row counts as a sample.

## Source classes

| Evidence | Class |
| --- | --- |
| Autoza | `LIVE_API` |
| Brave listing snippet | `SEARCH_INDEX_CURRENT` |
| Common Crawl capture newer than 45 days | `ARCHIVE_RECENT` |
| Older Common Crawl capture | `ARCHIVE_HISTORICAL` |
| No capture | `ARCHIVE_MISS` |

A result with no `page_age` is `SOURCE_AGE_UNKNOWN`. Republic of Ireland text or a `.ie` listing URL is `ROI`. Northern Ireland and Great Britain stay reference markets and are not converted into Irish anchors by FX.

## Query strategy

Strategy 1 is exact family label, exact centre year, and `site:` on donedeal.ie, carsireland.ie, or carzone.ie. Strategy 2 adds the year window and body words. Strategy 3 adds manufacturer aliases (Vauxhall/Opel and the existing sibling platforms) and VAT phrases. Sibling hits are stored as that sibling's family so Native v2 can use them only as adjustment evidence.

Searching stops for a group when Native v2 would already issue a MEDIUM or HIGH conservative resale, or when the hard caps are hit. Defaults: 12 requests per group, 120 per auction, 400 per day. A group harvested inside `CV_SEARCH_MARKET_CACHE_HOURS` (12) reuses the cached provider response.

## Dedupe and VAT

The same registration matches across sites. Otherwise the same family, year, body, normalised dealer, mileage within 2,000 km, and price within 4% collapse to one van. Dealer suffixes such as Ltd and "Van Centre" are stripped. A single generic word is not merged unless it contains a digit, so "M3" can match and "Motors" alone does not.

VAT is taken only from explicit wording. Native v2 still treats only inclusive and exclusive presentations as a known price basis. "No VAT" is stored and is not forced into that basis.

## Cost controls

Usage is stored under `artifacts/runtime/market_search/` (gitignored): requests today, this month, and for the auction. Transient Brave 429 and 5xx responses are retried up to three times. An invalid key or a 400 is not retried.

## Known limitations

This workspace has no `BRAVE_SEARCH_API_KEY` and no `DATABASE_URL`, so the live Stage A proof and the T426 coverage replay were not run. A broad Common Crawl URL filter for DoneDeal returned HTTP 504; exact-URL enrichment is implemented and unit-tested. Search-index evidence is snippet evidence, not a full listing page. Native v2 was not retuned.

## Setup

1. Create a Brave Search API key.
2. Add `BRAVE_SEARCH_API_KEY=<key>` to the environment.
3. Restart the ARIE worker.

`CV_MARKET_SEARCH_ENABLED` and `CV_COMMON_CRAWL_ENABLED` default on. With no key, `/cv` shows `SEARCH PROVIDER NOT CONFIGURED` and Autoza continues.

## T426 evidence

No T426 coverage replay 002 was produced. Cohort 001 was left untouched. Replay output belongs in `artifacts/runtime/` once a key and the stored auction identities are available.
