"""Irish resale valuation. Asking, achievable, conservative, and quick-sale stay separate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.core.money import money
from app.domains.vehicles.comps import CompScore, score_comp
from app.domains.vehicles.enums import EvidencePosture, LiquidityClass, ObservationStatus
from app.domains.vehicles.identity import VehicleIdentity
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.tax import VAT_RATE
from app.domains.vehicles.policy import (
    ASKING_ONLY_CONFIDENCE_CAP,
    ASKING_TO_ACHIEVABLE_DISCOUNT,
    LIQUIDITY_QUICK_SALE_HAIRCUT,
    MARKET_FRESH_DAYS,
    MIN_REALISED_FOR_UNCAPPED_CONFIDENCE,
)


@dataclass(frozen=True, slots=True)
class ValueBand:
    name: str
    value_eur: Decimal | None
    low_eur: Decimal | None
    high_eur: Decimal | None
    confidence: Decimal
    comparable_count: int
    freshness_hours: int | None
    close_count: int
    source_count: int
    market_depth: str
    adjustment: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value_eur": _s(self.value_eur),
            "low_eur": _s(self.low_eur),
            "high_eur": _s(self.high_eur),
            "confidence": str(self.confidence),
            "comparable_count": self.comparable_count,
            "freshness_hours": self.freshness_hours,
            "close_count": self.close_count,
            "source_count": self.source_count,
            "market_depth": self.market_depth,
            "adjustment": self.adjustment,
        }


@dataclass(frozen=True, slots=True)
class LiquidityResult:
    classification: LiquidityClass
    active_supply: int
    eligible_count: int
    close_count: int
    realised_count: int
    median_age_days: int | None
    reduction_listings: int
    disappeared_count: int
    interpretation: str

    def to_dict(self) -> dict[str, object]:
        return {
            "classification": self.classification.value,
            "active_supply": self.active_supply,
            "eligible_count": self.eligible_count,
            "close_count": self.close_count,
            "realised_count": self.realised_count,
            "median_age_days": self.median_age_days,
            "reduction_listings": self.reduction_listings,
            "disappeared_count": self.disappeared_count,
            "interpretation": self.interpretation,
        }


@dataclass(frozen=True, slots=True)
class ValuationResult:
    market_asking_eur: Decimal | None
    expected_achievable_eur: Decimal | None
    conservative_eur: Decimal | None
    quick_sale_eur: Decimal | None
    asking_low_eur: Decimal | None
    asking_high_eur: Decimal | None
    confidence: Decimal
    confidence_posture: EvidencePosture
    comparable_count: int
    close_count: int
    realised_count: int
    freshness_hours: int | None
    fresh: bool
    comps: tuple[CompScore, ...]
    rejected: tuple[CompScore, ...]
    liquidity: LiquidityResult
    discount_applied: Decimal
    notes: tuple[str, ...]
    bands: tuple[ValueBand, ...] = ()
    source_count: int = 0
    adjustment_reasons: tuple[str, ...] = ()
    model_version: str = "arie-native-v1"
    effective_sample_size: Decimal = Decimal("0")
    vat_basis: str = "as_stated"
    trade_downside_eur: Decimal | None = None
    median_comp_age_days: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "market_asking_eur": _s(self.market_asking_eur),
            "expected_achievable_eur": _s(self.expected_achievable_eur),
            "conservative_eur": _s(self.conservative_eur),
            "quick_sale_eur": _s(self.quick_sale_eur),
            "asking_low_eur": _s(self.asking_low_eur),
            "asking_high_eur": _s(self.asking_high_eur),
            "confidence": str(self.confidence),
            "confidence_posture": self.confidence_posture.value,
            "comparable_count": self.comparable_count,
            "close_count": self.close_count,
            "realised_count": self.realised_count,
            "freshness_hours": self.freshness_hours,
            "fresh": self.fresh,
            "discount_applied": str(self.discount_applied),
            "source_count": self.source_count,
            "adjustment_reasons": list(self.adjustment_reasons),
            "model_version": self.model_version,
            "effective_sample_size": str(self.effective_sample_size),
            "vat_basis": self.vat_basis,
            "trade_downside_eur": _s(self.trade_downside_eur),
            "median_comp_age_days": self.median_comp_age_days,
            "bands": [band.to_dict() for band in self.bands],
            "liquidity": self.liquidity.to_dict(),
            "comps": [comp.to_dict() for comp in self.comps],
            "rejected_comps": [comp.to_dict() for comp in self.rejected],
            "notes": list(self.notes),
        }


def _s(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _percentile(values: list[Decimal], fraction: Decimal) -> Decimal:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - Decimal(lower)
    return ordered[lower] * (Decimal("1") - weight) + ordered[upper] * weight


def _mad_keep(prices: list[Decimal]) -> list[Decimal]:
    if len(prices) < 4:
        return list(prices)
    centre = Decimal(str(median(prices)))
    deviations = sorted(abs(price - centre) for price in prices)
    mad = Decimal(str(median(deviations)))
    if mad == 0:
        return list(prices)
    kept: list[Decimal] = []
    for price in prices:
        modified_z = abs(price - centre) / mad
        if modified_z <= Decimal("3.5"):
            kept.append(price)
    return kept or list(prices)


def _mad_pairs(pairs: list[tuple[Decimal, Decimal]]) -> list[tuple[Decimal, Decimal]]:
    if len(pairs) < 4:
        return list(pairs)
    prices = [price for price, _weight in pairs]
    centre = Decimal(str(median(prices)))
    deviations = sorted(abs(price - centre) for price in prices)
    mad = Decimal(str(median(deviations)))
    if mad == 0:
        return list(pairs)
    kept = [pair for pair in pairs if abs(pair[0] - centre) / mad <= Decimal("3.5")]
    return kept or list(pairs)


def _drop_same_dealer_van(kept: list[CompScore]) -> tuple[list[CompScore], list[CompScore]]:
    """The same dealer van must not be counted twice. Spec-only matches stay separate."""

    chosen: dict[tuple[str, int | None, int | None, str, str], CompScore] = {}
    order: list[CompScore] = []
    duplicates: list[CompScore] = []
    for row in sorted(kept, key=lambda item: item.score, reverse=True):
        if not row.dealer_name:
            order.append(row)
            continue
        key = (row.dealer_name.casefold(), row.year, row.mileage_km, str(row.price_eur), row.model_family)
        if key in chosen:
            duplicates.append(
                CompScore(
                    observation_id=row.observation_id,
                    listing_id=row.listing_id,
                    score=row.score,
                    close=False,
                    rejected=True,
                    reasons=row.reasons + ("Same dealer, year, mileage, and price. Not counted twice.",),
                    price_eur=row.price_eur,
                    realised=False,
                    observed_at_iso=row.observed_at_iso,
                    url=row.url,
                    seller_type=row.seller_type,
                    mileage_km=row.mileage_km,
                    year=row.year,
                    model_family=row.model_family,
                    source=row.source,
                    registration=row.registration,
                    dealer_name=row.dealer_name,
                    differences=row.differences,
                    vat_presentation=row.vat_presentation,
                )
            )
            continue
        chosen[key] = row
        order.append(row)
    return order, duplicates


def _liquidity(
    *,
    active_supply: int,
    eligible: int,
    close: int,
    realised: int,
    ages: list[int],
    reductions: int,
    disappeared: int,
) -> LiquidityResult:
    median_age = int(median(ages)) if ages else None
    if active_supply == 0 and eligible == 0:
        klass = LiquidityClass.UNKNOWN
        text = "No current Irish supply was supplied to the market book."
    elif active_supply >= 25 and median_age is not None and median_age <= 30:
        klass = LiquidityClass.DEEP
        text = "Deep current supply and short listing ages."
    elif active_supply >= 12 and (median_age is None or median_age <= 45):
        klass = LiquidityClass.ADEQUATE
        text = "Enough active supply to treat a sale as plausible, still not fast by assumption."
    elif active_supply < 3 or (median_age is not None and median_age > 120):
        klass = LiquidityClass.ILLIQUID
        text = "Thin or stale supply. A theoretical value may take a long time to realise."
    else:
        klass = LiquidityClass.THIN
        text = "Limited active supply."
    if disappeared:
        text += f" {disappeared} disappeared listing(s) were not counted as sales."
    return LiquidityResult(
        classification=klass,
        active_supply=active_supply,
        eligible_count=eligible,
        close_count=close,
        realised_count=realised,
        median_age_days=median_age,
        reduction_listings=reductions,
        disappeared_count=disappeared,
        interpretation=text,
    )


def _latest_per_listing(rows: list[MarketObservation]) -> list[MarketObservation]:
    latest: dict[str, MarketObservation] = {}
    for row in rows:
        current = latest.get(row.listing_id)
        if current is None or row.observed_at >= current.observed_at:
            latest[row.listing_id] = row
    return list(latest.values())


def _drop_duplicate_registrations(kept: list[CompScore]) -> tuple[list[CompScore], list[CompScore]]:
    """One physical listing should not support the value twice."""

    chosen: dict[str, CompScore] = {}
    order: list[CompScore] = []
    duplicates: list[CompScore] = []
    for row in sorted(kept, key=lambda item: item.score, reverse=True):
        key = row.registration
        if not key:
            order.append(row)
            continue
        if key in chosen:
            duplicates.append(
                CompScore(
                    observation_id=row.observation_id,
                    listing_id=row.listing_id,
                    score=row.score,
                    close=False,
                    rejected=True,
                    reasons=row.reasons + ("Duplicate registration rejected.",),
                    price_eur=row.price_eur,
                    realised=False,
                    observed_at_iso=row.observed_at_iso,
                    url=row.url,
                    seller_type=row.seller_type,
                    mileage_km=row.mileage_km,
                    year=row.year,
                    model_family=row.model_family,
                    source=row.source,
                    registration=row.registration,
                )
            )
            continue
        chosen[key] = row
        order.append(row)
    return order, duplicates


def _asking_discount(
    *,
    visible: list[MarketObservation],
    subject: VehicleIdentity,
    as_of: datetime,
    realised_count: int,
) -> tuple[Decimal, tuple[str, ...]]:
    """Conservative asking-to-achievable gap. Never a fabricated sold price."""

    if realised_count >= MIN_REALISED_FOR_UNCAPPED_CONFIDENCE:
        return Decimal("0"), ("Enough realised sales to anchor achievable value. Asking prices stay secondary.",)
    notes = [
        "No fabricated sold price. Disappearance, withdrawal, and expiry are not sales.",
        f"Base asking haircut is {ASKING_TO_ACHIEVABLE_DISCOUNT} because realised Irish sales are thin.",
    ]
    extra = Decimal("0")
    family = [
        row
        for row in visible
        if row.model_family == subject.model_family and row.manufacturer == subject.manufacturer
    ]
    by_listing: dict[str, list[MarketObservation]] = {}
    for row in family:
        by_listing.setdefault(row.listing_id, []).append(row)
    aged = 0
    reduced = 0
    active = 0
    for rows in by_listing.values():
        ordered = sorted(rows, key=lambda item: item.observed_at)
        latest = ordered[-1]
        if latest.status in {
            ObservationStatus.DISAPPEARED,
            ObservationStatus.WITHDRAWN,
            ObservationStatus.EXPIRED,
            ObservationStatus.UNKNOWN,
        }:
            continue
        active += 1
        if (as_of - ordered[0].observed_at).days > 45:
            aged += 1
        prices = [row.asking_price_eur for row in ordered if row.asking_price_eur is not None]
        if len(prices) >= 2 and prices[-1] < prices[0]:
            reduced += 1
    if active and aged / active >= 0.5:
        extra += Decimal("0.05")
        notes.append("At least half of the current listings have been up more than 45 days. The haircut widens.")
    if active and reduced / active >= 0.3:
        extra += Decimal("0.03")
        notes.append("Repeated asking-price cuts widen the haircut. The cut itself is not treated as a sold price.")
    discount = min(Decimal("0.30"), ASKING_TO_ACHIEVABLE_DISCOUNT + extra)
    return discount, tuple(notes)


MODEL_VERSION = "arie-native-v1"
ASKING_MODEL_VERSION = "asking-haircut-v1"
_INCLUSIVE = {"inclusive", "inc_vat", "vat_inclusive", "gross"}
_EXCLUSIVE = {"ex_vat", "exclusive", "plus_vat", "vat_exclusive", "net", "qualifying", "vat_qualifying"}


def _vat_class(text: str) -> str:
    folded = (text or "").casefold().replace("-", " ").replace("_", " ")
    token = folded.strip()
    compact = token.replace(" ", "_")
    if compact in _INCLUSIVE or token in _INCLUSIVE:
        return "inclusive"
    if compact in _EXCLUSIVE or token in _EXCLUSIVE:
        return "exclusive"
    return "unknown"


def _weighted_median(prices: list[Decimal], weights: list[Decimal]) -> Decimal:
    pairs = sorted(zip(prices, weights, strict=True), key=lambda item: item[0])
    total = sum(weights, Decimal("0"))
    if total <= 0:
        return Decimal(str(median(prices)))
    half = total / Decimal("2")
    running = Decimal("0")
    for price, weight in pairs:
        running += weight
        if running >= half:
            return price
    return pairs[-1][0]


def _effective_sample_size(weights: list[Decimal]) -> Decimal:
    total = sum(weights, Decimal("0"))
    square = sum((weight * weight for weight in weights), Decimal("0"))
    if square == 0:
        return Decimal("0")
    return (total * total / square).quantize(Decimal("0.01"))


def _coarse(value: Decimal | None, low: Decimal | None, high: Decimal | None) -> Decimal | None:
    """Keep cent precision when the comp range is tight. Wide ranges round to the evidence."""

    if value is None:
        return None
    if low is None or high is None or (high - low) < Decimal("200"):
        return money(value)
    step = Decimal("100") if (high - low) < Decimal("2000") else Decimal("250")
    units = (value / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return money(units * step)


def _estimate_prices(
    rows: list[CompScore],
) -> tuple[list[Decimal], list[Decimal], str, bool, bool]:
    """Prices on one VAT basis, weights, basis label, whether unknown VAT was used, whether unknown VAT was dropped."""

    classes = [_vat_class(row.vat_presentation) for row in rows if row.price_eur is not None]
    known = {item for item in classes if item != "unknown"}
    unknown_present = "unknown" in classes
    usable = [row for row in rows if row.price_eur is not None]
    if len(known) <= 1:
        basis = "ex_vat" if known == {"exclusive"} else "vat_inclusive" if known == {"inclusive"} else "unknown"
        prices = [row.price_eur for row in usable if row.price_eur is not None]
        weights = [Decimal(max(row.score, 1)) for row in usable]
        return prices, weights, basis, unknown_present and basis == "unknown", False
    prices: list[Decimal] = []
    weights: list[Decimal] = []
    for row in usable:
        kind = _vat_class(row.vat_presentation)
        if kind == "unknown" or row.price_eur is None:
            continue
        amount = row.price_eur if kind == "inclusive" else money(row.price_eur * (Decimal("1") + VAT_RATE))
        prices.append(amount)
        weights.append(Decimal(max(row.score, 1)))
    return prices, weights, "vat_inclusive_ie_23", False, unknown_present


def value_vehicle(
    subject: VehicleIdentity,
    book: MarketBook,
    *,
    as_of: datetime,
) -> ValuationResult:
    fresh_after = as_of - timedelta(days=MARKET_FRESH_DAYS)
    visible = book.as_of(as_of)
    fresh_rows = [row for row in visible if row.observed_at >= fresh_after]
    current_rows = _latest_per_listing(fresh_rows)
    scored = [score_comp(subject, row) for row in current_rows]
    rejected_rows = [row for row in scored if row.rejected]
    kept = [row for row in scored if not row.rejected and row.price_eur is not None]
    kept, duplicate_rejected = _drop_duplicate_registrations(kept)
    kept, dealer_duplicates = _drop_same_dealer_van(kept)
    rejected = tuple(rejected_rows + duplicate_rejected + dealer_duplicates)
    asking = [row for row in kept if not row.realised]
    realised = [row for row in kept if row.realised]
    raw_prices, weights, vat_basis, unknown_vat_used, unknown_vat_dropped = _estimate_prices(asking)
    paired = list(zip(raw_prices, weights, strict=True))
    screened = _mad_pairs(paired)
    asking_prices = [price for price, _weight in screened]
    asking_weights = [weight for _price, weight in screened]
    realised_prices = [row.price_eur for row in realised if row.price_eur is not None]
    discount, discount_notes = _asking_discount(
        visible=visible,
        subject=subject,
        as_of=as_of,
        realised_count=len(realised_prices),
    )
    notes: list[str] = list(discount_notes)
    notes.append(f"Model {MODEL_VERSION}. Asking-to-achievable {ASKING_MODEL_VERSION} is an estimate, not a measured clearance rate.")
    if unknown_vat_dropped:
        notes.append("Comps with unknown VAT were left out of the central estimate because other comps had a known VAT basis.")
    if vat_basis == "vat_inclusive_ie_23":
        notes.append("Mixed VAT presentations were converted to VAT-inclusive euro at the Irish 23% rate.")
    if unknown_vat_used:
        notes.append("VAT presentation is unknown, so prices were not grossed up and confidence is capped.")
    market_asking = money(_weighted_median(asking_prices, asking_weights)) if asking_prices else None
    asking_low = money(_percentile(asking_prices, Decimal("0.20"))) if asking_prices else None
    asking_high = money(_percentile(asking_prices, Decimal("0.80"))) if asking_prices else None
    asking_haircut = discount if discount > 0 else ASKING_TO_ACHIEVABLE_DISCOUNT

    if len(realised_prices) >= MIN_REALISED_FOR_UNCAPPED_CONFIDENCE:
        realised_central = money(Decimal(str(median(realised_prices))))
        if market_asking is not None:
            haircut_asking = money(market_asking * (Decimal("1") - asking_haircut))
            expected = money((realised_central * Decimal("0.70")) + (haircut_asking * Decimal("0.30")))
        else:
            expected = realised_central
        notes.append("Realised sales anchor the achievable value. Asking prices are secondary.")
        posture = EvidencePosture.ESTIMATED
    elif market_asking is not None:
        expected = money(market_asking * (Decimal("1") - discount))
        notes.append(
            f"No sufficient realised sales. Achievable value is the asking median minus {discount}, not the asking price."
        )
        posture = EvidencePosture.ESTIMATED
    else:
        expected = None
        posture = EvidencePosture.UNKNOWN
        notes.append("Not enough priced Irish comps inside the freshness window.")

    if asking_prices and expected is not None:
        adjusted = [money(price * (Decimal("1") - asking_haircut)) for price in asking_prices]
        if realised_prices:
            adjusted.extend(realised_prices)
        conservative = money(min(expected, _percentile(adjusted, Decimal("0.25"))))
    elif expected is not None:
        conservative = expected
    else:
        conservative = None

    ages = [max(0, (as_of - row.observed_at).days) for row in fresh_rows]
    listing_prices: dict[str, list[Decimal]] = {}
    for row in visible:
        if row.model_family == subject.model_family and row.asking_price_eur is not None:
            listing_prices.setdefault(row.listing_id, []).append(row.asking_price_eur)
    reductions = sum(1 for prices in listing_prices.values() if len(prices) > 1)
    disappeared = sum(1 for row in scored if any("Disappearance" in reason for reason in row.reasons))
    active_supply = len({row.listing_id for row in asking})
    liquidity = _liquidity(
        active_supply=active_supply,
        eligible=len(kept),
        close=sum(1 for row in kept if row.close),
        realised=len(realised),
        ages=ages,
        reductions=reductions,
        disappeared=disappeared,
    )
    haircut = LIQUIDITY_QUICK_SALE_HAIRCUT[liquidity.classification.value]
    quick = money(conservative * (Decimal("1") - haircut)) if conservative is not None else None
    trade_downside = money(_percentile(adjusted, Decimal("0.10"))) if asking_prices and expected is not None else None

    close_count = sum(1 for row in kept if row.close)
    confidence = _confidence(kept, realised, close_count, fresh_rows, as_of)
    if unknown_vat_used:
        confidence = min(confidence, Decimal("0.55"))
    sample_size = _effective_sample_size(asking_weights) if asking_weights else Decimal("0")
    freshness_hours = None
    if fresh_rows:
        newest = max(row.observed_at for row in fresh_rows)
        freshness_hours = int((as_of - newest).total_seconds() // 3600)
    fresh_book = bool(fresh_rows) and expected is not None
    enough = len(kept) >= 5 and close_count >= 3
    if not fresh_book:
        notes.append("Market evidence is missing or older than the freshness window. No resale value is issued from stale comps.")
        market_asking = None
        expected = None
        conservative = None
        quick = None
        trade_downside = None
        asking_low = None
        asking_high = None
        fresh = False
    elif not enough:
        notes.append("Fewer than 5 kept comps or fewer than 3 close comps. No resale value is issued.")
        market_asking = None
        expected = None
        conservative = None
        quick = None
        trade_downside = None
        asking_low = None
        asking_high = None
        fresh = False
    else:
        fresh = True
        market_asking = _coarse(market_asking, asking_low, asking_high)
        expected = _coarse(expected, asking_low, asking_high)
        conservative = _coarse(conservative, asking_low, asking_high)
        quick = _coarse(quick, asking_low, asking_high)
        trade_downside = _coarse(trade_downside, asking_low, asking_high)
        asking_low = _coarse(asking_low, asking_low, asking_high)
        asking_high = _coarse(asking_high, asking_low, asking_high)

    source_count = len({row.source for row in kept if row.source})
    depth = liquidity.classification.value
    weak = expected is None
    band_confidence = Decimal("0") if weak else confidence

    def band(name: str, value: Decimal | None, low: Decimal | None, high: Decimal | None, adjustment: str) -> ValueBand:
        return ValueBand(
            name=name,
            value_eur=None if weak else value,
            low_eur=None if weak else low,
            high_eur=None if weak else high,
            confidence=band_confidence,
            comparable_count=len(kept),
            freshness_hours=freshness_hours,
            close_count=close_count,
            source_count=source_count,
            market_depth=depth,
            adjustment=adjustment,
        )

    bands = (
        band("asking_market", market_asking, asking_low, asking_high, "Median current asking price after the outlier screen. Not a sale price."),
        band("expected_achievable", expected, None, None, " ".join(discount_notes)),
        band("conservative_resale", conservative, None, None, "Lower of achievable value and the lower quartile of haircut asking prices."),
        band("quick_sale", quick, None, None, f"Conservative value minus the {liquidity.classification.value} liquidity haircut."),
    )
    return ValuationResult(
        market_asking_eur=market_asking,
        expected_achievable_eur=expected,
        conservative_eur=conservative,
        quick_sale_eur=quick,
        asking_low_eur=asking_low,
        asking_high_eur=asking_high,
        confidence=confidence,
        confidence_posture=posture,
        comparable_count=len(kept),
        close_count=close_count,
        realised_count=len(realised),
        freshness_hours=freshness_hours,
        fresh=fresh,
        comps=tuple(kept),
        rejected=rejected,
        liquidity=liquidity,
        discount_applied=discount,
        notes=tuple(notes),
        bands=bands,
        source_count=source_count,
        adjustment_reasons=tuple(discount_notes),
        model_version=MODEL_VERSION,
        effective_sample_size=sample_size,
        vat_basis=vat_basis,
        trade_downside_eur=trade_downside,
        median_comp_age_days=liquidity.median_age_days,
    )


def _confidence(
    kept: list[CompScore],
    realised: list[CompScore],
    close_count: int,
    fresh_rows: list[MarketObservation],
    as_of: datetime,
) -> Decimal:
    if len(kept) < 5 or close_count < 3:
        return Decimal("0.35")
    score = Decimal("0.45") + (Decimal(min(len(kept), 20)) / Decimal("100"))
    score += Decimal(min(close_count, 10)) / Decimal("200")
    if fresh_rows:
        newest = max(row.observed_at for row in fresh_rows)
        hours = Decimal(str((as_of - newest).total_seconds() / 3600))
        if hours > 72:
            score -= Decimal("0.08")
    if len(realised) < MIN_REALISED_FOR_UNCAPPED_CONFIDENCE:
        score = min(score, ASKING_ONLY_CONFIDENCE_CAP)
    else:
        score += Decimal("0.08")
    return min(Decimal("0.90"), max(Decimal("0.20"), score.quantize(Decimal("0.01"))))
