# Realised sales strategy

Asking prices and dealer guides are not sold prices.

## Providers (`SoldEvidenceProvider`)

| Provider | Access | Quality | Status |
|---|---|---|---|
| Owner-recorded sales CSV | Owner upload | High | LIVE (empty until imported) |
| Marketplace export importer | eBay/PayPal-style CSV | High if owner file is genuine | LIVE parser |
| Irish realised-price panel | DB table `sold_evidence` | High when populated | LIVE schema, empty at completion |
| Scryfall / Cardmarket EUR | Official API | Dealer/market, not Irish sold | LIVE as comparable only |
| eBay Marketplace Insights | Official sold-item search if entitled | High | Probe implemented; ordinary Buy apps typically 403/404 |
| eBay completed/sold (Finding) | Deprecated findCompletedItems | High | DO_NOT_CALL |
| eBay Sell Fulfillment/Finances | User OAuth, owner orders only | High | Owner OAuth required |
| Irish auction hammer archives | HTML only | High | No official public API; not scraped |
| CeX / trade-in | Liquidation floor | Medium | No official public API; not implemented |
| Reverb sold | Official API | Asking from this host | BLOCKED_TECHNICAL (403) |

No universal public Irish sold-comp API was found that can be used without scraping, unofficial clients, or a paid licence.

Owner-recorded rows are written into both `owner_sales` and the Irish panel and receive `EvidenceType.OWNER_RECORDED` / quality `high`.
