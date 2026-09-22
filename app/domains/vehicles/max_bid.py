"""Maximum safe hammer. The fee function is evaluated, not inverted approximately."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money, money_down
from app.domains.vehicles.landed import LandedCost
from app.domains.vehicles.policy import MIN_DOWNSIDE_PROFIT_EUR, REQUIRED_ABSOLUTE_PROFIT_EUR, REQUIRED_ROI


@dataclass(frozen=True, slots=True)
class BidEconomics:
    max_safe_hammer_eur: Decimal | None
    expected_profit_eur: Decimal | None
    downside_profit_eur: Decimal | None
    roi: Decimal | None
    selling_cost_eur: Decimal
    blocked: bool
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "max_safe_hammer_eur": _s(self.max_safe_hammer_eur),
            "expected_profit_eur": _s(self.expected_profit_eur),
            "downside_profit_eur": _s(self.downside_profit_eur),
            "roi": str(self.roi) if self.roi is not None else None,
            "selling_cost_eur": str(self.selling_cost_eur),
            "blocked": self.blocked,
            "note": self.note,
        }


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def profit_at(
    *,
    resale_eur: Decimal,
    selling_cost_eur: Decimal,
    all_in_eur: Decimal,
) -> Decimal:
    return money(resale_eur - selling_cost_eur - all_in_eur)


def roi_at(*, profit_eur: Decimal, all_in_eur: Decimal) -> Decimal | None:
    if all_in_eur <= ZERO:
        return None
    return (profit_eur / all_in_eur).quantize(Decimal("0.0001"))


def _feasible(
    landed: LandedCost,
    *,
    conservative_eur: Decimal,
    quick_sale_eur: Decimal,
    selling_cost_eur: Decimal,
    required_profit: Decimal,
    required_roi: Decimal,
    min_downside: Decimal,
) -> bool:
    if landed.blocked or landed.expected_all_in_eur is None or landed.downside_all_in_eur is None:
        return False
    expected = profit_at(
        resale_eur=conservative_eur,
        selling_cost_eur=selling_cost_eur,
        all_in_eur=landed.expected_all_in_eur,
    )
    downside = profit_at(
        resale_eur=quick_sale_eur,
        selling_cost_eur=selling_cost_eur,
        all_in_eur=landed.downside_all_in_eur,
    )
    if expected < required_profit or downside < min_downside:
        return False
    roi = roi_at(profit_eur=expected, all_in_eur=landed.expected_all_in_eur)
    return roi is not None and roi >= required_roi


def solve_max_hammer(
    *,
    conservative_eur: Decimal | None,
    quick_sale_eur: Decimal | None,
    selling_cost_eur: Decimal,
    landed_at,
    required_profit: Decimal = REQUIRED_ABSOLUTE_PROFIT_EUR,
    required_roi: Decimal = REQUIRED_ROI,
    min_downside: Decimal = MIN_DOWNSIDE_PROFIT_EUR,
) -> BidEconomics:
    if conservative_eur is None or quick_sale_eur is None:
        return BidEconomics(None, None, None, None, selling_cost_eur, True, "No conservative resale value.")
    probe = landed_at(ZERO)
    if probe.blocked:
        return BidEconomics(None, None, None, None, selling_cost_eur, True, "Cost stack is incomplete, so no maximum bid is published.")
    kwargs = {
        "conservative_eur": conservative_eur,
        "quick_sale_eur": quick_sale_eur,
        "selling_cost_eur": selling_cost_eur,
        "required_profit": required_profit,
        "required_roi": required_roi,
        "min_downside": min_downside,
    }
    if not _feasible(probe, **kwargs):
        return BidEconomics(ZERO, None, None, None, selling_cost_eur, False, "Even a zero hammer misses the return or downside test.")

    high_cents = int((conservative_eur * 100).to_integral_value())
    low = 0
    best = 0
    while low <= high_cents:
        mid = (low + high_cents) // 2
        landed = landed_at(Decimal(mid) / Decimal("100"))
        if _feasible(landed, **kwargs):
            best = mid
            low = mid + 1
        else:
            high_cents = mid - 1
    hammer = money_down(Decimal(best) / Decimal("100"))
    landed = landed_at(hammer)
    while hammer > ZERO and not _feasible(landed, **kwargs):
        hammer = money_down(hammer - Decimal("0.01"))
        landed = landed_at(hammer)
    if not _feasible(landed, **kwargs) or landed.expected_all_in_eur is None or landed.downside_all_in_eur is None:
        return BidEconomics(ZERO, None, None, None, selling_cost_eur, False, "No positive hammer survived cent rounding.")
    expected = profit_at(
        resale_eur=conservative_eur,
        selling_cost_eur=selling_cost_eur,
        all_in_eur=landed.expected_all_in_eur,
    )
    downside = profit_at(
        resale_eur=quick_sale_eur,
        selling_cost_eur=selling_cost_eur,
        all_in_eur=landed.downside_all_in_eur,
    )
    roi = roi_at(profit_eur=expected, all_in_eur=landed.expected_all_in_eur)
    return BidEconomics(
        hammer,
        expected,
        downside,
        roi,
        selling_cost_eur,
        False,
        "Maximum hammer is the highest cent that keeps conservative profit, ROI, and downside inside policy.",
    )
