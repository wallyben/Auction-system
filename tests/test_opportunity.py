"""Decision gates must fail closed."""

from decimal import Decimal

from app.models.enums import Decision, IdentityLevel
from app.opportunity.engine import score_opportunity


def _kwargs(**overrides):
    data = dict(
        expected_profit=Decimal("200"),
        roi=Decimal("0.40"),
        expected_days=10,
        valuation_confidence=Decimal("0.80"),
        identity_confidence=Decimal("0.80"),
        condition_confidence=Decimal("0.80"),
        liquidity_score=Decimal("0.70"),
        downside_profit=Decimal("50"),
        risk_score=Decimal("0.20"),
        identity_level=IdentityLevel.EXACT,
        ends_in_hours=None,
        min_profit=Decimal("40"),
        min_roi=Decimal("0.20"),
        min_confidence=Decimal("0.55"),
        max_days=45,
        max_capital=Decimal("1500"),
        capital_required=Decimal("400"),
        asking=Decimal("300"),
        max_buy=Decimal("500"),
    )
    data.update(overrides)
    return data


def test_weak_identity_is_review() -> None:
    result = score_opportunity(
        **_kwargs(identity_confidence=Decimal("0.20"), identity_level=IdentityLevel.UNKNOWN)
    )
    assert result.decision == Decision.REVIEW


def test_negative_profit_is_ignore() -> None:
    result = score_opportunity(
        **_kwargs(expected_profit=Decimal("-20"), roi=Decimal("-0.05"), downside_profit=Decimal("-40"))
    )
    assert result.decision == Decision.IGNORE
