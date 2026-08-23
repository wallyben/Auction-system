# Source certification

Statuses: LIVE, DEGRADED, BLOCKED_CREDENTIALS, BLOCKED_POLICY, BLOCKED_TECHNICAL, DISABLED, plus `commercial_quality` HIGH/MEDIUM/LOW/UNKNOWN.

A source may be technically LIVE and commercially LOW. Scryfall is the example: official, fresh, and not an Irish realised sale.

Each source now stores:

- `TECHNICAL_STATUS`
- `COMMERCIAL_DATA_QUALITY`
- `ACQUISITION_OR_VALUATION_ROLE`
- `REAL_MONEY_ELIGIBLE`
- `SOLD_EVIDENCE`

eBay Production Browse is real-money eligible only when OAuth+Browse are LIVE **and** `ebay_api_env=production`. It still has `SOLD_EVIDENCE=false` unless Marketplace Insights (or an owner export) is separately proven.

Sandbox Browse may be LIVE technically and is never `REAL_MONEY_ELIGIBLE`.
