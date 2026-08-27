"""Lookahead-free sold-distribution backtest.

When live CompSniper history exists, historical subset T is scored only from
records dated before T. This module also ships a deterministic synthetic
corpus so the metric path is tested without burning provider quota.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.models.enums import EvidenceType
from app.valuation.engine import Comp, value_from_comps
from app.valuation.stats import median as robust_median


def _comp(price: str, days_ago: int, country: str = "GB") -> Comp:
    now = datetime.now(timezone.utc)
    return Comp(
        source="compsniper",
        url=f"https://www.ebay.co.uk/itm/{days_ago}",
        title="Sony A7 IV body",
        price_eur=Decimal(price),
        evidence_type=EvidenceType.REALISED_SALE,
        country=country,
        condition_score=Decimal("0.90"),
        product_score=Decimal("0.95"),
        observed_at=now - timedelta(days=days_ago),
        evidence_class="A",
    )


def synthetic_lookahead_backtest() -> dict[str, object]:
    """Predict later sold prices from earlier tickets only."""
    earlier = [
        _comp("1250", 80),
        _comp("1180", 70),
        _comp("1300", 60),
        _comp("1220", 55),
        _comp("1280", 50),
        _comp("1190", 45),
        _comp("1260", 40),
        _comp("1210", 35),
    ]
    later = [
        _comp("1240", 20),
        _comp("1275", 12),
        _comp("1200", 8),
        _comp("1230", 4),
    ]
    predicted = value_from_comps(earlier)
    actuals = [c.price_eur for c in later]
    errors = [abs(a - predicted.expected_sale_eur) for a in actuals]
    pct = [abs(a - predicted.expected_sale_eur) / a for a in actuals if a]
    bias = sum((predicted.expected_sale_eur - a) for a in actuals) / Decimal(len(actuals))
    low, high = predicted.p25, predicted.p75
    coverage = sum(1 for a in actuals if low <= a <= high) / len(actuals)
    mae = sum(errors) / Decimal(len(errors))
    return {
        "sample_size": len(later),
        "train_n": len(earlier),
        "mae": str(mae),
        "median_abs_error": str(robust_median(errors)),
        "mean_pct_error": str((sum(pct) / Decimal(len(pct))).quantize(Decimal("0.0001"))),
        "bias": str(bias),
        "p25_p75_coverage": round(coverage, 4),
        "predicted_expected": str(predicted.expected_sale_eur),
        "predicted_p25": str(predicted.p25),
        "predicted_p75": str(predicted.p75),
        "method": predicted.method,
        "local_market_method": predicted.local_market_method,
        "lookahead_free": True,
        "note": "Synthetic dated corpus. Live CompSniper history replaces this once the owner key is live.",
    }
