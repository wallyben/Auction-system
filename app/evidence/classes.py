"""Evidence classes A–G. Asking prices are never realised sales."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.models.enums import EvidenceType


class EvidenceClass(str, enum.Enum):
    """Commercial evidence strength. Do not collapse these."""

    A = "A"  # market-wide realised transaction
    B = "B"  # auction hammer / verified completed transaction
    C = "C"  # owner realised transaction (not market-wide)
    D = "D"  # binding dealer / trade-in quote
    E = "E"  # historical dealer / statistical market value (aggregate, not a ticket)
    F = "F"  # current asking price
    G = "G"  # guide / reference price


BINDING_CLASSES = {EvidenceClass.A, EvidenceClass.B, EvidenceClass.C, EvidenceClass.D}
REALISED_CLASSES = {EvidenceClass.A, EvidenceClass.B, EvidenceClass.C}
MARKET_WIDE_CLASSES = {EvidenceClass.A, EvidenceClass.B}
ASKING_CLASSES = {EvidenceClass.F}

CLASS_LABEL = {
    EvidenceClass.A: "Market-wide realised transaction",
    EvidenceClass.B: "Auction hammer / verified completed transaction",
    EvidenceClass.C: "Owner realised transaction (not market-wide)",
    EvidenceClass.D: "Binding dealer / trade-in quote",
    EvidenceClass.E: "Historical dealer / statistical market value",
    EvidenceClass.F: "Current asking price",
    EvidenceClass.G: "Guide / reference price",
}


def evidence_class_for(
    evidence_type: EvidenceType,
    *,
    source: str = "",
    ticket_level: bool = True,
    binding_quote: bool = False,
) -> EvidenceClass:
    src = (source or "").lower()
    if src in {"owner_recorded", "owner_sales", "ebay_owner_fulfillment"}:
        return EvidenceClass.C
    if src in {"owner_trade_floor", "cex_trade_in"} or (
        evidence_type is EvidenceType.TRADE_IN and binding_quote
    ):
        return EvidenceClass.D
    if src in {"terapeak_aggregate", "product_research_aggregate"} or (
        evidence_type is EvidenceType.ESTIMATE and not ticket_level
    ):
        return EvidenceClass.E
    if evidence_type is EvidenceType.AUCTION_HAMMER:
        return EvidenceClass.B
    if evidence_type is EvidenceType.REALISED_SALE:
        return EvidenceClass.A if ticket_level else EvidenceClass.E
    if evidence_type is EvidenceType.OWNER_RECORDED:
        return EvidenceClass.C
    if evidence_type is EvidenceType.TRADE_IN:
        return EvidenceClass.D if binding_quote else EvidenceClass.G
    if evidence_type is EvidenceType.CURRENT_ASKING:
        return EvidenceClass.F
    if evidence_type in {EvidenceType.DEALER_RETAIL, EvidenceType.ESTIMATE}:
        return EvidenceClass.G
    return EvidenceClass.F


@dataclass(slots=True)
class EvidenceRecord:
    source: str
    source_type: str
    evidence_class: EvidenceClass
    product_identity: str
    variant: str
    condition: str
    price: Decimal
    currency: str
    price_eur: Decimal
    observed_at: datetime
    marketplace: str
    country: str
    shipping: Decimal | None = None
    seller_type: str | None = None
    provenance: str = ""
    source_reference: str | None = None
    confidence: Decimal = Decimal("0.50")
    title: str = ""
    notes: str = ""
    ticket_level: bool = True
    extras: dict = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "evidence_class": self.evidence_class.value,
            "class_label": CLASS_LABEL[self.evidence_class],
            "product_identity": self.product_identity,
            "variant": self.variant,
            "condition": self.condition,
            "price": str(self.price),
            "currency": self.currency,
            "price_eur": str(self.price_eur),
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "marketplace": self.marketplace,
            "country": self.country,
            "shipping": str(self.shipping) if self.shipping is not None else None,
            "seller_type": self.seller_type,
            "provenance": self.provenance,
            "source_reference": self.source_reference,
            "confidence": str(self.confidence),
            "title": self.title,
            "notes": self.notes,
            "ticket_level": self.ticket_level,
        }
