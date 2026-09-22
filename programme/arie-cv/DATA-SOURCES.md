# ARIE-CV data sources

Retrieved and reviewed 2026-09-22. Nothing in this list is fetched by the van engine. `enabled_live_fetchers()` is empty.

| Source | Geography | Role | Status | Constraint |
|---|---|---|---|---|
| Owner manual capture | IE/NI | Lots and market observations | LIVE_MANUAL | The owner supplies a record they are allowed to keep. Not a crawl |
| Wilsons Auctions | IE and NI | Commercial and plant auctions | BLOCKED_POLICY | Public pages exist. No official public API was found. A Dublin plant-auction fee note (15% to €5,000, 10% above, minimum €10, 23% VAT on fees) is plant catalogue copy, not a van schedule, and is not loaded |
| Copart Ireland | IE | Salvage and used, trade members | BLOCKED_CREDENTIALS | Member terms. Fees vary by volume. No credential |
| BCA | GB/NI | Dealer auctions | BLOCKED_CREDENTIALS | Login. No credential, no bypass |
| Manheim | GB/NI | Dealer auctions | BLOCKED_CREDENTIALS | Login. No credential |
| DVSA MOT History API | GB/NI | Mileage and test history | BLOCKED_CREDENTIALS | Official API, key required. Absence is `NOT_CHECKED` |
| Cartell / Motorcheck | IE | Finance, stolen, write-off, Irish history | BLOCKED_EXTERNAL | Paid reports. No subscription |
| DoneDeal | IE | Classified asking prices | BLOCKED_POLICY | Partner API only. Same block as the camera register |
| Adverts.ie | IE | Classifieds | BLOCKED_POLICY | No public aggregation API |
| Carzone | IE | Dealer inventory | BLOCKED_POLICY | No licensed feed |
| eBay Motors | IE/GB/NI | Listings | DISABLED | The existing Browse adapter is camera-filtered and is not called |

## What a market observation stores

Canonical family, listing id, seller type, asking or realised price, VAT presentation, mileage, year, derivative, body, engine/fuel, transmission, location, observed time, status, source. Historical rows are not updated. A later price is a new row. Status values include active, disappeared, realised sale, relisted, withdrawn, expired, and unknown. Only `REALISED_SALE` with a realised price is treated as a sale.

## Fee schedules

A schedule is usable for vans only when `applies_to` is `commercial_vehicles` and premium VAT is known. Tests use an explicit fixture schedule. No Wilsons, BCA, Manheim, or Copart schedule is installed.
