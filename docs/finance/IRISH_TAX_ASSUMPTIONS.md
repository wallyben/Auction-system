# Irish tax assumptions

Operational estimates only. Not tax advice. Do not use ARIE to evade tax.

- Standard VAT 23% (Revenue current rates). Verified against Revenue.ie documentation in-engine (2026-08-23).
- GB is a third country for import VAT. Import VAT is modelled on customs value + duty.
- Intra-EU: acquisition VAT / reverse charge may apply if VAT-registered.
- Domestic second-hand: margin scheme may apply if the owner is VAT-registered and conditions are met.

Scenarios always computed:

- `scenario_private_reseller`
- `scenario_vat_registered_standard`
- `scenario_margin_scheme_if_applicable`

Owner knobs: `OWNER_VAT_REGISTERED`, `OWNER_USES_MARGIN_SCHEME`. Accountant confirmation remains required.
