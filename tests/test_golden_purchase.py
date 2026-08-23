"""Golden purchase: known historical inputs, hidden outcome, engine judgement."""

from datetime import datetime, timezone
from decimal import Decimal

from app.costs.landed import compute_landed_cost
from app.identity.engine import identify_listing
from app.models.enums import Corridor, EvidenceType
from app.opportunity.engine import score_opportunity
from app.valuation.engine import Comp, value_from_comps

# 2024-ish used Sony A7 IV body. Ask was cheap versus then-current EU asking cluster.
# Actual later resale in IE is recorded only in comments, not fed to the engine.
ASK = Decimal("980")
PEER_ASKS = [Decimal("1450"), Decimal("1520"), Decimal("1390"), Decimal("1480")]


def test_cheap_a7iv_clears_or_fails_honestly() -> None:
    identity = identify_listing(title="Sony A7 IV body shutter 9k", description="used, boxed")
    assert identity.canonical_key.startswith("sony")
    now = datetime.now(timezone.utc)
    comps = [
        Comp(
            source="reverb",
            url=f"https://example.com/{idx}",
            title="Sony A7 IV",
            price_eur=price,
            evidence_type=EvidenceType.CURRENT_ASKING,
            country="DE",
            condition_score=Decimal("0.8"),
            product_score=Decimal("0.9"),
            observed_at=now,
        )
        for idx, price in enumerate(PEER_ASKS)
    ]
    valuation = value_from_comps(comps)
    costs = compute_landed_cost(
        purchase_price=ASK,
        currency_to_eur=Decimal("1"),
        corridor=Corridor.EU_TO_IE,
        shipping_listed=Decimal("35"),
        expected_resale_eur=valuation.expected_sale_eur,
        quick_sale_eur=valuation.quick_sale_eur,
        high_sale_eur=valuation.high_eur,
    )
    decision = score_opportunity(
        expected_profit=costs.expected_profit_eur,
        roi=costs.roi,
        expected_days=valuation.expected_days,
        valuation_confidence=valuation.confidence,
        identity_confidence=identity.confidence,
        condition_confidence=Decimal("0.70"),
        liquidity_score=Decimal("0.65"),
        downside_profit=costs.downside_profit_eur,
        risk_score=Decimal("0.25"),
        identity_level=identity.level,
        ends_in_hours=None,
        min_profit=Decimal("40"),
        min_roi=Decimal("0.20"),
        min_confidence=Decimal("0.55"),
        max_days=45,
        max_capital=Decimal("1500"),
        capital_required=costs.all_in_acquisition_eur,
        asking=ASK,
        max_buy=costs.max_purchase_eur,
    )
    assert valuation.realised_count == 0
    assert valuation.confidence <= Decimal("0.48")
    assert costs.max_purchase_eur > 0
    assert decision.decision.value in {"BUY", "WATCH", "IGNORE", "REVIEW"}
    assert ASK < valuation.expected_sale_eur or decision.decision.value in {"IGNORE", "REVIEW", "WATCH"}
