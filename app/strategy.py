"""Named acquisition strategies. Threshold overrides only — no category hard-coding."""

from __future__ import annotations

from decimal import Decimal

from app.core.config import settings
from app.core.money import as_decimal

PROFILES: dict[str, dict[str, Decimal]] = {
    "balanced": {},
    "fast_flip": {
        "min_profit_eur": Decimal("25"),
        "min_roi": Decimal("0.12"),
        "min_confidence": Decimal("0.50"),
        "max_days_to_sale": Decimal("21"),
    },
    "high_margin": {
        "min_profit_eur": Decimal("80"),
        "min_roi": Decimal("0.30"),
        "min_confidence": Decimal("0.60"),
    },
    "low_risk": {
        "min_confidence": Decimal("0.70"),
        "min_roi": Decimal("0.18"),
    },
    "repair": {
        "min_profit_eur": Decimal("60"),
        "min_roi": Decimal("0.25"),
        "min_confidence": Decimal("0.45"),
    },
    "job_lot": {
        "min_profit_eur": Decimal("100"),
        "min_roi": Decimal("0.20"),
        "min_confidence": Decimal("0.40"),
    },
    "ireland_arb": {
        "min_profit_eur": Decimal("50"),
        "min_roi": Decimal("0.22"),
        "min_confidence": Decimal("0.55"),
    },
    "clearance": {
        "min_profit_eur": Decimal("30"),
        "min_roi": Decimal("0.15"),
        "min_confidence": Decimal("0.50"),
    },
}


def thresholds() -> dict[str, Decimal]:
    """Merge owner .env knobs with the selected strategy profile."""
    base = {
        "min_profit_eur": as_decimal(settings.min_profit_eur),
        "min_roi": as_decimal(settings.min_roi),
        "min_confidence": as_decimal(settings.min_confidence),
        "max_capital_per_item_eur": as_decimal(settings.max_capital_per_item_eur),
        "max_days_to_sale": Decimal(str(settings.max_days_to_sale)),
        "target_margin_percent": as_decimal(settings.target_margin_percent),
        "risk_percent": as_decimal(settings.risk_percent),
    }
    profile = PROFILES.get(settings.strategy_profile, {})
    base.update(profile)
    return base


thresholds = thresholds
