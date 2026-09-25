"""Native valuation v2. Same-family anchors, then explicit adjustments.

Sibling platforms and the wider van book can estimate age and mileage.
They cannot set the price of a van that has no same-family anchor.
Asking prices are not sold prices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from app.core.money import money
from app.domains.vehicles.comps import (
    CompScore,
    _DAMAGE_TOKENS,
    _GOODS_BODIES,
    _NON_RUNNER_TOKENS,
    _PASSENGER_TOKENS,
    _PEOPLE_BODIES,
)
from app.domains.vehicles.effects import EffectModel, fit_effects
from app.domains.vehicles.enums import EvidencePosture, ObservationStatus
from app.domains.vehicles.identity import VehicleIdentity
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.platforms import sibling_families
from app.domains.vehicles.policy import (
    ASKING_ONLY_CONFIDENCE_CAP,
    ASKING_TO_ACHIEVABLE_DISCOUNT,
    LIQUIDITY_QUICK_SALE_HAIRCUT,
    MARKET_FRESH_DAYS,
)
from app.domains.vehicles.tax import VAT_RATE
from app.domains.vehicles.valuation import (
    ValuationResult,
    _drop_duplicate_registrations,
    _drop_same_dealer_van,
    _effective_sample_size,
    _latest_per_listing,
    _liquidity,
    _mad_pairs,
    _percentile,
    _vat_class,
    _weighted_median,
)

MODEL_VERSION = "arie-native-v2"
_ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class _Anchor:
    observation: MarketObservation
    tier: str
    weight: Decimal
    score: CompScore
    why: str


def value_vehicle_v2(subject: VehicleIdentity, book: MarketBook, *, as_of: datetime) -> ValuationResult:
    fresh_after = as_of - timedelta(days=MARKET_FRESH_DAYS)
    visible = book.as_of(as_of)
    fresh_rows = [row for row in visible if row.observed_at >= fresh_after]
    current = _latest_per_listing(fresh_rows)
    effects = fit_effects(fresh_rows, subject.model_family or "")
    anchors: list[_Anchor] = []
    tier_c: list[MarketObservation] = []
    rejected: list[CompScore] = []
    for row in current:
        anchor, tier_c_row, rejection = _classify(subject, row)
        if rejection is not None:
            rejected.append(rejection)
        elif tier_c_row is not None:
            tier_c.append(tier_c_row)
        elif anchor is not None:
            anchors.append(anchor)
    kept_scores = [item.score for item in anchors]
    kept_scores, registration_dupes = _drop_duplicate_registrations(kept_scores)
    kept_scores, dealer_dupes = _drop_same_dealer_van(kept_scores)
    rejected.extend(registration_dupes)
    rejected.extend(dealer_dupes)
    kept_ids = {item.observation_id for item in kept_scores}
    anchors = [item for item in anchors if item.score.observation_id in kept_ids]
    basis_name, priced = _basis_prices(anchors)
    priced_ids = {anchor.score.observation_id for _price, anchor in priced}
    adjusted_pairs: list[tuple[Decimal, Decimal, _Anchor, Decimal]] = []
    evidence: list[dict[str, object]] = []
    for price, anchor in priced:
        adjustment = apply_adjustment(subject, anchor.observation, effects, price)
        adjusted = money(price + adjustment)
        adjusted_pairs.append((adjusted, anchor.weight, anchor, adjustment))
        evidence.append(_evidence(anchor, price, adjusted, adjustment, effects))
    for anchor in anchors:
        if anchor.score.observation_id not in priced_ids:
            evidence.append(_unknown_vat_evidence(anchor))
    for row in tier_c[:12]:
        evidence.append(_tier_c_evidence(row))
    screened_input = [(price, weight) for price, weight, _anchor, _adjustment in adjusted_pairs]
    screened = _drop_cluster_outliers(screened_input) if screened_input else []
    screened_prices = {price for price, _weight in screened}
    outliers = [item for item in adjusted_pairs if item[0] not in screened_prices]
    for price, _weight, anchor, _adjustment in outliers:
        rejected.append(_reject(anchor.observation, 0, f"Extreme adjusted price €{price} left out of the median."))
    used = [item for item in adjusted_pairs if item[0] in screened_prices]
    prices = [price for price, _weight, _anchor, _adjustment in used]
    weights = [weight for _price, weight in screened]
    label, numeric = _confidence_label(anchors, used, basis_name, effects)
    mid = money(_weighted_median(prices, weights)) if prices and basis_name != "unknown" else None
    low = money(_percentile(prices, Decimal("0.20"))) if prices else None
    high = money(_percentile(prices, Decimal("0.80"))) if prices else None
    if basis_name == "unknown" and prices:
        low = money(_percentile(prices, Decimal("0.20")))
        high = money(max(prices) * (Decimal("1") + VAT_RATE))
        mid = None
    if label == "INSUFFICIENT":
        mid = None
        low = None
        high = None
    if mid is not None and low is not None and high is not None:
        low = min(low, mid)
        high = max(high, mid)
    issue = label in {"HIGH", "MEDIUM"} and mid is not None
    expected = money(mid * (Decimal("1") - ASKING_TO_ACHIEVABLE_DISCOUNT)) if issue and mid is not None else None
    conservative = money(mid * Decimal("0.80")) if issue and mid is not None else None
    tier_a = sum(1 for _price, _weight, anchor, _adjustment in used if anchor.tier == "A")
    active_supply = len({anchor.observation.listing_id for anchor in anchors})
    ages = [max(0, (as_of - row.observed_at).days) for row in fresh_rows]
    disappeared = sum(1 for row in rejected if any("Disappearance" in reason for reason in row.reasons))
    liquidity = _liquidity(
        active_supply=active_supply,
        eligible=len(used),
        close=tier_a,
        realised=0,
        ages=ages,
        reductions=0,
        disappeared=disappeared,
    )
    haircut = LIQUIDITY_QUICK_SALE_HAIRCUT[liquidity.classification.value]
    quick = money(conservative * (Decimal("1") - haircut)) if conservative is not None else None
    trade = money(_percentile([money(price * Decimal("0.85")) for price in prices], Decimal("0.10"))) if issue and prices else None
    known = sum(1 for anchor in anchors if _vat_class(anchor.observation.vat_presentation) != "unknown")
    share = _ZERO if not anchors else (Decimal(known) / Decimal(len(anchors))).quantize(Decimal("0.01"))
    sample = _effective_sample_size(weights) if weights else _ZERO
    notes = [
        f"Model {MODEL_VERSION}. Asking-to-achievable asking-haircut-v1 is an estimate, not a measured clearance rate.",
        "ASKING-TO-ACHIEVABLE ADJUSTMENT: 15% base. STATUS: UNCALIBRATED_ASSUMPTION.",
        "This estimates the current Irish asking market. It is not a verified realised-sale price.",
        f"Age/mileage basis: {effects.basis}. Sample {effects.sample_size}. Confidence {effects.confidence}.",
        f"Evidence label {label}. Tier A {tier_a}. Tier B {len(used) - tier_a}. Tier C {len(tier_c)}.",
    ]
    if basis_name == "unknown":
        notes.append("VAT basis is unknown, so the achievable value is withheld. The advertised interval remains visible.")
    if label in {"LOW", "INSUFFICIENT"}:
        notes.append("Evidence is not strong enough for an achievable resale figure.")
    sensitivity = _sensitivity(mid, effects) if mid is not None else None
    freshness = None
    if fresh_rows:
        newest = max(row.observed_at for row in fresh_rows)
        freshness = int((as_of - newest).total_seconds() // 3600)
    return ValuationResult(
        market_asking_eur=mid,
        expected_achievable_eur=expected,
        conservative_eur=conservative,
        quick_sale_eur=quick,
        asking_low_eur=low,
        asking_high_eur=high,
        confidence=numeric,
        confidence_posture=EvidencePosture.ESTIMATED if issue else EvidencePosture.UNKNOWN,
        comparable_count=len(used),
        close_count=tier_a,
        realised_count=0,
        freshness_hours=freshness,
        fresh=bool(fresh_rows) and bool(used),
        comps=tuple(anchor.score for _price, _weight, anchor, _adjustment in used),
        rejected=tuple(rejected),
        liquidity=liquidity,
        discount_applied=ASKING_TO_ACHIEVABLE_DISCOUNT,
        notes=tuple(notes),
        source_count=len({anchor.observation.source for _p, _w, anchor, _a in used}),
        adjustment_reasons=(f"year €{effects.year_eur}/year", f"mileage €{effects.km_eur}/km", f"basis {effects.basis}"),
        model_version=MODEL_VERSION,
        effective_sample_size=sample,
        vat_basis=basis_name if basis_name != "unknown" else "unknown",
        trade_downside_eur=trade,
        median_comp_age_days=liquidity.median_age_days,
        haircut_sensitivity={
            "0.10": str(money(mid * Decimal("0.90"))),
            "0.15": str(money(mid * Decimal("0.85"))),
            "0.20": str(money(mid * Decimal("0.80"))),
        }
        if mid is not None
        else None,
        confidence_label=label,
        tier_a_count=sum(1 for anchor in anchors if anchor.tier == "A"),
        tier_b_count=sum(1 for anchor in anchors if anchor.tier == "B"),
        tier_c_count=len(tier_c),
        known_vat_share=str(share),
        evidence=tuple(evidence),
        sensitivity=sensitivity,
        effect_basis=effects.basis,
    )


def _drop_cluster_outliers(pairs: list[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    """Drop a price that sits far outside a tight cluster, including when MAD is zero."""

    screened = _mad_pairs(pairs)
    if len(pairs) < 4:
        return screened
    prices = [price for price, _weight in pairs]
    centre = Decimal(str(median(prices)))
    deviations = sorted(abs(price - centre) for price in prices)
    mad = Decimal(str(median(deviations)))
    if mad != 0 or centre <= 0:
        return screened
    kept = [pair for pair in pairs if abs(pair[0] - centre) / centre <= Decimal("0.50")]
    return kept or screened


def _confidence_label(
    anchors: list[_Anchor],
    used: list[tuple[Decimal, Decimal, _Anchor, Decimal]],
    basis_name: str,
    effects: EffectModel,
) -> tuple[str, Decimal]:
    del effects
    if len(used) < 2 or basis_name == "unknown" and len(used) < 2:
        if len(used) < 2:
            return "INSUFFICIENT", Decimal("0.35")
    known = sum(1 for _p, _w, anchor, _a in used if _vat_class(anchor.observation.vat_presentation) != "unknown")
    share = Decimal(known) / Decimal(len(used)) if used else _ZERO
    weights = [weight for _price, weight, _anchor, _adjustment in used]
    sample = _effective_sample_size(weights) if weights else _ZERO
    tier_a = sum(1 for _p, _w, anchor, _a in used if anchor.tier == "A")
    prices = [price for price, _w, _a, _adj in used]
    mid = _weighted_median(prices, weights) if prices else None
    spread = _ZERO
    if mid and mid > 0 and len(prices) >= 2:
        spread = (_percentile(prices, Decimal("0.80")) - _percentile(prices, Decimal("0.20"))) / mid
    if (
        basis_name != "unknown"
        and tier_a >= 5
        and sample >= Decimal("8")
        and share >= Decimal("0.70")
        and spread <= Decimal("0.40")
        and len(used) >= 8
    ):
        return "HIGH", ASKING_ONLY_CONFIDENCE_CAP
    if basis_name != "unknown" and len(used) >= 5 and sample >= Decimal("3.5") and share >= Decimal("0.25") and tier_a >= 1:
        return "MEDIUM", Decimal("0.60")
    if len(anchors) >= 2 and len(used) >= 2:
        return "LOW", Decimal("0.48")
    return "INSUFFICIENT", Decimal("0.35")


def _basis_prices(anchors: list[_Anchor]) -> tuple[str, list[tuple[Decimal, _Anchor]]]:
    known = [anchor for anchor in anchors if _vat_class(anchor.observation.vat_presentation) != "unknown"]
    pool = known or anchors
    kinds = {_vat_class(anchor.observation.vat_presentation) for anchor in pool}
    priced: list[tuple[Decimal, _Anchor]] = []
    if not known:
        for anchor in anchors:
            price = anchor.observation.asking_price_eur
            if price is not None and price > 0:
                priced.append((price, anchor))
        return "unknown", priced
    if kinds == {"exclusive"}:
        basis = "ex_vat"
    elif kinds == {"inclusive"}:
        basis = "vat_inclusive"
    else:
        basis = "vat_inclusive_ie_23"
    for anchor in known:
        price = anchor.observation.asking_price_eur
        if price is None or price <= 0:
            continue
        kind = _vat_class(anchor.observation.vat_presentation)
        if basis == "vat_inclusive_ie_23" and kind == "exclusive":
            price = money(price * (Decimal("1") + VAT_RATE))
        priced.append((price, anchor))
    return basis, priced


def apply_adjustment(subject: VehicleIdentity, comp: MarketObservation, effects: EffectModel, price: Decimal) -> Decimal:
    if effects.confidence <= 0:
        return _ZERO
    total = _ZERO
    if subject.year and comp.year:
        total += effects.year_eur * Decimal(subject.year - comp.year)
    if subject.mileage_km and comp.mileage_km:
        total += effects.km_eur * Decimal(subject.mileage_km - comp.mileage_km)
    cap = abs(price) * Decimal("0.35")
    if total > cap:
        total = cap
    elif total < -cap:
        total = -cap
    return money(total)


def _classify(
    subject: VehicleIdentity,
    comp: MarketObservation,
) -> tuple[_Anchor | None, MarketObservation | None, CompScore | None]:
    title = (comp.listing_title or "").lower()
    flags = {flag.lower() for flag in comp.condition_flags}
    if comp.asking_price_eur is None or comp.asking_price_eur <= 0:
        return None, None, _reject(comp, 0, "No positive asking price.")
    if comp.status in {ObservationStatus.DISAPPEARED, ObservationStatus.WITHDRAWN, ObservationStatus.EXPIRED, ObservationStatus.UNKNOWN}:
        return None, None, _reject(comp, 0, f"Status {comp.status.value} is not a price observation. Disappearance is not a sale.")
    if flags.intersection(_DAMAGE_TOKENS) or any(token in title for token in _DAMAGE_TOKENS):
        return None, None, _reject(comp, 0, "Damaged, salvage, or spares listing rejected.")
    if any(token in title for token in _PASSENGER_TOKENS):
        return None, None, _reject(comp, 0, "Passenger, crew, or people-mover title rejected.")
    if any(token in title for token in _NON_RUNNER_TOKENS):
        return None, None, _reject(comp, 0, "Non-runner or spares title rejected.")
    if comp.model_family != subject.model_family:
        if comp.model_family in sibling_families(subject.model_family or ""):
            return None, comp, None
        return None, None, _reject(comp, 0, "Different manufacturer or model family. Sibling platforms are not comps.")
    if subject.generation and comp.generation and subject.generation != comp.generation:
        return None, None, _reject(comp, 0, "Generation mismatch rejected.")
    if subject.fuel.value != "UNKNOWN" and comp.fuel.value != "UNKNOWN" and subject.fuel is not comp.fuel:
        return None, None, _reject(comp, 0, "Fuel mismatch.")
    subject_body = subject.body.value
    comp_body = (comp.body or "UNKNOWN").upper()
    if subject_body in _GOODS_BODIES and comp_body in _PEOPLE_BODIES:
        return None, None, _reject(comp, 0, "Goods body compared with a crew, kombi, or people-mover.")
    if subject_body != "UNKNOWN" and comp_body not in {"", "UNKNOWN"} and subject_body != comp_body:
        return None, None, _reject(comp, 0, "Body configuration differs.")
    if subject.wheelbase and comp.wheelbase and subject.wheelbase != comp.wheelbase:
        return None, None, _reject(comp, 0, "Wheelbase mismatch rejected.")
    year_gap = abs(subject.year - comp.year) if subject.year and comp.year else None
    if year_gap is not None and year_gap > 6:
        return None, None, _reject(comp, 0, "Year gap greater than 6.")
    ratio = None
    if subject.mileage_km and comp.mileage_km and subject.mileage_km > 0:
        ratio = Decimal(comp.mileage_km) / Decimal(subject.mileage_km)
        if ratio < Decimal("0.30") or ratio > Decimal("3.5"):
            return None, None, _reject(comp, 0, "Mileage too far from the subject.")
    close_year = year_gap is not None and year_gap <= 2
    close_miles = ratio is not None and Decimal("0.75") <= ratio <= Decimal("1.35")
    wheel_unknown = not (subject.wheelbase and comp.wheelbase)
    tier = "A" if close_year and close_miles else "B"
    weight = Decimal("1.00") if tier == "A" else Decimal("0.55")
    why = ["Same model family."]
    if tier == "A":
        why.append("Near year and mileage.")
    else:
        why.append("Retained with an explicit year or mileage adjustment.")
    if wheel_unknown:
        weight *= Decimal("0.80")
        why.append("Wheelbase unknown, so the weight is lower.")
    if ratio is not None and not close_miles:
        weight *= Decimal("0.65")
        why.append("Mileage is outside the close band and is adjusted rather than dropped.")
    if year_gap is not None and year_gap >= 3:
        weight *= Decimal("0.70")
    if not subject.mileage_km or not comp.mileage_km:
        weight *= Decimal("0.70")
        why.append("Mileage missing on one side.")
    if subject.transmission and comp.transmission and subject.transmission != comp.transmission:
        weight *= Decimal("0.85")
        why.append("Transmission differs. Weight reduced.")
    score = _score(comp, tier, weight, "; ".join(why))
    return _Anchor(comp, tier, weight, score, "; ".join(why)), None, None


def _score(comp: MarketObservation, tier: str, weight: Decimal, why: str) -> CompScore:
    points = 80 if tier == "A" else 62
    return CompScore(
        observation_id=comp.observation_id,
        listing_id=comp.listing_id,
        score=points,
        close=tier == "A",
        rejected=False,
        reasons=(why, f"Tier {tier}. Weight {weight}."),
        price_eur=comp.asking_price_eur,
        realised=False,
        observed_at_iso=comp.observed_at.isoformat(),
        url=comp.url,
        seller_type=comp.seller_type,
        mileage_km=comp.mileage_km,
        year=comp.year,
        model_family=comp.model_family,
        source=comp.source,
        registration=(comp.registration or "").upper().replace(" ", ""),
        dealer_name=comp.dealer_name or "",
        vat_presentation=comp.vat_presentation,
    )


def _reject(comp: MarketObservation, score: int, reason: str) -> CompScore:
    return CompScore(
        observation_id=comp.observation_id,
        listing_id=comp.listing_id,
        score=score,
        close=False,
        rejected=True,
        reasons=(reason,),
        price_eur=comp.asking_price_eur,
        realised=False,
        observed_at_iso=comp.observed_at.isoformat(),
        url=comp.url,
        seller_type=comp.seller_type,
        mileage_km=comp.mileage_km,
        year=comp.year,
        model_family=comp.model_family,
        source=comp.source,
        registration=(comp.registration or "").upper().replace(" ", ""),
        dealer_name=comp.dealer_name or "",
        vat_presentation=comp.vat_presentation,
    )


def _evidence(anchor: _Anchor, basis_price: Decimal, adjusted: Decimal, adjustment: Decimal, effects: EffectModel) -> dict[str, object]:
    row = anchor.observation
    return {
        "vehicle": f"{row.manufacturer} {row.model_family}".strip(),
        "year": row.year,
        "mileage_km": row.mileage_km,
        "body": row.body,
        "fuel": row.fuel.value,
        "wheelbase": row.wheelbase or "UNKNOWN",
        "asking_price_eur": str(row.asking_price_eur),
        "vat_basis": row.vat_classification or row.vat_presentation or "UNKNOWN",
        "normalised_price_eur": str(basis_price),
        "tier": anchor.tier,
        "similarity_weight": str(anchor.weight),
        "adjustments_eur": str(adjustment),
        "adjusted_price_eur": str(adjusted),
        "effect_basis": effects.basis,
        "why": anchor.why,
    }


def _unknown_vat_evidence(anchor: _Anchor) -> dict[str, object]:
    row = anchor.observation
    return {
        "vehicle": f"{row.manufacturer} {row.model_family}".strip(),
        "year": row.year,
        "mileage_km": row.mileage_km,
        "body": row.body,
        "fuel": row.fuel.value,
        "wheelbase": row.wheelbase or "UNKNOWN",
        "asking_price_eur": str(row.asking_price_eur),
        "vat_basis": "UNKNOWN",
        "normalised_price_eur": None,
        "tier": anchor.tier,
        "similarity_weight": str(anchor.weight),
        "adjustments_eur": "0.00",
        "adjusted_price_eur": None,
        "effect_basis": "vat_interval",
        "why": "Unknown VAT. Excluded from the normalised median. The advertised price remains a bound.",
    }


def _tier_c_evidence(row: MarketObservation) -> dict[str, object]:
    return {
        "vehicle": f"{row.manufacturer} {row.model_family}".strip(),
        "year": row.year,
        "mileage_km": row.mileage_km,
        "body": row.body,
        "fuel": row.fuel.value,
        "wheelbase": row.wheelbase or "UNKNOWN",
        "asking_price_eur": str(row.asking_price_eur),
        "vat_basis": row.vat_classification or row.vat_presentation or "UNKNOWN",
        "normalised_price_eur": None,
        "tier": "C",
        "similarity_weight": "0",
        "adjustments_eur": "0.00",
        "adjusted_price_eur": None,
        "effect_basis": "platform",
        "why": "Platform sibling used only to estimate market effects. Not a price anchor.",
    }


def _sensitivity(mid: Decimal, effects: EffectModel) -> dict[str, str]:
    if effects.confidence <= 0:
        mileage_plus = "no fitted mileage slope"
        mileage_minus = "no fitted mileage slope"
        year_plus = "no fitted age slope"
    else:
        mileage_plus = str(money(mid + effects.km_eur * Decimal("20000")))
        mileage_minus = str(money(mid + effects.km_eur * Decimal("-20000")))
        year_plus = str(money(mid + effects.year_eur))
    return {
        "mileage_plus_20000_km": mileage_plus,
        "mileage_minus_20000_km": mileage_minus,
        "one_model_year_newer": year_plus,
        "vat_interpretation": "Unknown VAT stays an interval. It does not pick a basis.",
        "wheelbase_uncertainty": "Unknown wheelbase lowers weight. A known mismatch is excluded.",
        "asking_haircut_status": "UNCALIBRATED_ASSUMPTION",
    }
