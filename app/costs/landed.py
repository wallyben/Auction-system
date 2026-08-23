"""Landed-cost engine wrapping the existing Decimal margin calculator."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.money import ZERO, as_decimal, money
from app.margin_engine.calculator import calculate_margin
from app.margin_engine.schemas import MarginInput
from app.models.enums import Corridor


@dataclass(slots=True)
class CostLine:
    code: str
    label: str
    amount_eur: Decimal
    assumption_class: str
    notes: str = ""


@dataclass(slots=True)
class LandedCost:
    purchase_price_eur: Decimal
    all_in_acquisition_eur: Decimal
    expected_resale_eur: Decimal
    expected_net_resale_eur: Decimal
    expected_profit_eur: Decimal
    downside_profit_eur: Decimal
    upside_profit_eur: Decimal
    roi: Decimal
    max_purchase_eur: Decimal
    max_hammer_eur: Decimal | None
    lines: list[CostLine] = field(default_factory=list)
    used_existing_margin_engine: bool = False


SHIPPING_DEFAULTS = {
    Corridor.IE_DOMESTIC: Decimal("8.50"),
    Corridor.NI_TO_IE: Decimal("12.00"),
    Corridor.GB_TO_IE: Decimal("18.00"),
    Corridor.EU_TO_IE: Decimal("22.00"),
    Corridor.ROW_TO_IE: Decimal("45.00"),
}


def _fee(amount: Decimal, rate: Decimal, fixed: Decimal = ZERO) -> Decimal:
    return money(amount * rate + fixed)


def compute_landed_cost(
    *,
    purchase_price: Decimal,
    currency_to_eur: Decimal,
    corridor: Corridor,
    shipping_listed: Decimal | None,
    expected_resale_eur: Decimal,
    quick_sale_eur: Decimal,
    high_sale_eur: Decimal,
    buyer_premium_rate: Decimal = ZERO,
    auction_fee_rate: Decimal = ZERO,
    auction_fixed_fee: Decimal = ZERO,
    vat_scheme: str = "margin",
    vat_rate: Decimal = Decimal("0.23"),
    payment_fee_rate: Decimal = Decimal("0.019"),
    payment_fee_fixed: Decimal = Decimal("0.25"),
    platform_fee_rate: Decimal = Decimal("0.129"),
    platform_fee_vat: Decimal = Decimal("0.23"),
    returns_allowance: Decimal = Decimal("0.03"),
    warranty_allowance: Decimal = Decimal("0.01"),
    refurb_eur: Decimal = ZERO,
    duty_eur: Decimal = ZERO,
    import_vat_eur: Decimal = ZERO,
    fx_spread: Decimal = Decimal("0.012"),
    target_margin_percent: Decimal = Decimal("0.15"),
    risk_percent: Decimal = Decimal("0.08"),
    listing_type: str = "fixed",
    outbound_shipping: Decimal | None = None,
) -> LandedCost:
    """Build a full Irish landed-cost stack. Auction subset uses the existing engine."""
    purchase_eur = money(purchase_price * currency_to_eur)
    fx_cost = money(purchase_eur * fx_spread) if currency_to_eur != Decimal("1") else ZERO
    premium = money(purchase_eur * buyer_premium_rate)
    inbound = money(shipping_listed if shipping_listed is not None else SHIPPING_DEFAULTS[corridor])
    pay_in = _fee(purchase_eur + premium, payment_fee_rate, payment_fee_fixed)

    lines = [
        CostLine("purchase", "Purchase price (EUR)", purchase_eur, "measured"),
        CostLine("fx_spread", "FX spread", fx_cost, "configured", "Configurable spread, not mid-market."),
        CostLine("buyer_premium", "Buyer premium", premium, "configured"),
        CostLine("inbound_shipping", "Inbound shipping", inbound, "configured" if shipping_listed is None else "measured"),
        CostLine("payment_in", "Inbound payment fee", pay_in, "configured"),
        CostLine("duty", "Customs duty", money(duty_eur), "assumption"),
        CostLine("import_vat", "Import VAT (cash, not always a cost)", money(import_vat_eur), "accountant_required"),
        CostLine("refurb", "Refurbishment allowance", money(refurb_eur), "assumption"),
    ]

    auction_fee = ZERO
    vat = ZERO
    max_hammer = None
    used_margin = False
    if listing_type == "auction":
        margin_input = MarginInput(
            expected_resale_price=expected_resale_eur,
            auction_fee_percent=auction_fee_rate,
            auction_fixed_fee=auction_fixed_fee,
            vat_scheme=vat_scheme if vat_scheme in {"margin", "standard"} else "margin",
            vat_rate=vat_rate,
            logistics_cost=inbound + refurb_eur + duty_eur,
            risk_percent=risk_percent,
            target_margin_percent=target_margin_percent,
        )
        result = calculate_margin(margin_input)
        auction_fee = result["breakdown"]["auction_fee"]
        vat = result["breakdown"]["vat"]
        max_hammer = result["max_bid"]
        used_margin = True
        lines.append(CostLine("auction_fee", "Auction fee (existing engine)", auction_fee, "measured"))
        lines.append(CostLine("vat", "VAT on acquisition (existing engine)", vat, "configured"))

    acquisition = money(
        purchase_eur + fx_cost + premium + inbound + pay_in + duty_eur + import_vat_eur + refurb_eur + auction_fee + vat
    )
    platform_fee = money(expected_resale_eur * platform_fee_rate * (Decimal("1") + platform_fee_vat))
    pay_out = _fee(expected_resale_eur, payment_fee_rate, payment_fee_fixed)
    outbound = money(outbound_shipping if outbound_shipping is not None else Decimal("9.50"))
    returns = money(expected_resale_eur * returns_allowance)
    warranty = money(expected_resale_eur * warranty_allowance)
    lines.extend(
        [
            CostLine("platform_fee", "Irish resale platform fee incl. VAT on fee", platform_fee, "configured"),
            CostLine("payment_out", "Outbound payment fee", pay_out, "configured"),
            CostLine("outbound_shipping", "Outbound shipping", outbound, "configured"),
            CostLine("returns", "Returns allowance", returns, "assumption"),
            CostLine("warranty", "Warranty/returns support", warranty, "assumption"),
        ]
    )
    net_resale = money(expected_resale_eur - platform_fee - pay_out - outbound - returns - warranty)
    profit = money(net_resale - acquisition)
    down = money(
        quick_sale_eur
        - money(quick_sale_eur * platform_fee_rate * (Decimal("1") + platform_fee_vat))
        - outbound
        - acquisition
    )
    up = money(
        high_sale_eur
        - money(high_sale_eur * platform_fee_rate * (Decimal("1") + platform_fee_vat))
        - outbound
        - acquisition
    )
    roi = money(profit / acquisition) if acquisition else ZERO

    # Reverse max purchase: keep non-purchase lines fixed.
    variable_rate = (
        Decimal("1")
        + fx_spread
        + buyer_premium_rate
        + payment_fee_rate
        + auction_fee_rate
        + (vat_rate if vat_scheme == "standard" else ZERO)
    )
    fixed = (
        auction_fixed_fee
        + inbound
        + payment_fee_fixed
        + duty_eur
        + import_vat_eur
        + refurb_eur
        + outbound
        + Decimal("0.25")
    )
    target_profit = money(expected_resale_eur * target_margin_percent)
    net_after_resale_fees = money(expected_resale_eur - platform_fee - pay_out - returns - warranty)
    numerator = net_after_resale_fees - target_profit - fixed
    max_purchase = money(numerator / variable_rate) if variable_rate > 0 else ZERO
    if max_purchase < ZERO:
        max_purchase = ZERO
    if max_hammer is not None:
        max_purchase = min(max_purchase, max_hammer)

    return LandedCost(
        purchase_price_eur=purchase_eur,
        all_in_acquisition_eur=acquisition,
        expected_resale_eur=money(expected_resale_eur),
        expected_net_resale_eur=net_resale,
        expected_profit_eur=profit,
        downside_profit_eur=down,
        upside_profit_eur=up,
        roi=roi,
        max_purchase_eur=max_purchase,
        max_hammer_eur=max_hammer,
        lines=lines,
        used_existing_margin_engine=used_margin,
    )
