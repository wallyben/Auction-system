# ARIE-CV data sources

Retrieved and reviewed 2026-09-22, rechecked 2026-09-23. The classification and the legal ingestion path for each source are in `PHASE2-AUDIT.md`. The native estimator is in `NATIVE-MARKET-ENGINE.md`.

`enabled_live_fetchers()` includes `autoza` unless `CV_AUTOZA=0`. eBay vans and dealer URLs stay off until configured. Mid Ulster is owner catalogue capture, not a crawl. DoneDeal, Carzone, CarsIreland, Adverts.ie, and Wilsons are not scraped.

Cartell and Motorcheck are `OPTIONAL_CALIBRATION`. They are not required for a shadow candidate and they are not called.

## What a market observation stores

Canonical family, listing id, seller type, asking or realised price, VAT presentation, mileage, year, derivative, body, engine/fuel, transmission, wheelbase, roof, location, observed time, status, source. Historical rows are not updated. A later price is a new row. Derived listing state is `ACTIVE`, `PRICE_REDUCED`, `PRICE_INCREASED`, `DISAPPEARED`, `RELISTED`, `RETURNED`, or `UNKNOWN`. Only an explicit `REALISED_SALE` with a realised price is a sale.

## Fee schedules

A schedule is usable for vans only when `applies_to` is `commercial_vehicles` and premium VAT is known. A band may be a percentage or a fixed amount. Tests use an explicit fixture schedule. A Mid Ulster cars/vans table is loaded only from the catalogue text the owner supplies, then converted with a fresh FX rate. No Wilsons, BCA, Manheim, or Copart schedule is installed.

