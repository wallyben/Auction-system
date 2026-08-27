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
    kind: str = "UNKNOWN"


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
            ZERO, None, None, None, ZERO, Decimal("0.15"), Decimal("0.80"),
            "No evidence. Days-to-sale unknown.",
            kind="UNKNOWN",
        )
    if realised_count == 0:
        prior = Decimal("0.25")
        if category in fast:
            prior += Decimal("0.05")
        return LiquidityResult(
            score=prior,
            expected_days_to_sale=None,
            expected_days_to_sale_low=None,
            expected_days_to_sale_high=None,
            liquidity_confidence=Decimal("0.20"),
            quick_sale_discount=Decimal("0.15"),
            slow_sale_risk=money_risk(prior),
            notes="MARKET_PRIOR only. Asking density is not sell-through. Days-to-sale not measured.",
            kind="MARKET_PRIOR",
        )
    days = 45
    low, high = 21, 70
    if score >= Decimal("0.70"):
        days, low, high = 14, 7, 23
    elif score >= Decimal("0.50"):
        days, low, high = 28, 14, 45
    conf = min(score, Decimal("0.75"))
    kind = "MEASURED_LIQUIDITY" if realised_count >= 3 else "MARKET_PRIOR"
    return LiquidityResult(
        score=score,
        expected_days_to_sale=days if kind == "MEASURED_LIQUIDITY" else None,
        expected_days_to_sale_low=low if kind == "MEASURED_LIQUIDITY" else None,
        expected_days_to_sale_high=high if kind == "MEASURED_LIQUIDITY" else None,
        liquidity_confidence=conf if kind == "MEASURED_LIQUIDITY" else min(conf, Decimal("0.35")),
        quick_sale_discount=Decimal("0.12"),
        slow_sale_risk=money_risk(score),
        notes=(
            "MEASURED_LIQUIDITY from realised transaction density."
            if kind == "MEASURED_LIQUIDITY"
            else "Fewer than 3 realised comps: days-to-sale is a prior, not a measurement."
        ),
        kind=kind,
    )


def money_risk(score: Decimal) -> Decimal:
    return (Decimal("1") - score).quantize(Decimal("0.01"))
