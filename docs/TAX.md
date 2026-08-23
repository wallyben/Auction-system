# Irish cost and tax model

Operational estimates only. Not tax advice.

## VAT

Irish standard VAT from 1 Jan 2026 is modelled at **23%** (`VAT_RATE`, Revenue.ie). Confirm with an accountant.

## Corridors

- `ie_domestic` — no import VAT modelled
- `ni_to_ie` — Protocol-sensitive; accountant-required notes
- `gb_to_ie` — third country: import VAT on customs value + duty + transport
- `eu_to_ie` — intra-EU acquisition / reverse charge may apply if VAT-registered
- `row_to_ie` — duty + import VAT; HS code not auto-classified

## Margin scheme

Second-hand margin treatment is a **configurable assumption** (`OWNER_USES_MARGIN_SCHEME`). Eligibility is not certified by ARIE.

## Landed stack

Purchase (FX mid + spread) + inbound ship + payment fee + duty + import VAT (cash) + refurb + Irish platform fee incl. VAT on fee + outbound ship + returns + warranty.

Max buy is solved backwards from target margin using the existing Decimal margin engine for auction fee/VAT shapes.

## Labels

Every tax line carries `measured` | `configured` | `assumption` | `accountant_required`.
