"""Liquidity scoring from evidence density, not invented precision."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.money import ZERO


@dataclass(slots=True)
class LiquidityResult:
    score: Decimal
    expected_days_to_sale: int | None
    expected_days_to_sale_low: int | None
    expected_days_to_sale_high: int | None
    liquidity_confidence: Decimal
    quick_sale_discount: Decimal
    slow_sale_risk: Decimal
    notes: str


def estimate_liquidity(
    *,
    comparable_count: int,
    realised_count: int,
    local_count: int,
    category: str | None,
    is_lot: bool,
) -> LiquidityResult:
    score = Decimal("0.20")
    score += min(Decimal("0.30"), Decimal(comparable_count) * Decimal("0.03"))
    score += min(Decimal("0.25"), Decimal(realised_count) * Decimal("0.05"))
    score += min(Decimal("0.20"), Decimal(local_count) * Decimal("0.04"))
    fast = {
        "trading_cards",
        "gaming",
        "consumer_electronics",
        "computing",
        "cameras",
        "music_dj",
    }
    if category in fast:
        score += Decimal("0.08")
    if is_lot:
        score -= Decimal("0.15")
    if score < ZERO:
        score = ZERO
    if score > Decimal("0.95"):
        score = Decimal("0.95")
    if comparable_count == 0:
        return LiquidityResult(
            ZERO, None, None, None, ZERO, Decimal("0.15"), Decimal("0.80"), "No evidence. Days-to-sale unknown."
        )
    days = 45
    low, high = 21, 70
    if score >= Decimal("0.70"):
        days, low, high = 14, 7, 23
    elif score >= Decimal("0.50"):
        days, low, high = 28, 14, 45
    if realised_count == 0:
        high = max(high, 60)
    conf = min(score, Decimal("0.40") if realised_count == 0 else score)
    return LiquidityResult(
        score=score,
        expected_days_to_sale=days,
        expected_days_to_sale_low=low,
        expected_days_to_sale_high=high,
        liquidity_confidence=conf,
        quick_sale_discount=Decimal("0.12"),
        slow_sale_risk=money_risk(score),
        notes="Days-to-sale is a band from evidence density, not a calendar promise.",
    )


def money_risk(score: Decimal) -> Decimal:
    return (Decimal("1") - score).quantize(Decimal("0.01"))
