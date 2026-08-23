# Source access matrix

Verified 2026-08-23 from this runtime. LIVE means a real request returned inventory or a rate.

| Source | Country | Purpose | Official API | Access | Credentials | LIVE status | Last real proof | Fallback |
|---|---|---|---|---|---|---|---|---|
| Reverb | US/EU | Acquisition + asks | Public JSON | `GET /api/listings` | Optional token | BLOCKED_TECHNICAL | HTTP 403 Akamai/HTML 2026-08-23 | CSV / retry from residential IP / token |
| Scryfall | EU guide | Comparables (Cardmarket EUR) | Public JSON | `api.scryfall.com` | No | LIVE | Sol Ring named lookup 200 | None needed |
| ECB FX | EU | EUR reference rates | Public XML | eurofxref-daily.xml | No | LIVE | GBP+USD present 2026-08-23 | Manual rate |
| eBay Browse | IE/GB/EU | Acquisition + asks | Official Browse | OAuth client credentials | Yes | BLOCKED_CREDENTIALS | No keys in env | Owner keys |
| CSV import | IE | Owner capture | n/a | Upload | No | LIVE | Parser always on | — |
| Manual | IE | Paste listing | n/a | Form | No | LIVE | Always on | — |
| RSS generic | EU | Owner feeds | RSS/Atom | feedparser | No | DISABLED until `RSS_URLS` | — | Configure permitted feeds |
| DoneDeal | IE | Acquisition | Dealer API only | Blocked | — | BLOCKED_POLICY | Not called | CSV |
| Adverts.ie | IE | Acquisition | None public | Blocked | — | BLOCKED_POLICY | Not called | CSV |
| Wilsons IE | IE | Auction | None public | Blocked | — | BLOCKED_POLICY | Not called | CSV |
| John Pye | GB | Auction | In-house | Blocked | — | BLOCKED_POLICY | Not called | CSV |
| BidSpotter / i-bidder / BPI | GB | Auction | None public | Blocked | — | BLOCKED_POLICY | Not called | CSV |
| CeX IE | IE | Trade-in bench | None | Blocked | — | BLOCKED_POLICY | Not called | Manual |
| Discogs / Cardmarket | EU | Market | Official, keyed | Blocked | Yes | BLOCKED_CREDENTIALS | — | Owner keys |
| Kleinanzeigen / Leboncoin / Marktplaats / Subito / Wallapop / Vinted / Allegro / B-Stock | EU | Classifieds / liquidation | Partner or none | Blocked | — | BLOCKED_POLICY or CREDENTIALS | Not scraped | CSV |

Scryfall EUR is **dealer/market guide**, never an Irish realised sale.
