# Source access matrix

Investigated in official-API → feed → owner-import order. No CAPTCHA/auth/ToS bypass.

| Source | Official API | Result | Fallback |
|---|---|---|---|
| Scryfall | Public JSON | LIVE comparable | — |
| ECB FX | Public XML | LIVE | — |
| eBay Browse | OAuth client credentials | Adapter complete; BLOCKED_CREDENTIALS without keys | `make ebay-check` |
| Reverb | Public JSON | BLOCKED_TECHNICAL 403 from this IP | Owner token / residential browser export |
| CSV / manual / URL (allow-list) | n/a | LIVE | — |
| Owner sales / marketplace export | n/a | LIVE parsers | — |
| RSS | feedparser | DISABLED until `RSS_URLS` | — |
| DoneDeal, Adverts, Wilsons, John Pye, BidSpotter, i-bidder, CeX storefront | none licensed | BLOCKED_POLICY | Owner CSV / paste |
| Discogs, Cardmarket, Allegro, B-Stock | keyed / partner | BLOCKED_CREDENTIALS | Owner keys |
| Kleinanzeigen, Leboncoin, Marktplaats, Subito, Wallapop, Vinted | none licensed | BLOCKED_POLICY | Owner capture |

Commercial quality is separate from LIVE: Scryfall can be LIVE and still LOW as Irish sold evidence.
