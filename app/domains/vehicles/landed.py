"""Auditable all-in acquisition cost. No line is silently omitted."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money
from app.domains.vehicles.auction_costs import AuctionCostResult
from app.domains.vehicles.enums import EvidencePosture
from app.domains.vehicles.evidence import MoneyLine
from app.domains.vehicles.reconditioning import ReconditioningResult
from app.domains.vehicles.tax import TaxPosition


@dataclass(frozen=True, slots=True)
class LandedCost:
    expected_all_in_eur: Decimal | None
    downside_all_in_eur: Decimal | None
    blocked: bool
    lines: tuple[MoneyLine, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "expected_all_in_eur": str(self.expected_all_in_eur) if self.expected_all_in_eur is not None else None,
            "downside_all_in_eur": str(self.downside_all_in_eur) if self.downside_all_in_eur is not None else None,
            "blocked": self.blocked,
            "lines": [line.to_dict() for line in self.lines],
        }


def _sum_known(lines: list[MoneyLine]) -> Decimal | None:
    total = ZERO
    for line in lines:
        if line.amount_eur is None or line.posture is EvidencePosture.UNKNOWN:
            return None
        total += line.amount_eur
    return money(total)


def stack_landed_cost(
    *,
    auction: AuctionCostResult,
    tax: TaxPosition,
    transport_eur: Decimal | None,
    transport_posture: EvidencePosture,
    repairs: ReconditioningResult,
) -> LandedCost:
    """Expected stack uses expected repairs. Downside stack swaps in the downside reserve."""

    shared: list[MoneyLine] = [
        line
        for line in auction.lines
        if line.name != "auction_lot_vat_cash"
    ]
    shared.append(MoneyLine("transport", transport_eur, transport_posture, "logistics", "Collection and delivery."))
    for line in tax.lines:
        shared.append(line)

    expected_lines = list(shared)
    expected_lines.append(
        MoneyLine("reconditioning", repairs.expected_eur, repairs.posture, "reconditioning", "Expected reserve")
    )
    downside_lines = list(shared)
    downside_lines.append(
        MoneyLine("reconditioning", repairs.downside_eur, repairs.posture, "reconditioning", "Downside reserve")
    )
    expected = _sum_known(expected_lines)
    downside = _sum_known(downside_lines)
    blocked = auction.blocked or tax.blocked or expected is None or downside is None
    return LandedCost(
        expected_all_in_eur=expected,
        downside_all_in_eur=downside,
        blocked=blocked,
        lines=tuple(expected_lines),
    )
