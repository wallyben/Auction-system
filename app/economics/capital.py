"""Portfolio ranking under finite capital. Diversify unless owner configures otherwise."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.core.money import ZERO, as_decimal, money


@dataclass(slots=True)
class AllocationPick:
    opportunity_id: str
    capital: Decimal
    expected_profit: Decimal
    category: str


def allocate_capital(
    candidates: list[dict],
    *,
    available: Decimal | None = None,
) -> list[AllocationPick]:
    budget = available if available is not None else as_decimal(settings.available_capital_eur)
    max_pos = as_decimal(settings.max_position_percent) * budget
    max_cat = as_decimal(settings.max_category_exposure) * budget
    ranked = sorted(
        candidates,
        key=lambda row: (
            as_decimal(row.get("profit_per_30") or 0),
            as_decimal(row.get("expected_profit") or 0),
            as_decimal(row.get("downside") or 0),
        ),
        reverse=True,
    )
    picks: list[AllocationPick] = []
    used = ZERO
    by_cat: dict[str, Decimal] = {}
    for row in ranked:
        if not row.get("money_ready"):
            continue
        cap = as_decimal(row["capital"])
        cat = str(row.get("category") or "unknown")
        if cap <= ZERO or cap > max_pos:
            continue
        if used + cap > budget:
            continue
        if by_cat.get(cat, ZERO) + cap > max_cat:
            continue
        picks.append(
            AllocationPick(
                opportunity_id=str(row["id"]),
                capital=money(cap),
                expected_profit=as_decimal(row.get("expected_profit") or 0),
                category=cat,
            )
        )
        used += cap
        by_cat[cat] = by_cat.get(cat, ZERO) + cap
    return picks
