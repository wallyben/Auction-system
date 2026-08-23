"""Evidence tiers. Weak asking comps must not drown strong realised comps."""

from __future__ import annotations

from app.models.enums import EvidenceType

TIER_A = "TIER_A"
TIER_B = "TIER_B"
TIER_C = "TIER_C"
TIER_D = "TIER_D"
TIER_E = "TIER_E"
TIER_F = "TIER_F"

STRONG_TIERS = {TIER_A, TIER_B, TIER_C}
BUY_READY_TIERS = STRONG_TIERS


def classify_tier(evidence_type: EvidenceType, *, exact_sku: bool = True, locality_ok: bool = True) -> str:
    if evidence_type in {EvidenceType.REALISED_SALE, EvidenceType.OWNER_RECORDED}:
        if exact_sku and locality_ok:
            return TIER_A
        return TIER_B
    if evidence_type is EvidenceType.AUCTION_HAMMER:
        return TIER_C
    if evidence_type is EvidenceType.TRADE_IN:
        return TIER_D
    if evidence_type is EvidenceType.DEALER_RETAIL:
        return TIER_E
    return TIER_F


TIER_LABEL = {
    TIER_A: "Verified recent realised transaction, exact SKU/variant/condition.",
    TIER_B: "Verified realised transaction, imperfect condition or locality.",
    TIER_C: "Auction hammer / strong completed-sale evidence.",
    TIER_D: "Trade-buy / liquidation quote.",
    TIER_E: "Dealer retail.",
    TIER_F: "Active asking.",
}
