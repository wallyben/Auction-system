"""Normalize CompSniper rows into canonical sold-evidence records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.money import money
from app.evidence.classes import EvidenceClass
from app.evidence.providers.compsniper import CompSniperItem
from app.models.enums import EvidenceType
from app.sold.cameras import SITE_TO_TERRITORY
from app.sold.condition_map import map_sold_condition
from app.sold.identity_gate import IdentityVerdict, PRODUCT_CLASS_CAMERA_BODY, validate_camera_sold
from app.sold.cameras import CameraBody
from app.sold.provider import SoldEvidenceHit

EVIDENCE_CLASS_NAME = "MARKET_WIDE_COMPLETED_SALE"
PROVIDER = "compsniper"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_eur(amount: Decimal | None, currency: str | None, rates: dict[str, Decimal] | None) -> Decimal | None:
    if amount is None:
        return None
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return money(amount)
    if not rates:
        return None
    units = rates.get(cur)
    if not units or units <= 0:
        return None
    # ECB quote is units per EUR (GBP per 1 EUR). EUR = amount / units.
    return money(amount / units)


@dataclass(slots=True)
class CanonicalSoldRecord:
    provider: str
    marketplace: str
    source_listing_id: str
    source_url: str | None
    title: str
    product_class: str
    canonical_product_id: str
    variant: str
    condition_raw: str
    condition_grade: str
    sold_price: Decimal
    shipping_price: Decimal | None
    buyer_total: Decimal | None
    currency: str
    sold_price_eur: Decimal | None
    shipping_eur: Decimal | None
    sold_at: datetime
    seller: dict[str, Any]
    imported_at: datetime
    provenance: str
    evidence_class: str
    evidence_class_letter: str
    accepted_for_valuation: bool
    rejection_reason: str
    raw: dict[str, Any] = field(default_factory=dict)
    best_offer_accepted: bool = False
    listing_type: str = "sold"
    price_certainty: str = "KNOWN_TRANSACTION"

    def as_hit(self) -> SoldEvidenceHit:
        price = self.sold_price_eur if self.sold_price_eur is not None else self.sold_price
        shipping = self.shipping_eur if self.shipping_eur is not None else self.shipping_price
        return SoldEvidenceHit(
            source=self.provider,
            title=self.title,
            sold_price_eur=price,
            territory=self.marketplace,
            condition=self.condition_grade.lower(),
            channel="ebay",
            sold_date=self.sold_at,
            evidence_type=EvidenceType.REALISED_SALE if self.accepted_for_valuation else EvidenceType.ESTIMATE,
            quality="high" if self.accepted_for_valuation else "rejected",
            url=self.source_url,
            notes=self.rejection_reason or EVIDENCE_CLASS_NAME,
            variant=self.variant,
            currency="EUR" if self.sold_price_eur is not None else self.currency,
            shipping=shipping,
            identity_key=self.canonical_product_id,
            provenance=self.provenance,
            market=self.marketplace,
            identity_confidence=Decimal("0.95") if self.accepted_for_valuation else Decimal("0"),
            matching_confidence=Decimal("0.95") if self.accepted_for_valuation else Decimal("0"),
        )


def normalize_item(
    item: CompSniperItem,
    *,
    target: CameraBody,
    ebay_site: str,
    rates: dict[str, Decimal] | None = None,
    imported_at: datetime | None = None,
) -> CanonicalSoldRecord:
    marketplace = SITE_TO_TERRITORY.get(ebay_site, "GB")
    cond = map_sold_condition(item.condition, condition_id=item.condition_id, title=item.title)
    verdict: IdentityVerdict = validate_camera_sold(
        target=target,
        sold_title=item.title,
        sold_condition_raw=item.condition,
        sold_condition_id=item.condition_id,
    )
    currency = (item.sold_currency or item.shipping_currency or "GBP").upper()
    sold = item.sold_price or Decimal("0")
    shipping = item.shipping_price
    buyer_total = item.total_price
    if buyer_total is None and sold is not None:
        buyer_total = sold + (shipping or Decimal("0"))
    sold_eur = to_eur(sold, item.sold_currency or currency, rates)
    shipping_eur = to_eur(shipping, item.shipping_currency or currency, rates)
    accepted = verdict.accepted
    reason = verdict.reason
    listing_type = (item.listing_type or "sold").lower().replace(" ", "_")
    if listing_type in {"active", "unsold", "cancelled", "canceled", "not_sold"}:
        accepted = False
        reason = "not_completed_sale"
    if sold is None or sold <= 0:
        accepted = False
        reason = "invalid_sold_price"
    price_certainty = "KNOWN_TRANSACTION"
    if item.best_offer_accepted or listing_type in {"best_offer_accepted", "bestofferaccepted"}:
        # CompSniper: Best Offer soldPrice is the asking ceiling, not the accepted offer.
        price_certainty = "UPPER_BOUND"
        if accepted:
            accepted = False
            reason = "best_offer_upper_bound"
    if not (item.sold_currency or currency):
        accepted = False
        reason = "invalid_currency"
    if item.ended_at is None:
        accepted = False
        reason = "implausible_date"
    else:
        age = (_now() - item.ended_at).days
        if age < -1 or age > 400:
            accepted = False
            reason = "implausible_date"
    if verdict.product_class != PRODUCT_CLASS_CAMERA_BODY and accepted:
        accepted = False
        reason = "wrong_product_class"

    return CanonicalSoldRecord(
        provider=PROVIDER,
        marketplace=marketplace,
        source_listing_id=item.item_id,
        source_url=item.url,
        title=item.title,
        product_class=verdict.product_class if accepted else verdict.product_class or "unknown",
        canonical_product_id=verdict.canonical_product_id or target.canonical_id,
        variant=verdict.variant or "body",
        condition_raw=item.condition or "",
        condition_grade=cond.grade,
        sold_price=sold,
        shipping_price=shipping,
        buyer_total=buyer_total,
        currency=currency,
        sold_price_eur=sold_eur,
        shipping_eur=shipping_eur,
        sold_at=item.ended_at or _now(),
        seller={
            "username": item.seller_username,
            "positive_percent": item.seller_positive_percent,
            "feedback_score": item.seller_feedback_score,
            "item_location": item.item_location,
        },
        imported_at=imported_at or _now(),
        provenance="compsniper:/v1/scrape",
        evidence_class=EVIDENCE_CLASS_NAME if accepted else "REJECTED",
        evidence_class_letter=EvidenceClass.A.value if accepted else "X",
        accepted_for_valuation=accepted,
        rejection_reason=reason,
        raw=item.raw,
        best_offer_accepted=item.best_offer_accepted,
        listing_type=item.listing_type,
        price_certainty=price_certainty,
    )
