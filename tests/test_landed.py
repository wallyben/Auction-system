"""Landed cost and max-buy wrapping the existing margin calculator."""

from decimal import Decimal

from app.costs.landed import compute_landed_cost
from app.models.enums import Corridor


def test_domestic_max_buy_is_below_resale() -> None:
    result = compute_landed_cost(
        purchase_price=Decimal("500"),
        currency_to_eur=Decimal("1"),
        corridor=Corridor.IE_DOMESTIC,
        shipping_listed=Decimal("10"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
    )
    assert result.all_in_acquisition_eur > Decimal("500")
    assert result.max_purchase_eur < Decimal("900")


def test_gb_import_vat_increases_all_in_cost() -> None:
    base = dict(
        purchase_price=Decimal("500"),
        currency_to_eur=Decimal("1"),
        shipping_listed=Decimal("20"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
        duty_eur=Decimal("0"),
    )
    domestic = compute_landed_cost(corridor=Corridor.IE_DOMESTIC, import_vat_eur=Decimal("0"), **base)
    imported = compute_landed_cost(corridor=Corridor.GB_TO_IE, import_vat_eur=Decimal("115"), **base)
    assert imported.all_in_acquisition_eur >= domestic.all_in_acquisition_eur


def test_downside_includes_resale_fees() -> None:
    result = compute_landed_cost(
        purchase_price=Decimal("500"),
        currency_to_eur=Decimal("1"),
        corridor=Corridor.IE_DOMESTIC,
        shipping_listed=Decimal("10"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
    )
    optimistic_down = (
        Decimal("800")
        - (Decimal("800") * Decimal("0.129") * Decimal("1.23"))
        - Decimal("9.50")
        - result.all_in_acquisition_eur
    )
    assert result.downside_profit_eur < optimistic_down
    assert result.downside_profit_eur < result.expected_profit_eur


def test_max_buy_does_not_add_extra_fixed_payment() -> None:
    result = compute_landed_cost(
        purchase_price=Decimal("400"),
        currency_to_eur=Decimal("1"),
        corridor=Corridor.IE_DOMESTIC,
        shipping_listed=Decimal("10"),
        expected_resale_eur=Decimal("900"),
        quick_sale_eur=Decimal("800"),
        high_sale_eur=Decimal("1000"),
    )
    assert result.max_purchase_eur > Decimal("0")
    assert result.max_purchase_eur < Decimal("900")
