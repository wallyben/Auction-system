"""Irish acquisition tax posture — operational estimates, not advice."""

from decimal import Decimal

from app.models.enums import AssumptionClass, Corridor
from app.tax.irish import estimate_acquisition_tax


def test_gb_import_flags_import_vat() -> None:
    result = estimate_acquisition_tax(
        corridor=Corridor.GB_TO_IE,
        customs_value_eur=Decimal("1000"),
        seller_vat_registered=True,
        goods_are_second_hand=True,
        owner_vat_registered=True,
        owner_uses_margin_scheme=True,
    )
    assert result.import_vat_eur > 0
    assert result.assumption_class in {
        AssumptionClass.ACCOUNTANT_REQUIRED,
        AssumptionClass.CONFIGURED,
        AssumptionClass.ASSUMPTION,
    }


def test_irish_private_purchase_does_not_invent_import_vat() -> None:
    result = estimate_acquisition_tax(
        corridor=Corridor.IE_DOMESTIC,
        customs_value_eur=Decimal("400"),
        seller_vat_registered=False,
        goods_are_second_hand=True,
        owner_vat_registered=True,
        owner_uses_margin_scheme=True,
    )
    assert result.import_vat_eur == 0
