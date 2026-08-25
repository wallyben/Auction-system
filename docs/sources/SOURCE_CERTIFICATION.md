# Source certification

Statuses: LIVE, DEGRADED, BLOCKED_CREDENTIALS, BLOCKED_POLICY, BLOCKED_TECHNICAL, DISABLED, PRODUCTION_KEYSET_DISABLED_COMPLIANCE, plus `commercial_quality` HIGH/MEDIUM/LOW/UNKNOWN.

`PRODUCTION_KEYSET_DISABLED_COMPLIANCE` is not a bad-credentials status. eBay Production OAuth `401 invalid_client` is the documented result when the Production keyset is disabled pending Marketplace Account Deletion/Closure notification compliance. Do not regenerate keys. Complete the notification endpoint in the eBay Developer portal, then re-run `make ebay-check`.

A source may be technically LIVE and commercially LOW. Scryfall is the example: official, fresh, and not an Irish realised sale.

Each source now stores:

- `TECHNICAL_STATUS`
- `COMMERCIAL_DATA_QUALITY`
- `ACQUISITION_OR_VALUATION_ROLE`
- `REAL_MONEY_ELIGIBLE`
- `SOLD_EVIDENCE`

eBay Production Browse is real-money eligible only when OAuth+Browse are LIVE **and** `ebay_api_env=production`. It still has `SOLD_EVIDENCE=false` unless Marketplace Insights (or an owner export) is separately proven.

Sandbox Browse may be LIVE technically and is never `REAL_MONEY_ELIGIBLE`.
