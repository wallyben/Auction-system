"""Irish localisation of foreign evidence. No invented Ireland premium."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ONE, ZERO, as_decimal, money
from app.models.enums import Corridor, EvidenceType

EVIDENCE_WEIGHT = {
    EvidenceType.REALISED_SALE: Decimal("1.00"),
    EvidenceType.AUCTION_HAMMER: Decimal("0.85"),
    EvidenceType.TRADE_IN: Decimal("0.70"),
    EvidenceType.CURRENT_ASKING: Decimal("0.45"),
    EvidenceType.DEALER_RETAIL: Decimal("0.35"),
    EvidenceType.OWNER_RECORDED: Decimal("0.90"),
    EvidenceType.ESTIMATE: Decimal("0.15"),
}

TERRITORY_WEIGHT = {
    "IE": Decimal("1.00"),
    "NI": Decimal("0.85"),
    "GB": Decimal("0.70"),
    "DE": Decimal("0.60"),
    "FR": Decimal("0.55"),
    "NL": Decimal("0.55"),
    "BE": Decimal("0.55"),
    "ES": Decimal("0.50"),
    "IT": Decimal("0.50"),
    "PL": Decimal("0.45"),
    "US": Decimal("0.30"),
    "UN": Decimal("0.25"),
}

PLATFORM_FEE_IE = Decimal("0.129")  # configurable assumption, not a fee quote
PLATFORM_FEE_VAT = Decimal("0.23")


@dataclass(slots=True)
class LocalisationResult:
    adjusted_eur: Decimal
    corridor: Corridor
    notes: list[str]
    assumption_class: str


def corridor_for(country: str) -> Corridor:
    country = (country or "UN").upper()
    if country in {"IE"}:
        return Corridor.IE_DOMESTIC
    if country in {"NI", "GB-NIR"}:
        return Corridor.NI_TO_IE
    if country in {"GB", "UK"}:
        return Corridor.GB_TO_IE
    if country in {"DE", "FR", "NL", "BE", "ES", "IT", "PL", "AT", "PT", "SE", "DK", "FI", "IE"}:
        return Corridor.EU_TO_IE
    return Corridor.ROW_TO_IE


def to_eur(amount: Decimal, currency: str, eur_per_unit: Decimal) -> Decimal:
    currency = currency.upper()
    if currency == "EUR":
        return money(amount)
    if eur_per_unit <= ZERO:
        raise ValueError("FX rate must be positive")
    return money(amount * eur_per_unit)


def localise_asking_to_irish_resale(
    *,
    price: Decimal,
    currency: str,
    country: str,
    shipping: Decimal | None,
    evidence_type: EvidenceType,
    fx_eur: Decimal,
    inbound_shipping_eur: Decimal,
    import_vat_eur: Decimal = ZERO,
    duty_eur: Decimal = ZERO,
) -> LocalisationResult:
    """Convert a foreign observation into an Irish-relevant EUR figure.

    Asking prices are never treated as realised Irish sale prices.
    Foreign retail is discounted because it is not an Irish exit.
    """
    notes: list[str] = []
    amount = to_eur(price, currency, fx_eur)
    if shipping:
        amount += to_eur(shipping, currency, fx_eur)
        notes.append("Included listed shipping before corridor adjustment.")
    corridor = corridor_for(country)
    if corridor is Corridor.IE_DOMESTIC:
        notes.append("Irish observation. No geographic invention applied.")
        return LocalisationResult(amount, corridor, notes, "measured")
    amount += inbound_shipping_eur
    amount += import_vat_eur
    amount += duty_eur
    notes.append(f"Corridor {corridor.value}: added modelled inbound costs.")
    if evidence_type is EvidenceType.CURRENT_ASKING:
        notes.append("Asking price, not a realised sale.")
    if evidence_type is EvidenceType.DEALER_RETAIL:
        notes.append("Dealer retail includes unsold-shop margin; down-weighted later.")
    return LocalisationResult(money(amount), corridor, notes, "configured")


def irish_net_proceeds(expected_sale: Decimal, *, fee_rate: Decimal = PLATFORM_FEE_IE, fee_vat: Decimal = PLATFORM_FEE_VAT, outbound_shipping: Decimal = Decimal("9.50"), returns_allowance: Decimal = Decimal("0.03")) -> Decimal:
    fee = expected_sale * fee_rate * (ONE + fee_vat)
    returns = expected_sale * returns_allowance
    return money(expected_sale - fee - outbound_shipping - returns)
