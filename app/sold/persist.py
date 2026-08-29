"""Write realised-sale hits into sold_evidence. Never persist asking prices here."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import EvidenceType
from app.models.orm import SoldEvidence
from app.sold.provider import SoldEvidenceHit


def _fingerprint(hit: SoldEvidenceHit) -> str:
    key = "|".join(
        [
            hit.source,
            hit.identity_key or hit.title,
            hit.sold_date.date().isoformat() if hit.sold_date else "",
            str(hit.sold_price_eur),
            hit.currency,
            hit.url or "",
            hit.provenance,
        ]
    )
    return hashlib.sha256(key.encode()).hexdigest()


def persist_sold_hits(session: Session, hits: list[SoldEvidenceHit]) -> dict[str, int]:
    written = 0
    skipped = 0
    for hit in hits:
        if hit.evidence_type in {EvidenceType.CURRENT_ASKING, EvidenceType.DEALER_RETAIL, EvidenceType.ESTIMATE}:
            skipped += 1
            continue
        fp = _fingerprint(hit)
        existing = session.scalar(select(SoldEvidence).where(SoldEvidence.fingerprint == fp))
        if existing:
            skipped += 1
            continue
        session.add(
            SoldEvidence(
                canonical_product_id=hit.identity_key or hit.title[:512],
                condition=hit.condition or "unknown",
                channel=hit.channel,
                territory=hit.territory or "IE",
                sold_price=hit.sold_price_eur,
                currency=hit.currency or "EUR",
                shipping_charged=hit.shipping if hit.shipping else None,
                fees_if_known=None,
                sold_date=hit.sold_date,
                source=hit.source,
                evidence_quality=hit.quality,
                url_or_reference=hit.url,
                fingerprint=fp,
                extras={
                    "title": hit.title,
                    "variant": hit.variant,
                    "market": hit.market,
                    "provenance": hit.provenance,
                    "notes": hit.notes,
                    "product_identity": hit.identity_key,
                    "quantity": hit.quantity,
                    "identity_confidence": str(hit.identity_confidence) if hit.identity_confidence is not None else None,
                    "matching_confidence": str(hit.matching_confidence) if hit.matching_confidence is not None else None,
                    "evidence_type": hit.evidence_type.value,
                    "classification": "REALIZED_SOLD",
                    "asking_relabelled": False,
                    "accepted_for_valuation": True,
                    "evidence_class": "A",
                    "evidence_class_name": "MARKET_WIDE_COMPLETED_SALE" if hit.source == "compsniper" else hit.evidence_type.value,
                },
            )
        )
        written += 1
    session.flush()
    return {"imported": written, "duplicates": skipped}


def _canonical_fingerprint(provider: str, marketplace: str, source_listing_id: str) -> str:
    key = f"{provider}|{marketplace}|{source_listing_id}"
    return hashlib.sha256(key.encode()).hexdigest()


def persist_canonical_sold(session: Session, records: list[Any]) -> dict[str, int]:
    """Persist CompSniper canonical rows, including rejected identity candidates."""
    written = 0
    skipped = 0
    imported_accepted = 0
    rejected = 0
    fingerprints = [_canonical_fingerprint(rec.provider, rec.marketplace, rec.source_listing_id) for rec in records]
    existing_by_fp: dict[str, SoldEvidence] = {}
    if fingerprints:
        for row in session.scalars(select(SoldEvidence).where(SoldEvidence.fingerprint.in_(fingerprints))).all():
            existing_by_fp[row.fingerprint] = row
    urls = [rec.source_url for rec in records if rec.source_url]
    existing_by_url: dict[str, SoldEvidence] = {}
    if urls:
        for row in session.scalars(
            select(SoldEvidence).where(SoldEvidence.source == "compsniper", SoldEvidence.url_or_reference.in_(urls))
        ).all():
            if row.url_or_reference:
                existing_by_url[row.url_or_reference] = row
    for rec in records:
        fp = _canonical_fingerprint(rec.provider, rec.marketplace, rec.source_listing_id)
        existing = existing_by_fp.get(fp)
        if existing is None and rec.source_url:
            existing = existing_by_url.get(rec.source_url)
        extras = {
            "title": rec.title,
            "variant": rec.variant,
            "market": rec.marketplace,
            "provenance": rec.provenance,
            "notes": rec.rejection_reason or rec.evidence_class,
            "product_identity": rec.canonical_product_id,
            "quantity": 1,
            "evidence_type": "realised_sale",
            "classification": "REALIZED_SOLD" if rec.accepted_for_valuation else "REJECTED_SOLD_CANDIDATE",
            "asking_relabelled": False,
            "accepted_for_valuation": rec.accepted_for_valuation,
            "rejection_reason": rec.rejection_reason,
            "evidence_class": rec.evidence_class_letter,
            "evidence_class_name": rec.evidence_class,
            "product_class": rec.product_class,
            "condition_raw": rec.condition_raw,
            "condition_grade": rec.condition_grade,
            "sold_price_native": str(rec.sold_price),
            "shipping_native": str(rec.shipping_price) if rec.shipping_price is not None else None,
            "buyer_total_native": str(rec.buyer_total) if rec.buyer_total is not None else None,
            "native_currency": rec.currency,
            "sold_price_eur": str(rec.sold_price_eur) if rec.sold_price_eur is not None else None,
            "shipping_eur": str(rec.shipping_eur) if rec.shipping_eur is not None else None,
            "seller": rec.seller,
            "imported_at": rec.imported_at.isoformat() if rec.imported_at else None,
            "source_listing_id": rec.source_listing_id,
            "best_offer_accepted": rec.best_offer_accepted,
            "price_certainty": getattr(rec, "price_certainty", "KNOWN_TRANSACTION"),
            "listing_type": rec.listing_type,
            "raw": rec.raw,
            "ticket_level": True,
        }
        price = rec.sold_price_eur if rec.sold_price_eur is not None else rec.sold_price
        if rec.shipping_eur is not None and rec.sold_price_eur is not None:
            price = rec.sold_price_eur + rec.shipping_eur
        elif rec.buyer_total is not None and rec.sold_price_eur is None:
            price = rec.buyer_total
        shipping = rec.shipping_eur if rec.shipping_eur is not None else rec.shipping_price
        if existing:
            existing.extras = {**(existing.extras or {}), **extras}
            existing.condition = rec.condition_grade.lower()
            existing.sold_price = price
            existing.shipping_charged = shipping
            existing.evidence_quality = "high" if rec.accepted_for_valuation else "rejected"
            skipped += 1
            continue
        session.add(
            SoldEvidence(
                canonical_product_id=rec.canonical_product_id,
                condition=rec.condition_grade.lower(),
                channel="ebay",
                territory=rec.marketplace,
                sold_price=price,
                currency="EUR" if rec.sold_price_eur is not None else rec.currency,
                shipping_charged=shipping,
                fees_if_known=None,
                sold_date=rec.sold_at,
                source=rec.provider,
                evidence_quality="high" if rec.accepted_for_valuation else "rejected",
                url_or_reference=rec.source_url or rec.source_listing_id,
                fingerprint=fp,
                extras=extras,
            )
        )
        written += 1
        if rec.accepted_for_valuation:
            imported_accepted += 1
        else:
            rejected += 1
    session.flush()
    return {
        "imported": written,
        "duplicates": skipped,
        "imported_accepted": imported_accepted,
        "rejected": rejected,
    }


def as_eur(amount: Decimal, currency: str, rates: dict[str, Decimal] | None) -> Decimal:
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return amount
    if not rates:
        return amount
    rate = rates.get(cur)
    if rate is None or rate <= 0:
        return amount
    # ECB quote is units of `currency` per 1 EUR.
    return amount / rate
