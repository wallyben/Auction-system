"""Certification levels. Do not call LEVEL 5 without evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.core.config import settings
from app.models.enums import CategoryCert, CertificationLevel

CATEGORY_DEFAULTS = {
    "cameras": CategoryCert.NOT_CERTIFIED,
    "lenses": CategoryCert.NOT_CERTIFIED,
    "apple": CategoryCert.NOT_CERTIFIED,
    "computing": CategoryCert.NOT_CERTIFIED,
    "gaming": CategoryCert.NOT_CERTIFIED,
    "gpu": CategoryCert.NOT_CERTIFIED,
    "music_dj": CategoryCert.NOT_CERTIFIED,
    "pro_av": CategoryCert.NOT_CERTIFIED,
    "trading_cards": CategoryCert.NOT_CERTIFIED,
    "collectibles": CategoryCert.NOT_CERTIFIED,
    "tools": CategoryCert.NOT_CERTIFIED,
    "consumer_electronics": CategoryCert.NOT_CERTIFIED,
}

EXIT_DEFAULTS = {
    "ebay_ie": CategoryCert.NOT_CERTIFIED,
    "ebay_gb": CategoryCert.NOT_CERTIFIED,
    "local_ie": CategoryCert.NOT_CERTIFIED,
    "cardmarket": CategoryCert.NOT_CERTIFIED,
    "reverb": CategoryCert.NOT_CERTIFIED,
    "cex_trade_in": CategoryCert.NOT_CERTIFIED,
    "dealer": CategoryCert.NOT_CERTIFIED,
}


@dataclass(slots=True)
class CategoryMetrics:
    category: str
    listings: int
    false_positive_rate: Decimal
    identity_exact_or_variant_rate: Decimal
    condition_reliable_rate: Decimal
    realised_comp_coverage: Decimal
    valuation_error_ok: bool
    exit_channel_credible: bool
    risk_controls_pass: bool


@dataclass(slots=True)
class CertificationVerdict:
    category: str
    certified: bool
    reasons: list[str]
    metrics: CategoryMetrics


def evaluate_category_certification(metrics: CategoryMetrics) -> CertificationVerdict:
    """Certify only when FP, identity, condition, realised coverage, and exit all pass.

    This never writes CERTIFIED into CATEGORY_DEFAULTS. Owner config
    `certified_categories` is the only runtime override, and it should stay empty
    until this evaluator returns certified=True with evidence.
    """
    reasons: list[str] = []
    if metrics.listings < 20:
        reasons.append("too_few_listings")
    if metrics.false_positive_rate >= Decimal("0.05"):
        reasons.append(f"fp_rate {metrics.false_positive_rate} >= 0.05")
    if metrics.identity_exact_or_variant_rate < Decimal("0.90"):
        reasons.append(f"identity {metrics.identity_exact_or_variant_rate} < 0.90")
    if metrics.condition_reliable_rate < Decimal("0.80"):
        reasons.append(f"condition {metrics.condition_reliable_rate} < 0.80")
    if metrics.realised_comp_coverage < Decimal("0.50"):
        reasons.append(f"realised_coverage {metrics.realised_comp_coverage} < 0.50")
    if not metrics.valuation_error_ok:
        reasons.append("valuation_error_not_acceptable")
    if not metrics.exit_channel_credible:
        reasons.append("exit_channel_not_credible")
    if not metrics.risk_controls_pass:
        reasons.append("risk_controls_failed")
    return CertificationVerdict(
        category=metrics.category,
        certified=not reasons,
        reasons=reasons or ["all_certification_bars_met"],
        metrics=metrics,
    )


def category_is_certified(category: str | None) -> bool:
    if not category:
        return False
    if category in settings.certified_category_list():
        return True
    return CATEGORY_DEFAULTS.get(category, CategoryCert.NOT_CERTIFIED) is CategoryCert.CERTIFIED


def exit_is_certified(channel: str | None) -> bool:
    if not channel:
        return False
    if channel in settings.certified_exit_list() and settings.owner_override_uncertified:
        return True
    return EXIT_DEFAULTS.get(channel, CategoryCert.NOT_CERTIFIED) is CategoryCert.CERTIFIED


def current_level(*, live_sources: int, owner_sales: int, paper_closed: int, real_purchases: int) -> CertificationLevel:
    if real_purchases >= 20 and paper_closed >= 30:
        return CertificationLevel.LEVEL_5_REAL_MONEY
    if real_purchases >= 3:
        return CertificationLevel.LEVEL_4_SMALL_MONEY
    if paper_closed >= 10:
        return CertificationLevel.LEVEL_3_PAPER_TRADE
    if owner_sales >= 15:
        return CertificationLevel.LEVEL_2_MARKET_VALIDATED
    if live_sources >= 1:
        return CertificationLevel.LEVEL_1_LIVE_DATA
    return CertificationLevel.LEVEL_0_ENGINEERING
