# Source access matrix

Investigated in official-API → feed → owner-import order. No CAPTCHA/auth/ToS bypass.

| Source | Official API | Result | Fallback |
|---|---|---|---|
| Scryfall | Public JSON | LIVE comparable | — |
| ECB FX | Public XML | LIVE | — |
| eBay Browse | OAuth client credentials | **LIVE (sandbox)** with owner SBX keys 2026-08-23. Token + Browse search 200. Dummy inventory only. `PRODUCTION_SOURCE_PASS` blocks BUY_READY. Production keys not supplied. | Production App ID when ready; no code change |
| Reverb | Public JSON | BLOCKED_TECHNICAL 403 from this IP | Owner token / residential browser export |
| CSV / manual / URL (allow-list) | n/a | LIVE | — |
| Owner sales / marketplace export | n/a | LIVE parsers | — |
| RSS | feedparser | DISABLED until `RSS_URLS` | — |
| DoneDeal, Adverts, Wilsons, John Pye, BidSpotter, i-bidder, CeX storefront | none licensed | BLOCKED_POLICY | Owner CSV / paste |
| Discogs, Cardmarket, Allegro, B-Stock | keyed / partner | BLOCKED_CREDENTIALS | Owner keys |
| Kleinanzeigen, Leboncoin, Marktplaats, Subito, Wallapop, Vinted | none licensed | BLOCKED_POLICY | Owner capture |

Commercial quality is separate from LIVE: Scryfall can be LIVE and still LOW as Irish sold evidence.
