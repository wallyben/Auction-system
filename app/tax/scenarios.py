"""Explicit Irish tax scenarios. Operational estimates, not advice or evasion."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.models.enums import Corridor
from app.tax.irish import TaxEstimate, estimate_acquisition_tax


@dataclass(slots=True)
class TaxScenario:
    name: str
    estimate: TaxEstimate
    cash_outlay_extra_eur: Decimal


def scenario_matrix(
    *,
    corridor: Corridor,
    customs_value_eur: Decimal,
    goods_are_second_hand: bool,
    vat_rate: Decimal,
) -> list[TaxScenario]:
    private = estimate_acquisition_tax(
        corridor=corridor,
        customs_value_eur=customs_value_eur,
        seller_vat_registered=False,
        goods_are_second_hand=goods_are_second_hand,
        owner_vat_registered=False,
        owner_uses_margin_scheme=False,
        vat_rate=vat_rate,
    )
    vat_std = estimate_acquisition_tax(
        corridor=corridor,
        customs_value_eur=customs_value_eur,
        seller_vat_registered=True,
        goods_are_second_hand=goods_are_second_hand,
        owner_vat_registered=True,
        owner_uses_margin_scheme=False,
        vat_rate=vat_rate,
    )
    margin = estimate_acquisition_tax(
        corridor=corridor,
        customs_value_eur=customs_value_eur,
        seller_vat_registered=False,
        goods_are_second_hand=goods_are_second_hand,
        owner_vat_registered=True,
        owner_uses_margin_scheme=True,
        vat_rate=vat_rate,
    )
    return [
        TaxScenario("scenario_private_reseller", private, private.import_vat_eur + private.duty_eur),
        TaxScenario("scenario_vat_registered_standard", vat_std, vat_std.import_vat_eur + vat_std.duty_eur),
        TaxScenario("scenario_margin_scheme_if_applicable", margin, margin.import_vat_eur + margin.duty_eur),
    ]
