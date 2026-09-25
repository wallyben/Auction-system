# ARIE-CV tax model

Operational calculations from Revenue pages retrieved 2026-09-22. Not tax advice. Rule version: `ie-cv-tax-2026-09-22`.

## Sources

- VRT categories and €200 vans: [Applying the tax](https://www.revenue.ie/en/vrt/calculating-vrt/applying-tax.aspx), published 21 July 2026, and VRT Manual Part 01A.
- VAT 23% from 1 January 2026: [Current VAT rates](https://www.revenue.ie/en/vat/vat-rates/search-vat-rates/current-VAT-rates.aspx), published 1 January 2026.
- GB and NI: [Importing vehicles from GB and NI](https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/index.aspx) and [Registering used vehicles from NI](https://www.revenue.ie/en/vrt/registration-of-imported-used-vehicles/registering-vehicles-from-ni.aspx), published 24 August 2026.
- Import VAT base: [VAT and Customs Duty](https://www.revenue.ie/en/vrt/calculating-vrt/vat-customs-duty.aspx), published 9 July 2026.
- Preferential origin is not implied by a GB registration: Revenue CCC note 79.

## Provenance and border charges

| State | Customs duty | Import VAT | Extra VRT |
|---|---|---|---|
| ROI_NATIVE | 0, proven from an Irish registration certificate | 0 | 0, already registered |
| NI_PRE_2021_PROVEN | 0 | 0 | Calculated |
| NI_POST_2020_IMPORT_PROVEN | 0 | 0 | Calculated |
| LIKELY_NI_NEEDS_DOCUMENTS | Unknown | Unknown | Not confirmed |
| GB_TO_NI_UNPROVEN | Unknown | Unknown | Not confirmed |
| GB_ORIGIN | 0 only if preferential origin is proven. Otherwise the caller must supply a TARIC rate. 10% is not assumed | 23% of customs value plus duty, when both exist | Calculated |
| UNKNOWN | Unknown | Unknown | Not confirmed |

NI pre-2021 requires an original NI V5C, NI service history, NI MOT history, a pre-2021 NI test, and no GB history in the bundle. A plate or an NI auction yard is not enough. Post-2020 clearance requires an NI import declaration whose VIN matches.

A determined GB origin can pass the provenance gate and still fail the tax gate when duty or customs value is missing.

## VRT

€200 is confirmed only when a CoC, NSSTA, or IVA says EU category N1, seats are fewer than 4, and technically permissible maximum laden mass is strictly greater than 130% of mass in service. Electric N1 vans use 125% under the rule in force since 1 January 2025. Equality does not qualify.

Without that document the state is `VRT_REQUIRES_DATA` or `VRT_LIKELY`. Likely is not used in the bid.

Other N1 vans use the Category B CO2 table in force since 1 July 2025, applied to a Revenue OMSP:

- CO2 up to and including 120 g/km: 8% or €160, whichever is greater
- above 120 g/km: 13.3% or €266, whichever is greater

An Irish asking price is rejected as an OMSP. NOx is not added to confirmed Category B.

N1 vehicles with four or more seats, without separate passenger and cargo units at manufacture, are calculated on the Category A CO2 table plus the NOx levy. Electrics are excluded from NOx. Diesel NOx is capped at €4,850 and other fuels at €600. The published 120 mg/km diesel example is €1,800. A crew van fails the commercial-class gate even if Category A VRT can be computed.

Auction VAT, import VAT, duty, VRT, NOx, and registration are separate lines. Import VAT is not treated as recoverable.

## Auction VAT

Standard-rated, margin scheme, none, or unknown. Unknown blocks the cost stack. Input VAT on a standard-rated van is removed from the economic cost only when the owner is marked VAT-registered, a VAT invoice is expected, and the van is homologated N1. That recovery is labelled estimated.
