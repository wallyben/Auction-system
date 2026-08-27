"""Comparable-driven Irish expected resale. Asking is never a realised Irish sale."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from app.core.money import ZERO, money
from app.evidence.classes import evidence_class_for
from app.models.enums import EvidenceType
from app.valuation.irish import EVIDENCE_WEIGHT, TERRITORY_WEIGHT, irish_net_proceeds
from app.valuation.stats import display_money, percentile, recency_weight, reject_outliers, weighted_median
from app.valuation.tiers import STRONG_TIERS, classify_tier
from app.valuation.version import VALUATION_ALGORITHM_VERSION

BINDING_TYPES = {EvidenceType.REALISED_SALE, EvidenceType.AUCTION_HAMMER, EvidenceType.OWNER_RECORDED, EvidenceType.TRADE_IN}
REALISED_TYPES = {EvidenceType.REALISED_SALE, EvidenceType.AUCTION_HAMMER, EvidenceType.OWNER_RECORDED}
GUIDE_TYPES = {EvidenceType.DEALER_RETAIL, EvidenceType.ESTIMATE}


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
    evidence_class: str = ""


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
    sample_size: int = 0
    median_market_value: Decimal = ZERO
    quick_sale_value: Decimal = ZERO
    expected_sale_value: Decimal = ZERO
    optimistic_sale_value: Decimal = ZERO
    realised_comp_count: int = 0
    local_comp_count: int = 0
    evidence_age_days: int | None = None
    local_market_method: str = "INSUFFICIENT"
    local_sample_n: int = 0
    foreign_sample_n: int = 0
    localisation_confidence: Decimal = ZERO
    value_status: str = "UNVALIDATED_VALUE"
    algorithm_version: str = VALUATION_ALGORITHM_VERSION
    asking_implied_eur: Decimal = ZERO
    binding_count: int = 0
    uk_comp_count: int = 0
    eu_comp_count: int = 0
    valuation_anomaly: bool = False
    valuation_anomaly_reason: str = ""


def _weight(comp: Comp, now: datetime) -> Decimal:
    age = max(0, (now - comp.observed_at).days)
    geo = TERRITORY_WEIGHT.get(comp.country.upper(), Decimal("0.25"))
    klass = comp.evidence_class or evidence_class_for(comp.evidence_type, source=comp.source).value
    class_w = {
        "A": Decimal("1.00"),
        "B": Decimal("0.90"),
        "C": Decimal("0.85"),
        "D": Decimal("0.70"),
        "E": Decimal("0.40"),
        "F": Decimal("0.20"),
        "G": Decimal("0.30"),
    }.get(klass, Decimal("0.20"))
    return (
        EVIDENCE_WEIGHT[comp.evidence_type]
        * recency_weight(age)
        * geo
        * comp.product_score
        * comp.condition_score
        * class_w
    )


def _empty(reason: str) -> ValuationResult:
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
        provenance={"reason": reason, "algorithm_version": VALUATION_ALGORITHM_VERSION},
        sample_size=0,
        local_market_method="INSUFFICIENT",
        value_status="UNVALIDATED_VALUE",
        algorithm_version=VALUATION_ALGORITHM_VERSION,
    )


def value_from_comps(comps: list[Comp], *, now: datetime | None = None) -> ValuationResult:
    now = now or datetime.now(timezone.utc)
    if not comps:
        return _empty("No comparables. Fail closed.")
    for comp in comps:
        if not comp.evidence_class:
            comp.evidence_class = evidence_class_for(comp.evidence_type, source=comp.source).value
        if not comp.evidence_tier:
            comp.evidence_tier = classify_tier(
                comp.evidence_type,
                exact_sku=comp.product_score >= Decimal("0.85"),
                locality_ok=comp.country.upper() == "IE",
            )
    strong = [c for c in comps if c.evidence_tier in STRONG_TIERS]
    binding = [c for c in comps if c.evidence_type in BINDING_TYPES or c.evidence_class in {"A", "B", "C", "D"}]
    guides = [c for c in comps if c.evidence_type in GUIDE_TYPES or c.evidence_class in {"E", "G"}]
    asking = [c for c in comps if c.evidence_type is EvidenceType.CURRENT_ASKING or c.evidence_class == "F"]
    candidate = strong if strong else (binding if binding else (guides if guides else asking))
    prices = [c.price_eur for c in candidate]
    kept_prices, rejected = reject_outliers(prices)
    rejected_set = set(rejected)
    usable = [c for c in candidate if c.price_eur not in rejected_set]
    for comp in comps:
        comp.outlier = comp.price_eur in rejected_set and comp in candidate
    if not usable:
        usable = candidate
    priced = usable
    pairs = [(c.price_eur, _weight(c, now)) for c in priced if _weight(c, now) > ZERO]
    if not pairs:
        return _empty("Comparables had zero weight after identity/geography haircut.")
    expected = weighted_median(pairs)
    ordered = sorted(c.price_eur for c in priced)
    low = ordered[0]
    high = ordered[-1]
    p10 = percentile(ordered, Decimal("0.10"))
    p25 = percentile(ordered, Decimal("0.25"))
    p50 = percentile(ordered, Decimal("0.50"))
    p75 = percentile(ordered, Decimal("0.75"))
    p90 = percentile(ordered, Decimal("0.90"))
    realised = sum(1 for c in comps if c.evidence_type in REALISED_TYPES)
    binding_n = sum(1 for c in comps if c.evidence_type in BINDING_TYPES)
    local = sum(1 for c in usable if c.country.upper() == "IE")
    foreign = len(usable) - local
    local_realised = sum(1 for c in comps if c.evidence_type in REALISED_TYPES and c.country.upper() == "IE")
    foreign_realised = realised - local_realised
    uk_comps = [c for c in usable if c.evidence_type in REALISED_TYPES and c.country.upper() in {"GB", "UK"}]
    eu_comps = [
        c
        for c in usable
        if c.evidence_type in REALISED_TYPES and c.country.upper() in {"DE", "FR", "IT", "ES", "NL", "BE", "AT"}
    ]
    uk_comp_count = len(uk_comps)
    eu_comp_count = len(eu_comps)
    asking_count = sum(1 for c in comps if c.evidence_type is EvidenceType.CURRENT_ASKING)
    asking_implied = ZERO
    if asking:
        ask_pairs = [(c.price_eur, _weight(c, now)) for c in asking if _weight(c, now) > ZERO]
        if ask_pairs:
            asking_implied = weighted_median(ask_pairs)

    ages = [(now - c.observed_at).days for c in priced if c.observed_at]
    evidence_age = int(sorted(ages)[len(ages) // 2]) if ages else None

    confidence = Decimal("0.15")
    confidence += min(Decimal("0.25"), Decimal(realised) * Decimal("0.06"))
    confidence += min(Decimal("0.20"), Decimal(local_realised) * Decimal("0.05"))
    confidence += min(Decimal("0.20"), Decimal(len(usable)) * Decimal("0.02"))

    value_status = "UNVALIDATED_VALUE"
    localisation_confidence = ZERO
    if local_realised:
        local_market_method = "IE_REALISED"
        localisation_confidence = min(Decimal("0.90"), Decimal("0.40") + Decimal(local_realised) * Decimal("0.10"))
        method = "irish_realised_plus_support"
        confidence += Decimal("0.15")
        value_status = "VALIDATED_VALUE"
        quick = p25 if len(ordered) >= 3 else money(expected * Decimal("0.88"))
        optimistic = p75 if len(ordered) >= 3 else high
    elif uk_comp_count:
        local_market_method = "UK_REALIZED_PROXY"
        recency_bonus = Decimal("0.08") if (evidence_age is not None and evidence_age <= 21) else Decimal("0")
        localisation_confidence = min(
            Decimal("0.78"),
            Decimal("0.32") + Decimal(uk_comp_count) * Decimal("0.04") + recency_bonus,
        )
        method = "uk_realized_proxy"
        confidence += min(Decimal("0.40"), Decimal(uk_comp_count) * Decimal("0.045"))
        if evidence_age is not None and evidence_age > 45:
            confidence = min(confidence, Decimal("0.72"))
        confidence = min(confidence, Decimal("0.85"))
        value_status = "VALIDATED_VALUE"
        quick = p25 if len(ordered) >= 3 else money(expected * Decimal("0.88"))
        optimistic = p75 if len(ordered) >= 3 else high
    elif realised:
        local_market_method = "EU_REALIZED_PROXY" if eu_comp_count else "GB_EU_REALISED_HAIRCUT"
        localisation_confidence = min(Decimal("0.50"), Decimal("0.18") + Decimal(foreign_realised) * Decimal("0.04"))
        method = "foreign_realised_localised"
        confidence = min(confidence, Decimal("0.70"))
        value_status = "VALIDATED_VALUE"
        quick = p25 if len(ordered) >= 3 else money(expected * Decimal("0.88"))
        optimistic = p75 if len(ordered) >= 3 else high
    elif guides and not strong:
        local_market_method = "GUIDE_ONLY"
        localisation_confidence = Decimal("0.15")
        method = "guide_reference_unvalidated"
        confidence = min(confidence, Decimal("0.40"))
        value_status = "UNVALIDATED_VALUE"
        # Guide may be displayed but is not an Irish realised resale forecast.
        expected = ZERO
        quick = ZERO
        optimistic = ZERO
    else:
        local_market_method = "ASKING_ONLY"
        localisation_confidence = ZERO
        method = "asking_only_unvalidated"
        confidence = min(confidence, Decimal("0.35"))
        value_status = "UNVALIDATED_VALUE"
        expected = ZERO
        quick = ZERO
        optimistic = ZERO

    if len(usable) < 3 and value_status == "VALIDATED_VALUE":
        confidence = min(confidence, Decimal("0.58"))
    if confidence > Decimal("0.95"):
        confidence = Decimal("0.95")

    provenance = {
        "comps": [
            {
                "source": c.source,
                "url": c.url,
                "title": c.title,
                "price_eur": str(c.price_eur),
                "type": c.evidence_type.value,
                "evidence_class": c.evidence_class,
                "country": c.country,
                "outlier": c.outlier,
                "weight": str(_weight(c, now)),
                "tier": c.evidence_tier,
                "notes": c.notes,
            }
            for c in comps
        ],
        "rejected_outliers": [str(value) for value in rejected],
        "method": method,
        "strong_tier_count": len(strong),
        "priced_from": "strong_realised" if strong else ("guide" if guides and not binding else "asking_unvalidated"),
        "warning": (
            "Asking prices are not realised Irish sales. Expected resale is not priced from asks."
            if value_status == "UNVALIDATED_VALUE"
            else ""
        ),
            "localisation": {
            "method": local_market_method,
            "local_sample_n": local_realised,
            "foreign_sample_n": foreign_realised,
            "uk_comp_count": uk_comp_count,
            "eu_comp_count": eu_comp_count,
            "localisation_confidence": str(localisation_confidence),
            "note": (
                "Irish realised used at full weight. No Ireland premium invented."
                if local_realised
                else "UK realised used as Ireland proxy. No Ireland premium invented."
                if uk_comp_count
                else "No Irish or UK realised sales. EU realised used with explicit lower confidence."
                if realised
                else "No realised evidence. Asking is not an Ireland expected resale."
            ),
        },
        "percentiles": {"p10": str(p10), "p25": str(p25), "median": str(p50), "p75": str(p75), "p90": str(p90)},
        "asking_implied_eur": str(asking_implied),
        "value_status": value_status,
        "algorithm_version": VALUATION_ALGORITHM_VERSION,
        "evidence_age_days": evidence_age,
        "display": {
            "expected": str(display_money(expected, confidence=confidence)),
            "range": f"{display_money(low, confidence=confidence)}–{display_money(high, confidence=confidence)}",
        },
    }
    return ValuationResult(
        expected_sale_eur=expected,
        quick_sale_eur=quick,
        high_eur=high if value_status == "VALIDATED_VALUE" else ZERO,
        low_eur=low if value_status == "VALIDATED_VALUE" else ZERO,
        confidence=confidence,
        method=method,
        comparable_count=len(usable),
        realised_count=realised,
        local_count=local_realised,
        foreign_count=foreign_realised,
        expected_days=21 if local_realised else (35 if realised else None),
        provenance=provenance,
        net_proceeds_eur=irish_net_proceeds(expected) if expected else ZERO,
        p10=p10,
        p25=p25,
        median=p50,
        p75=p75,
        p90=p90,
        asking_count=asking_count,
        display_expected=display_money(expected, confidence=confidence),
        display_low=display_money(low if expected else ZERO, confidence=confidence),
        display_high=display_money(high if expected else ZERO, confidence=confidence),
        sample_size=len(usable),
        median_market_value=p50 if value_status == "VALIDATED_VALUE" else ZERO,
        quick_sale_value=quick,
        expected_sale_value=expected,
        optimistic_sale_value=optimistic if value_status == "VALIDATED_VALUE" else ZERO,
        realised_comp_count=realised,
        local_comp_count=local_realised,
        evidence_age_days=evidence_age,
        local_market_method=local_market_method,
        local_sample_n=local_realised,
        foreign_sample_n=foreign_realised,
        localisation_confidence=localisation_confidence,
        value_status=value_status,
        algorithm_version=VALUATION_ALGORITHM_VERSION,
        asking_implied_eur=asking_implied,
        binding_count=binding_n,
        uk_comp_count=uk_comp_count,
        eu_comp_count=eu_comp_count,
    )
