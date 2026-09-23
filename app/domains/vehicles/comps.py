"""Transparent comparable selection. Sibling vans are not interchangeable."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domains.vehicles.enums import Fuel, ObservationStatus
from app.domains.vehicles.identity import VehicleIdentity
from app.domains.vehicles.market import MarketObservation
from app.domains.vehicles.policy import COMP_CLOSE_SCORE, COMP_MIN_SCORE

_GOODS_BODIES = {"PANEL", "CHASSIS", "TIPPER", "DROPSIDE", "LUTON"}
_PEOPLE_BODIES = {"CREW", "KOMBI", "MINIBUS", "WINDOW"}
_DAMAGE_TOKENS = (
    "salvage",
    "cat s",
    "cat n",
    "cat c",
    "cat d",
    "category s",
    "category n",
    "write-off",
    "write off",
    "for spares",
    "spares or repair",
    "accident damaged",
    "damaged",
)


@dataclass(frozen=True, slots=True)
class CompScore:
    observation_id: str
    listing_id: str
    score: int
    close: bool
    rejected: bool
    reasons: tuple[str, ...]
    price_eur: Decimal | None
    realised: bool
    observed_at_iso: str
    url: str | None
    seller_type: str
    mileage_km: int | None
    year: int | None
    model_family: str
    source: str = ""
    registration: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "observation_id": self.observation_id,
            "listing_id": self.listing_id,
            "score": self.score,
            "close": self.close,
            "rejected": self.rejected,
            "reasons": list(self.reasons),
            "price_eur": str(self.price_eur) if self.price_eur is not None else None,
            "realised": self.realised,
            "observed_at": self.observed_at_iso,
            "url": self.url,
            "seller_type": self.seller_type,
            "mileage_km": self.mileage_km,
            "year": self.year,
            "model_family": self.model_family,
            "source": self.source,
            "registration": self.registration,
        }


def _body_name(identity: VehicleIdentity) -> str:
    return identity.body.value


def score_comp(subject: VehicleIdentity, comp: MarketObservation) -> CompScore:
    reasons: list[str] = []
    rejected = False
    if comp.model_family != subject.model_family or comp.manufacturer != subject.manufacturer:
        rejected = True
        reasons.append("Different manufacturer or model family. Sibling platforms are not comps.")
        return _finish(comp, 0, rejected, reasons, subject)

    title = (comp.listing_title or "").lower()
    flags = {flag.lower() for flag in comp.condition_flags}
    if flags.intersection(_DAMAGE_TOKENS) or any(token in title for token in _DAMAGE_TOKENS):
        rejected = True
        reasons.append("Damaged, salvage, or spares listing rejected.")

    score = 30
    reasons.append("Same model family (+30).")

    if subject.generation and comp.generation:
        if subject.generation == comp.generation:
            score += 10
            reasons.append("Same generation (+10).")
        else:
            rejected = True
            reasons.append("Generation mismatch rejected.")

    subject_body = _body_name(subject)
    comp_body = (comp.body or "UNKNOWN").upper()
    if subject_body in _GOODS_BODIES and comp_body in _PEOPLE_BODIES:
        rejected = True
        reasons.append("Goods body compared with a crew, kombi, or people-mover.")
    elif subject_body == comp_body and subject_body != "UNKNOWN":
        score += 10
        reasons.append("Same body (+10).")
    elif subject_body != "UNKNOWN" and comp_body not in {"", "UNKNOWN"} and subject_body != comp_body:
        rejected = True
        reasons.append("Body configuration differs.")

    if subject.fuel is not Fuel.UNKNOWN and comp.fuel is not Fuel.UNKNOWN:
        if subject.fuel is comp.fuel:
            score += 8
            reasons.append("Same fuel (+8).")
        else:
            rejected = True
            reasons.append("Fuel mismatch.")

    if subject.transmission and comp.transmission:
        if subject.transmission == comp.transmission:
            score += 4
            reasons.append("Same transmission (+4).")
        else:
            score -= 4
            reasons.append("Transmission mismatch (-4).")

    if subject.year and comp.year:
        gap = abs(subject.year - comp.year)
        if gap > 6:
            rejected = True
            reasons.append("Year gap greater than 6.")
        elif gap <= 1:
            score += 10
            reasons.append("Year within 1 (+10).")
        elif gap <= 2:
            score += 6
            reasons.append("Year within 2 (+6).")
        else:
            score += 2
            reasons.append("Year within 4 to 6 (+2).")

    if subject.mileage_km and comp.mileage_km:
        ratio = Decimal(comp.mileage_km) / Decimal(subject.mileage_km)
        if ratio < Decimal("0.45") or ratio > Decimal("2.2"):
            rejected = True
            reasons.append("Mileage too far from the subject.")
        elif Decimal("0.80") <= ratio <= Decimal("1.20"):
            score += 10
            reasons.append("Mileage within 20% (+10).")
        elif Decimal("0.60") <= ratio <= Decimal("1.40"):
            score += 5
            reasons.append("Mileage within 40% (+5).")

    if subject.wheelbase and comp.wheelbase:
        if subject.wheelbase == comp.wheelbase:
            score += 6
            reasons.append("Same wheelbase (+6).")
        else:
            rejected = True
            reasons.append("Wheelbase mismatch rejected.")
    if subject.roof and comp.roof:
        if subject.roof == comp.roof:
            score += 4
            reasons.append("Same roof (+4).")
        else:
            score -= 6
            reasons.append("Roof mismatch (-6).")
    if subject.engine and comp.engine:
        if subject.engine == comp.engine:
            score += 6
            reasons.append("Same engine (+6).")
        else:
            score -= 8
            reasons.append("Engine mismatch (-8).")
    if subject.derivative and comp.derivative and subject.derivative == comp.derivative:
        score += 4
        reasons.append("Same derivative (+4).")

    if score < COMP_MIN_SCORE:
        rejected = True
        reasons.append(f"Score {score} below {COMP_MIN_SCORE}.")
    return _finish(comp, score, rejected, reasons, subject)


def _finish(comp: MarketObservation, score: int, rejected: bool, reasons: list[str], subject: VehicleIdentity) -> CompScore:
    del subject
    realised = comp.status is ObservationStatus.REALISED_SALE and comp.realised_price_eur is not None
    price = comp.realised_price_eur if realised else comp.asking_price_eur
    if price is None:
        rejected = True
        reasons.append("No price on the observation.")
    if comp.status in {ObservationStatus.DISAPPEARED, ObservationStatus.WITHDRAWN, ObservationStatus.EXPIRED, ObservationStatus.UNKNOWN}:
        rejected = True
        reasons.append(f"Status {comp.status.value} is not a price observation. Disappearance is not a sale.")
        price = None
    return CompScore(
        observation_id=comp.observation_id,
        listing_id=comp.listing_id,
        score=score,
        close=score >= COMP_CLOSE_SCORE and not rejected,
        rejected=rejected,
        reasons=tuple(reasons),
        price_eur=price,
        realised=realised and not rejected,
        observed_at_iso=comp.observed_at.isoformat(),
        url=comp.url,
        seller_type=comp.seller_type,
        mileage_km=comp.mileage_km,
        year=comp.year,
        model_family=comp.model_family,
        source=comp.source,
        registration=(comp.registration or "").upper().replace(" ", ""),
    )
