"""How unusual is the ask versus the market? Cheap is not automatically a buy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO, money


@dataclass(slots=True)
class Mispricing:
    discount_to_expected_sale: Decimal
    discount_to_quick_sale: Decimal
    price_percentile: Decimal | None
    mispricing_score: Decimal


def mispricing(
    *,
    ask: Decimal | None,
    expected: Decimal,
    quick: Decimal,
    p10: Decimal | None = None,
) -> Mispricing:
    if not ask or expected <= ZERO:
        return Mispricing(ZERO, ZERO, None, ZERO)
    disc_exp = money((expected - ask) / expected)
    disc_q = money((quick - ask) / quick) if quick else ZERO
    pct = None
    if p10 and ask <= p10:
        pct = Decimal("0.10")
    score = disc_exp
    if score < ZERO:
        score = ZERO
    if score > Decimal("1"):
        score = Decimal("1")
    return Mispricing(disc_exp, disc_q, pct, score)
