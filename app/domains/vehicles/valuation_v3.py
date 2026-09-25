"""Native valuation v3. Unknown VAT widens the cash interval. It does not drop the comp."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.money import money
from app.domains.vehicles.comps import CompScore
from app.domains.vehicles.effects import EffectModel, fit_effects
from app.domains.vehicles.enums import EvidencePosture
from app.domains.vehicles.identity import VehicleIdentity
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.policy import (
    ASKING_ONLY_CONFIDENCE_CAP,
    ASKING_TO_ACHIEVABLE_DISCOUNT,
    LIQUIDITY_QUICK_SALE_HAIRCUT,
    MARKET_FRESH_DAYS,
)
from app.domains.vehicles.price_interval import PriceInterval, cash_interval
from app.domains.vehicles.tax import VAT_RATE
from app.domains.vehicles.valuation import (
    ValuationResult,
    _drop_duplicate_registrations,
    _drop_same_dealer_van,
    _effective_sample_size,
    _latest_per_listing,
    _liquidity,
    _percentile,
    _weighted_median,
)
from app.domains.vehicles.valuation_v2 import (
    _Anchor,
    _classify,
    _drop_cluster_outliers,
    _reject,
    _tier_c_evidence,
    apply_adjustment,
)

MODEL_VERSION = "arie-native-v3-vat-interval"
_ZERO = Decimal("0")
_CONSERVATIVE_HAIRCUT = Decimal("0.20")


def value_vehicle_v3(subject: VehicleIdentity, book: MarketBook, *, as_of: datetime) -> ValuationResult:
    fresh_after = as_of - timedelta(days=MARKET_FRESH_DAYS)
    visible = book.as_of(as_of)
    fresh_rows = [row for row in visible if row.observed_at >= fresh_after]
    current = _latest_per_listing(fresh_rows)
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
    effects = _exact_effects(anchors, subject.model_family or "")
    used_rows: list[tuple[Decimal, Decimal, Decimal, _Anchor, PriceInterval]] = []
    evidence: list[dict[str, object]] = []
    for anchor in anchors:
        interval = _observation_interval(anchor.observation)
        low, high, adjustment = _adjust_bounds(subject, anchor.observation, effects, interval)
        if low <= 0 or high < low:
            rejected.append(_reject(anchor.observation, 0, "Cash interval collapsed below a positive price."))
            continue
        used_rows.append((low, high, anchor.weight, anchor, interval))
        evidence.append(_evidence(anchor, interval, low, high, adjustment, effects))
    for row in tier_c[:12]:
        evidence.append(_tier_c_evidence(row))
    screened_input = [(low, weight) for low, _high, weight, _anchor, _interval in used_rows]
    screened = _drop_cluster_outliers(screened_input) if screened_input else []
    screened_lows = {price for price, _weight in screened}
    for low, _high, _weight, anchor, _interval in used_rows:
        if low not in screened_lows:
            rejected.append(_reject(anchor.observation, 0, f"Extreme adjusted cash low €{low} left out of the lower market."))
    used = [item for item in used_rows if item[0] in screened_lows]
    lows = [low for low, _high, _weight, _anchor, _interval in used]
    highs = [high for _low, high, _weight, _anchor, _interval in used]
    weights = [weight for _low, _high, weight, _anchor, _interval in used]
    market_label, market_numeric = _market_floor_confidence(used)
    dealer_count, largest_share, unnamed = _dealer_concentration(used)
    concentrated = largest_share > Decimal("0.50") or (dealer_count < 2 and not unnamed)
    if dealer_count > 0 and concentrated and market_label in {"HIGH", "MEDIUM"}:
        market_label = "LOW"
        market_numeric = Decimal("0.48")
    vat_label = _vat_basis_confidence(used)
    central_low = money(_weighted_median(lows, weights)) if lows else None
    central_high = money(_weighted_median(highs, weights)) if highs else None
    cash_low = money(_percentile(lows, Decimal("0.20"))) if lows else None
    cash_high = money(_percentile(highs, Decimal("0.80"))) if highs else None
    if central_low is not None and cash_low is not None:
        cash_low = min(cash_low, central_low)
    if central_high is not None and cash_high is not None:
        cash_high = max(cash_high, central_high)
    issue = market_label in {"HIGH", "MEDIUM"} and central_low is not None
    if not issue:
        central_low = central_low if lows else None
    floor = money(central_low * (Decimal("1") - _CONSERVATIVE_HAIRCUT)) if issue and central_low is not None else None
    expected_low = money(central_low * (Decimal("1") - ASKING_TO_ACHIEVABLE_DISCOUNT)) if issue and central_low is not None else None
    expected_high = money(central_high * (Decimal("1") - ASKING_TO_ACHIEVABLE_DISCOUNT)) if issue and central_high is not None else None
    exact_book = bool(used) and all(interval.exact for _l, _h, _w, _a, interval in used)
    single_expected = None
    if issue and expected_low is not None and (exact_book or vat_label == "HIGH"):
        single_expected = expected_low
    stress = money(floor / (Decimal("1") + VAT_RATE)) if floor is not None else None
    if floor is not None and stress is not None and stress > floor:
        stress = floor
    tier_a = sum(1 for _l, _h, _w, anchor, _i in used if anchor.tier == "A")
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
    quick = money(floor * (Decimal("1") - haircut)) if floor is not None else None
    known = sum(1 for _l, _h, _w, _a, interval in used if interval.exact)
    share = _ZERO if not used else (Decimal(known) / Decimal(len(used))).quantize(Decimal("0.01"))
    sample = _effective_sample_size(weights) if weights else _ZERO
    prebid = floor is not None
    notes = [
        f"Model {MODEL_VERSION}. Asking-to-achievable asking-haircut-v1 is an estimate, not a measured clearance rate.",
        "ASKING-TO-ACHIEVABLE ADJUSTMENT: 15% base. CONSERVATIVE HAIRCUT: 20% of the lower cash central. STATUS: UNCALIBRATED_ASSUMPTION.",
        "Unknown VAT is the interval [advertised, advertised×(1+VAT)]. It is not treated as inclusive or exclusive.",
        "The conservative resale floor uses only the lower cash distribution.",
        "FULL_OUTPUT_VAT_STRESS is cash floor / (1+VAT). It is a downside screen, not the owner's legal treatment.",
        f"Age/mileage basis: {effects.basis}. Sample {effects.sample_size}. Confidence {effects.confidence}.",
        f"Market-floor confidence {market_label}. VAT-basis confidence {vat_label}.",
        f"Tier A {tier_a}. Used comps {len(used)}. Tier C {len(tier_c)}.",
    ]
    if not exact_book:
        notes.append("VAT basis is materially uncertain, so a single expected achievable value is withheld.")
    if market_label in {"LOW", "INSUFFICIENT"}:
        notes.append("Market evidence is not strong enough for a conservative resale floor.")
    freshness = None
    if fresh_rows:
        newest = max(row.observed_at for row in fresh_rows)
        freshness = int((as_of - newest).total_seconds() // 3600)
    return ValuationResult(
        market_asking_eur=central_low if issue else None,
        expected_achievable_eur=single_expected,
        conservative_eur=floor,
        quick_sale_eur=quick,
        asking_low_eur=cash_low if issue else None,
        asking_high_eur=cash_high if issue else None,
        confidence=market_numeric,
        confidence_posture=EvidencePosture.ESTIMATED if issue else EvidencePosture.UNKNOWN,
        comparable_count=len(used),
        close_count=tier_a,
        realised_count=0,
        freshness_hours=freshness,
        fresh=bool(fresh_rows) and bool(used),
        comps=tuple(anchor.score for _l, _h, _w, anchor, _i in used),
        rejected=tuple(rejected),
        liquidity=liquidity,
        discount_applied=ASKING_TO_ACHIEVABLE_DISCOUNT,
        notes=tuple(notes),
        source_count=len({anchor.observation.source for _l, _h, _w, anchor, _i in used}),
        adjustment_reasons=(f"year €{effects.year_eur}/year", f"mileage €{effects.km_eur}/km", f"basis {effects.basis}"),
        model_version=MODEL_VERSION,
        effective_sample_size=sample,
        vat_basis="exact" if exact_book else "VAT_UNCERTAIN",
        trade_downside_eur=stress,
        median_comp_age_days=liquidity.median_age_days,
        haircut_sensitivity={
            "lower_central": str(central_low) if central_low is not None else None,
            "asking_to_achievable": str(expected_low) if expected_low is not None else None,
            "conservative_floor": str(floor) if floor is not None else None,
        }
        if central_low is not None
        else None,
        confidence_label=market_label,
        tier_a_count=sum(1 for anchor in anchors if anchor.tier == "A"),
        tier_b_count=sum(1 for anchor in anchors if anchor.tier == "B"),
        tier_c_count=len(tier_c),
        known_vat_share=str(share),
        evidence=tuple(evidence),
        sensitivity={
            "vat_interpretation": "Unknown VAT stays [P, P×(1+rate)]. The floor uses P.",
            "asking_haircut_status": "UNCALIBRATED_ASSUMPTION",
        },
        effect_basis=effects.basis,
        market_floor_confidence=market_label,
        vat_basis_confidence=vat_label,
        market_cash_low_eur=cash_low if issue else None,
        market_cash_central_low_eur=central_low if issue else None,
        market_cash_central_high_eur=central_high if issue else None,
        market_cash_high_eur=cash_high if issue else None,
        expected_achievable_low_eur=expected_low,
        expected_achievable_high_eur=expected_high,
        vat_stress_proceeds_eur=stress,
        prebid_floor_available=prebid,
        prebid_state="PREBID_FLOOR_AVAILABLE" if prebid else "",
        dealer_count=dealer_count,
        largest_dealer_share=str(largest_share),
    )


def _dealer_concentration(used: list[tuple[Decimal, Decimal, Decimal, _Anchor, PriceInterval]]) -> tuple[int, Decimal, bool]:
    """Share is of the whole priced book. Unnamed marketplace rows are not one dealer."""

    totals: dict[str, Decimal] = {}
    weight_sum = _ZERO
    unnamed = False
    for _low, _high, weight, anchor, _interval in used:
        weight_sum += weight
        name = (anchor.observation.dealer_name or "").strip()
        if not name:
            unnamed = True
            continue
        totals[name.casefold()] = totals.get(name.casefold(), _ZERO) + weight
    if not totals or weight_sum <= 0:
        return 0, _ZERO, unnamed
    largest = max(totals.values()) / weight_sum
    return len(totals), largest.quantize(Decimal("0.01")), unnamed


def _exact_effects(anchors: list[_Anchor], family: str) -> EffectModel:
    exact: list[MarketObservation] = []
    for anchor in anchors:
        if anchor.observation.model_family != family:
            continue
        interval = _observation_interval(anchor.observation)
        if not interval.exact or not anchor.observation.year or not anchor.observation.mileage_km:
            continue
        exact.append(replace(anchor.observation, asking_price_eur=interval.cash_low_eur))
    if len(exact) < 8:
        return EffectModel(_ZERO, _ZERO, "exact_insufficient", len(exact), _ZERO)
    fitted = fit_effects(exact, family)
    if fitted.confidence <= 0 or fitted.basis == "none":
        return EffectModel(_ZERO, _ZERO, "exact_insufficient", len(exact), _ZERO)
    return fitted


def _observation_interval(row: MarketObservation) -> PriceInterval:
    advertised = row.advertised_price_eur or row.asking_price_eur or _ZERO
    return cash_interval(
        advertised,
        row.vat_classification,
        presentation=row.vat_presentation,
        evidence=row.vat_fragment,
    )


def _adjust_bounds(
    subject: VehicleIdentity,
    comp: MarketObservation,
    effects: EffectModel,
    interval: PriceInterval,
) -> tuple[Decimal, Decimal, Decimal]:
    delta = apply_adjustment(subject, comp, effects, interval.cash_low_eur)
    low = money(interval.cash_low_eur + delta)
    high = money(interval.cash_high_eur + delta)
    if low > high:
        low, high = high, low
    return low, high, delta


def _market_floor_confidence(used: list[tuple[Decimal, Decimal, Decimal, _Anchor, PriceInterval]]) -> tuple[str, Decimal]:
    if len(used) < 2:
        return "INSUFFICIENT", Decimal("0.35")
    weights = [weight for _l, _h, weight, _a, _i in used]
    sample = _effective_sample_size(weights)
    tier_a = sum(1 for _l, _h, _w, anchor, _i in used if anchor.tier == "A")
    lows = [low for low, _h, _w, _a, _i in used]
    mid = _weighted_median(lows, weights)
    spread = _ZERO
    if mid > 0 and len(lows) >= 2:
        spread = (_percentile(lows, Decimal("0.80")) - _percentile(lows, Decimal("0.20"))) / mid
    if tier_a >= 5 and sample >= Decimal("8") and spread <= Decimal("0.40") and len(used) >= 8:
        return "HIGH", ASKING_ONLY_CONFIDENCE_CAP
    if len(used) >= 5 and sample >= Decimal("3.5") and tier_a >= 1:
        return "MEDIUM", Decimal("0.60")
    if len(used) >= 2:
        return "LOW", Decimal("0.48")
    return "INSUFFICIENT", Decimal("0.35")


def _vat_basis_confidence(used: list[tuple[Decimal, Decimal, Decimal, _Anchor, PriceInterval]]) -> str:
    if not used:
        return "LOW"
    known = sum(1 for _l, _h, _w, _a, interval in used if interval.exact)
    share = Decimal(known) / Decimal(len(used))
    if share >= Decimal("0.70") and known >= 5:
        return "HIGH"
    if share >= Decimal("0.25") and known >= 2:
        return "MEDIUM"
    return "LOW"


def _evidence(
    anchor: _Anchor,
    interval: PriceInterval,
    adjusted_low: Decimal,
    adjusted_high: Decimal,
    adjustment: Decimal,
    effects: EffectModel,
) -> dict[str, object]:
    row = anchor.observation
    return {
        "vehicle": f"{row.manufacturer} {row.model_family}".strip(),
        "year": row.year,
        "mileage_km": row.mileage_km,
        "body": row.body,
        "fuel": row.fuel.value,
        "wheelbase": row.wheelbase or "UNKNOWN",
        "asking_price_eur": str(interval.advertised_eur),
        "advertised_eur": str(interval.advertised_eur),
        "cash_low_eur": str(interval.cash_low_eur),
        "cash_high_eur": str(interval.cash_high_eur),
        "adjusted_low_eur": str(adjusted_low),
        "adjusted_high_eur": str(adjusted_high),
        "vat_basis": interval.basis,
        "vat_classification": interval.vat_classification,
        "exact": interval.exact,
        "normalised_price_eur": str(interval.cash_low_eur) if interval.exact else None,
        "tier": anchor.tier,
        "similarity_weight": str(anchor.weight),
        "adjustments_eur": str(adjustment),
        "adjusted_price_eur": str(adjusted_low),
        "effect_basis": effects.basis,
        "why": anchor.why,
        "evidence": interval.evidence,
    }
