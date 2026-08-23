from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import EvidenceType
from app.valuation.engine import Comp, value_from_comps
from app.valuation.tiers import TIER_A, TIER_F, classify_tier


def _comp(price: str, evidence: EvidenceType, country: str = "IE", title: str = "Sony A7 IV") -> Comp:
    return Comp(
        source="test",
        url="https://example.test",
        title=title,
        price_eur=Decimal(price),
        evidence_type=evidence,
        country=country,
        condition_score=Decimal("0.90"),
        product_score=Decimal("0.95"),
        observed_at=datetime.now(timezone.utc),
    )


def test_asking_cannot_overwhelm_realised() -> None:
    comps = [
        _comp("900", EvidenceType.REALISED_SALE),
        _comp("1600", EvidenceType.CURRENT_ASKING),
        _comp("1700", EvidenceType.CURRENT_ASKING),
        _comp("1800", EvidenceType.CURRENT_ASKING),
        _comp("1900", EvidenceType.CURRENT_ASKING),
    ]
    result = value_from_comps(comps)
    assert result.realised_count == 1
    assert result.expected_sale_eur == Decimal("900.00")
    assert result.provenance["priced_from"] == "strong_realised"


def test_tier_labels() -> None:
    assert classify_tier(EvidenceType.REALISED_SALE) == TIER_A
    assert classify_tier(EvidenceType.CURRENT_ASKING) == TIER_F
