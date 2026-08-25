"""Category/weight/dimension aware Irish shipping. No blind €9.50 on every SKU."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import money
from app.models.enums import Corridor

# An Post / typical courier bands, last verified as operator assumptions 2026-08-23.
# https://www.anpost.com/Post/Parcels
_OUTBOUND_IE = {
    "trading_cards": Decimal("4.50"),
    "lenses": Decimal("9.50"),
    "cameras": Decimal("11.50"),
    "pro_av": Decimal("10.50"),
    "music_dj": Decimal("18.00"),
    "gpu": Decimal("12.50"),
    "computing": Decimal("16.00"),
    "consumer_electronics": Decimal("12.00"),
    "gaming": Decimal("14.00"),
    "tools": Decimal("15.00"),
    "default": Decimal("11.00"),
}

_WEIGHT_BANDS = (
    (Decimal("0.5"), Decimal("5.90")),
    (Decimal("2"), Decimal("9.50")),
    (Decimal("5"), Decimal("12.50")),
    (Decimal("10"), Decimal("16.00")),
    (Decimal("20"), Decimal("22.00")),
)

_INBOUND = {
    Corridor.IE_DOMESTIC: Decimal("6.50"),
    Corridor.NI_TO_IE: Decimal("10.00"),
    Corridor.GB_TO_IE: Decimal("16.00"),
    Corridor.EU_TO_IE: Decimal("19.00"),
    Corridor.ROW_TO_IE: Decimal("38.00"),
}

_INSURE = {
    "cameras": Decimal("6.00"),
    "lenses": Decimal("6.00"),
    "gpu": Decimal("4.00"),
    "computing": Decimal("5.00"),
    "consumer_electronics": Decimal("4.00"),
    "gaming": Decimal("3.50"),
    "music_dj": Decimal("8.00"),
    "default": Decimal("2.50"),
}
_PACK = Decimal("1.80")


@dataclass(slots=True)
class ShippingEstimate:
    amount_eur: Decimal
    insurance_eur: Decimal
    packaging_eur: Decimal
    service: str
    assumption: str
    notes: str


def _weight_rate(weight_kg: Decimal | None) -> Decimal | None:
    if weight_kg is None:
        return None
    for limit, price in _WEIGHT_BANDS:
        if weight_kg <= limit:
            return price
    return Decimal("35.00")


def estimate_outbound(
    *,
    category: str | None,
    channel: str,
    weight_kg: Decimal | None = None,
    bulky: bool = False,
) -> ShippingEstimate:
    if channel in {"local_ie", "cex_trade_in", "dealer"}:
        return ShippingEstimate(
            Decimal("0") if channel != "local_ie" else Decimal("3.00"),
            Decimal("0"),
            Decimal("0") if channel != "local_ie" else Decimal("1.00"),
            "collection_or_local",
            "configured",
            "Local collection / trade-in. No An Post parcel.",
        )
    if bulky or category == "music_dj" and channel != "local_ie":
        base = Decimal("28.00")
        service = "courier_bulky"
    else:
        base = _weight_rate(weight_kg) or _OUTBOUND_IE.get(category or "", _OUTBOUND_IE["default"])
        service = "an_post_or_courier"
    if channel == "ebay_gb":
        base = money(base + Decimal("8.00"))
        service = "ie_to_gb_tracked"
    insure = _INSURE.get(category or "", _INSURE["default"]) if (base or Decimal("0")) >= Decimal("8") else Decimal("0")
    return ShippingEstimate(
        money(base),
        insure,
        _PACK,
        service,
        "configured",
        "Banded estimate from category/weight. Replace with owner labels when known.",
    )


def estimate_inbound(
    *,
    corridor: Corridor,
    listed: Decimal | None,
    category: str | None,
    weight_kg: Decimal | None = None,
) -> ShippingEstimate:
    if listed is not None:
        return ShippingEstimate(money(listed), Decimal("0"), Decimal("0"), "listed", "measured", "Seller-stated shipping.")
    base = _INBOUND[corridor]
    extra = Decimal("0")
    if category in {"music_dj", "computing"}:
        extra = Decimal("6.00")
    if weight_kg and weight_kg > Decimal("5"):
        extra += Decimal("8.00")
    return ShippingEstimate(
        money(base + extra),
        Decimal("0"),
        Decimal("0"),
        "corridor_default",
        "configured",
        f"Inbound corridor {corridor.value}. Not a carrier quote.",
    )
