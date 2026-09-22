"""Irish resale valuation. Asking, achievable, conservative, and quick-sale stay separate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median

from app.core.money import money
from app.domains.vehicles.comps import CompScore, score_comp
from app.domains.vehicles.enums import EvidencePosture, LiquidityClass
from app.domains.vehicles.identity import VehicleIdentity
from app.domains.vehicles.market import MarketBook, MarketObservation
from app.domains.vehicles.policy import (
    ASKING_ONLY_CONFIDENCE_CAP,
    ASKING_TO_ACHIEVABLE_DISCOUNT,
    LIQUIDITY_QUICK_SALE_HAIRCUT,
    MARKET_FRESH_DAYS,
    MIN_REALISED_FOR_UNCAPPED_CONFIDENCE,
)


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


def value_vehicle(
    subject: VehicleIdentity,
    book: MarketBook,
    *,
    as_of: datetime,
) -> ValuationResult:
    fresh_after = as_of - timedelta(days=MARKET_FRESH_DAYS)
    visible = book.as_of(as_of)
    fresh_rows = [row for row in visible if row.observed_at >= fresh_after]
    scored = [score_comp(subject, row) for row in fresh_rows]
    rejected = tuple(row for row in scored if row.rejected)
    kept = [row for row in scored if not row.rejected and row.price_eur is not None]
    asking = [row for row in kept if not row.realised]
    realised = [row for row in kept if row.realised]
    asking_prices = _mad_keep([row.price_eur for row in asking if row.price_eur is not None])
    realised_prices = [row.price_eur for row in realised if row.price_eur is not None]

    notes: list[str] = []
    market_asking = money(Decimal(str(median(asking_prices)))) if asking_prices else None
    asking_low = money(min(asking_prices)) if asking_prices else None
    asking_high = money(max(asking_prices)) if asking_prices else None
    discount = ASKING_TO_ACHIEVABLE_DISCOUNT if len(realised_prices) < MIN_REALISED_FOR_UNCAPPED_CONFIDENCE else Decimal("0")

    if len(realised_prices) >= MIN_REALISED_FOR_UNCAPPED_CONFIDENCE:
        realised_central = money(Decimal(str(median(realised_prices))))
        if market_asking is not None:
            haircut_asking = money(market_asking * (Decimal("1") - ASKING_TO_ACHIEVABLE_DISCOUNT))
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
        adjusted = [money(price * (Decimal("1") - ASKING_TO_ACHIEVABLE_DISCOUNT)) for price in asking_prices]
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

    close_count = sum(1 for row in kept if row.close)
    confidence = _confidence(kept, realised, close_count, fresh_rows, as_of)
    freshness_hours = None
    if fresh_rows:
        newest = max(row.observed_at for row in fresh_rows)
        freshness_hours = int((as_of - newest).total_seconds() // 3600)
    fresh = bool(fresh_rows) and expected is not None
    if not fresh:
        notes.append("Market evidence is missing or older than the freshness window.")

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
