"""Irish VAT / import posture. Operational estimates, not tax advice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.core.money import ZERO, money
from app.models.enums import AssumptionClass, Corridor

REVENUE_VAT_RATES = "https://www.revenue.ie/en/vat/vat-rates/search-vat-rates/current-vat-rates.aspx"
REVENUE_MARGIN = "https://www.revenue.ie/en/vat/vat-on-goods-and-services/margin-scheme/index.aspx"
REVENUE_IMPORTS = "https://www.revenue.ie/en/customs/businesses/importing/index.aspx"


@dataclass(slots=True)
class TaxEstimate:
    corridor: Corridor
    vat_rate: Decimal
    import_vat_eur: Decimal
    duty_eur: Decimal
    margin_scheme_eligible: bool | None
    assumption_class: AssumptionClass
    evidence_url: str
    notes: list[str]
    last_verified_at: datetime


def estimate_acquisition_tax(
    *,
    corridor: Corridor,
    customs_value_eur: Decimal,
    seller_vat_registered: bool | None,
    goods_are_second_hand: bool,
    owner_vat_registered: bool,
    owner_uses_margin_scheme: bool,
    vat_rate: Decimal = Decimal("0.23"),
    duty_rate: Decimal = ZERO,
) -> TaxEstimate:
    notes: list[str] = [
        "This is an operational estimate. An Irish accountant must confirm treatment.",
        f"Standard Irish VAT rate used: {vat_rate} (Revenue current rates page).",
    ]
    duty = money(customs_value_eur * duty_rate)
    import_vat = ZERO
    eligible: bool | None = None
    klass = AssumptionClass.ACCOUNTANT_REQUIRED

    if corridor is Corridor.IE_DOMESTIC:
        eligible = bool(goods_are_second_hand and owner_uses_margin_scheme and owner_vat_registered)
        notes.append("Domestic Irish purchase. Import VAT not modelled.")
        if seller_vat_registered is False and goods_are_second_hand:
            notes.append("Private/non-VAT seller: margin scheme may be available if conditions met.")
        klass = AssumptionClass.CONFIGURED
        evidence = REVENUE_MARGIN
    elif corridor is Corridor.NI_TO_IE:
        notes.append("Northern Ireland goods often follow EU VAT territory rules; still confirm Protocol treatment.")
        eligible = bool(goods_are_second_hand and owner_uses_margin_scheme)
        evidence = REVENUE_VAT_RATES
    elif corridor is Corridor.EU_TO_IE:
        notes.append("Intra-EU acquisition. Reverse charge / acquisition VAT may apply if VAT-registered.")
        eligible = bool(goods_are_second_hand and owner_uses_margin_scheme)
        evidence = REVENUE_VAT_RATES
    elif corridor is Corridor.GB_TO_IE:
        import_vat = money((customs_value_eur + duty) * vat_rate)
        notes.append("GB is third-country for VAT. Import VAT is typically due on customs value + duty + transport.")
        notes.append("Margin scheme generally does not convert a GB import into a no-import-VAT purchase.")
        eligible = False
        evidence = REVENUE_IMPORTS
    else:
        import_vat = money((customs_value_eur + duty) * vat_rate)
        notes.append("Rest-of-world import. Duty and import VAT may apply. HS code not classified automatically.")
        eligible = False
        evidence = REVENUE_IMPORTS

    return TaxEstimate(
        corridor=corridor,
        vat_rate=vat_rate,
        import_vat_eur=import_vat,
        duty_eur=duty,
        margin_scheme_eligible=eligible,
        assumption_class=klass,
        evidence_url=evidence,
        notes=notes,
        last_verified_at=datetime(2026, 8, 23, tzinfo=timezone.utc),
    )
