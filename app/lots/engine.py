"""Job-lot splitting. Conservative: residue and labour are first-class costs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money
from app.identity.engine import identify_listing


@dataclass(slots=True)
class LotItem:
    text: str
    brand: str | None
    model: str | None
    quantity: int
    sellable: bool


@dataclass(slots=True)
class LotBreakdown:
    items: list[LotItem]
    is_lot: bool
    labour_hours: Decimal
    residue_ratio: Decimal


SPLIT_RE = re.compile(r"(?:^|\n)\s*(?:[-*]|\d+[.)])\s+(.+)")


def split_lot(title: str, description: str) -> LotBreakdown:
    identity = identify_listing(title=title, description=description)
    chunks = SPLIT_RE.findall(description or "")
    if not chunks and identity.is_lot:
        chunks = [part.strip() for part in re.split(r"[;,/]| and ", title) if part.strip()]
    items: list[LotItem] = []
    for chunk in chunks[:40]:
        ident = identify_listing(title=chunk)
        items.append(
            LotItem(
                text=chunk[:300],
                brand=ident.brand,
                model=ident.model,
                quantity=1,
                sellable=ident.level.value not in {"unknown"},
            )
        )
    if not items:
        items = [
            LotItem(
                text=title,
                brand=identity.brand,
                model=identity.model,
                quantity=1,
                sellable=not identity.is_lot,
            )
        ]
    n = max(1, len(items))
    labour = Decimal(str(n)) * Decimal("0.4")
    residue = Decimal("0.20") if identity.is_lot else Decimal("0.02")
    return LotBreakdown(items=items, is_lot=identity.is_lot, labour_hours=labour, residue_ratio=residue)


def lot_liquidation(
    *,
    purchase: Decimal,
    item_values: list[Decimal],
    selling_cost_rate: Decimal,
    labour_eur: Decimal,
) -> dict[str, Decimal]:
    gross = sum(item_values, ZERO)
    expected = money(gross * (Decimal("1") - Decimal("0.20")))
    quick = money(gross * Decimal("0.55"))
    selling = money(expected * selling_cost_rate)
    profit = money(expected - selling - labour_eur - purchase)
    return {
        "lot_purchase_price": money(purchase),
        "gross_breakup_value": money(gross),
        "expected_realised_breakup_value": expected,
        "quick_liquidation_value": quick,
        "estimated_selling_costs": selling,
        "labour": money(labour_eur),
        "expected_profit": profit,
        "max_safe_bid": money(max(ZERO, expected - selling - labour_eur - money(expected * Decimal("0.15")))),
    }
