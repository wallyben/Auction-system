"""Comparable-driven Irish expected resale."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.core.money import ZERO, money
from app.models.enums import EvidenceType
from app.valuation.irish import EVIDENCE_WEIGHT, TERRITORY_WEIGHT, irish_net_proceeds
from app.valuation.stats import display_money, percentile, recency_weight, reject_outliers, weighted_median
from app.valuation.tiers import STRONG_TIERS, classify_tier


@dataclass(slots=True)
class Comp:
    source: str
    url: str | None
    title: str
    price_eur: Decimal
    evidence_type: EvidenceType
    country: str
    condition_score: Decimal
    product_score: Decimal
    observed_at: datetime
    outlier: bool = False
    notes: str = ""
    evidence_tier: str = ""


@dataclass(slots=True)
class ValuationResult:
    expected_sale_eur: Decimal
    quick_sale_eur: Decimal
    high_eur: Decimal
    low_eur: Decimal
    confidence: Decimal
    method: str
    comparable_count: int
    realised_count: int
    local_count: int
    foreign_count: int
    expected_days: int | None
    provenance: dict = field(default_factory=dict)
    net_proceeds_eur: Decimal = ZERO
    p10: Decimal = ZERO
    p25: Decimal = ZERO
    median: Decimal = ZERO
    p75: Decimal = ZERO
    p90: Decimal = ZERO
    asking_count: int = 0
    display_expected: Decimal = ZERO
    display_low: Decimal = ZERO
    display_high: Decimal = ZERO


def _weight(comp: Comp, now: datetime) -> Decimal:
    age = max(0, (now - comp.observed_at).days)
    geo = TERRITORY_WEIGHT.get(comp.country.upper(), Decimal("0.25"))
    return (
        EVIDENCE_WEIGHT[comp.evidence_type]
        * recency_weight(age)
        * geo
        * comp.product_score
        * comp.condition_score
    )


def value_from_comps(comps: list[Comp], *, now: datetime | None = None) -> ValuationResult:
    now = now or datetime.now(timezone.utc)
    if not comps:
        return ValuationResult(
            expected_sale_eur=ZERO,
            quick_sale_eur=ZERO,
            high_eur=ZERO,
            low_eur=ZERO,
            confidence=ZERO,
            method="insufficient_evidence",
            comparable_count=0,
            realised_count=0,
            local_count=0,
            foreign_count=0,
            expected_days=None,
            provenance={"reason": "No comparables. Fail closed."},
        )
    for comp in comps:
        if not comp.evidence_tier:
            comp.evidence_tier = classify_tier(
                comp.evidence_type,
                exact_sku=comp.product_score >= Decimal("0.85"),
                locality_ok=comp.country.upper() == "IE",
            )
    strong = [c for c in comps if c.evidence_tier in STRONG_TIERS]
    candidate = strong if strong else comps
    prices = [c.price_eur for c in candidate]
    kept_prices, rejected = reject_outliers(prices)
    rejected_set = set(rejected)
    usable = [c for c in candidate if c.price_eur not in rejected_set]
    for comp in comps:
        comp.outlier = comp.price_eur in rejected_set and comp in candidate
    if not usable:
        usable = candidate
    # Strong realised/hammer evidence wins. A pile of asking prices cannot average it away.
    priced = usable
    pairs = [(c.price_eur, _weight(c, now)) for c in priced]
    expected = weighted_median(pairs)
    ordered = sorted(c.price_eur for c in priced)
    low = ordered[0]
    high = ordered[-1]
    quick = money(expected * Decimal("0.88"))
    realised = sum(1 for c in usable if c.evidence_type in {EvidenceType.REALISED_SALE, EvidenceType.AUCTION_HAMMER, EvidenceType.OWNER_RECORDED})
    local = sum(1 for c in usable if c.country.upper() == "IE")
    foreign = len(usable) - local
    confidence = Decimal("0.15")
    confidence += min(Decimal("0.25"), Decimal(realised) * Decimal("0.06"))
    confidence += min(Decimal("0.20"), Decimal(local) * Decimal("0.05"))
    confidence += min(Decimal("0.20"), Decimal(len(usable)) * Decimal("0.02"))
    asking_only = realised == 0
    if asking_only:
        expected = money(expected * Decimal("0.90"))
        quick = money(expected * Decimal("0.88"))
        confidence = min(confidence, Decimal("0.48"))
        method = "asking_distribution_localised"
    elif local and realised:
        method = "irish_realised_plus_support"
        confidence += Decimal("0.15")
    else:
        method = "foreign_realised_localised"
        confidence = min(confidence, Decimal("0.62"))
    if confidence > Decimal("0.95"):
        confidence = Decimal("0.95")
    p10 = percentile(ordered, Decimal("0.10"))
    p25 = percentile(ordered, Decimal("0.25"))
    p50 = percentile(ordered, Decimal("0.50"))
    p75 = percentile(ordered, Decimal("0.75"))
    p90 = percentile(ordered, Decimal("0.90"))
    asking_count = sum(1 for c in usable if c.evidence_type in {EvidenceType.CURRENT_ASKING, EvidenceType.DEALER_RETAIL})
    provenance = {
        "comps": [
            {
                "source": c.source,
                "url": c.url,
                "price_eur": str(c.price_eur),
                "type": c.evidence_type.value,
                "country": c.country,
                "outlier": c.outlier,
                "weight": str(_weight(c, now)),
                "tier": c.evidence_tier,
            }
            for c in comps
        ],
        "rejected_outliers": [str(value) for value in rejected],
        "method": method,
        "strong_tier_count": len(strong),
        "priced_from": "strong_realised" if strong else "weak_or_asking",
        "warning": "Asking prices are not realised Irish sales." if asking_only else "",
        "percentiles": {"p10": str(p10), "p25": str(p25), "median": str(p50), "p75": str(p75), "p90": str(p90)},
        "display": {
            "expected": str(display_money(expected, confidence=confidence)),
            "range": f"{display_money(low, confidence=confidence)}–{display_money(high, confidence=confidence)}",
        },
    }
    return ValuationResult(
        expected_sale_eur=expected,
        quick_sale_eur=quick,
        high_eur=high,
        low_eur=low,
        confidence=confidence,
        method=method,
        comparable_count=len(usable),
        realised_count=realised,
        local_count=local,
        foreign_count=foreign,
        expected_days=21 if local else 35,
        provenance=provenance,
        net_proceeds_eur=irish_net_proceeds(expected),
        p10=p10,
        p25=p25,
        median=p50,
        p75=p75,
        p90=p90,
        asking_count=asking_count,
        display_expected=display_money(expected, confidence=confidence),
        display_low=display_money(low, confidence=confidence),
        display_high=display_money(high, confidence=confidence),
    )
