"""Valuation statistics and asking-versus-sale discipline."""

from datetime import datetime, timezone
from decimal import Decimal

from app.models.enums import EvidenceType
from app.valuation.engine import Comp, value_from_comps
from app.valuation.stats import reject_outliers, weighted_median


def test_outliers_are_separated_when_spread_exists() -> None:
    values = [Decimal("100"), Decimal("110"), Decimal("105"), Decimal("120"), Decimal("800")]
    kept, rejected = reject_outliers(values)
    assert Decimal("800") in rejected or Decimal("800") not in kept


def test_weighted_median_ignores_tiny_weight() -> None:
    result = weighted_median(
        [(Decimal("10"), Decimal("1")), (Decimal("20"), Decimal("1")), (Decimal("100"), Decimal("0.01"))]
    )
    assert result < Decimal("50")


def test_asking_only_is_not_called_realised() -> None:
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="reverb",
            url="https://example.com/1",
            title="Sony A7 IV",
            price_eur=Decimal("1400"),
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="DE",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.8"),
            observed_at=now,
        ),
        Comp(
            source="reverb",
            url="https://example.com/2",
            title="Sony A7 IV",
            price_eur=Decimal("1500"),
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="FR",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.8"),
            observed_at=now,
        ),
        Comp(
            source="reverb",
            url="https://example.com/3",
            title="Sony A7 IV",
            price_eur=Decimal("1450"),
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="NL",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.8"),
            observed_at=now,
        ),
    ]
    result = value_from_comps(comps)
    assert result.realised_count == 0
    assert result.confidence <= Decimal("0.48")
    assert result.expected_sale_eur == Decimal("0.00")
    assert result.asking_implied_eur > Decimal("0")
    assert result.value_status == "UNVALIDATED_VALUE"
    assert "asking" in result.method
