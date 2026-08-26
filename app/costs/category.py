"""Category-specific exit cost assumptions. Generic 3%/1% must not dominate."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.core.money import as_decimal


@dataclass(frozen=True, slots=True)
class CategoryCostPolicy:
    returns_allowance: Decimal
    warranty_allowance: Decimal
    repair_allowance_eur: Decimal
    notes: str


# Operator-verified bands for Irish eBay/local exit. Not invoices.
_POLICY: dict[str, CategoryCostPolicy] = {
    "cameras": CategoryCostPolicy(Decimal("0.04"), Decimal("0.025"), Decimal("35"), "Body: higher return + shutter/AF repair envelope."),
    "lenses": CategoryCostPolicy(Decimal("0.035"), Decimal("0.02"), Decimal("25"), "Glass: fungus/haze handled in condition, not here."),
    "computing": CategoryCostPolicy(Decimal("0.06"), Decimal("0.03"), Decimal("40"), "MacBook: battery/keyboard returns above generic."),
    "consumer_electronics": CategoryCostPolicy(Decimal("0.08"), Decimal("0.04"), Decimal("20"), "iPhone: high return rate; battery health still in condition."),
    "gpu": CategoryCostPolicy(Decimal("0.05"), Decimal("0.02"), Decimal("15"), "GPU: mining/hashrate disputes; no generic 3%."),
    "gaming": CategoryCostPolicy(Decimal("0.05"), Decimal("0.02"), Decimal("10"), "Console: HDMI/ban risk is condition, not fee."),
    "music_dj": CategoryCostPolicy(Decimal("0.04"), Decimal("0.02"), Decimal("30"), "DJ: bulky outbound already in shipping engine."),
    "pro_av": CategoryCostPolicy(Decimal("0.04"), Decimal("0.02"), Decimal("15"), "Mics: low weight, moderate returns."),
    "trading_cards": CategoryCostPolicy(Decimal("0.02"), Decimal("0.005"), Decimal("0"), "Cards: cheap tracked letter."),
}


def category_cost_policy(category: str | None) -> CategoryCostPolicy:
    if category and category in _POLICY:
        return _POLICY[category]
    return CategoryCostPolicy(
        as_decimal(settings.returns_allowance),
        as_decimal(settings.warranty_allowance),
        Decimal("0"),
        "Generic configured default. Prefer a certified category policy.",
    )
