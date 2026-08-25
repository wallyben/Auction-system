"""Write realised-sale hits into sold_evidence. Never persist asking prices here."""

from __future__ import annotations

import hashlib
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

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
                    "asking_relabelled": False,
                },
            )
        )
        written += 1
    session.flush()
    return {"imported": written, "duplicates": skipped}


def as_eur(amount: Decimal, currency: str, rates: dict[str, Decimal] | None) -> Decimal:
    cur = (currency or "EUR").upper()
    if cur == "EUR":
        return amount
    if not rates:
        return amount
    rate = rates.get(cur)
    if rate is None or rate <= 0:
        return amount
    return amount * rate
