"""Liquidity from realised sold tickets, not category priors."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.liquidity.engine import LiquidityResult, money_risk
from app.models.orm import SoldEvidence

HIGH = "HIGH_REALIZED_VELOCITY"
MEDIUM = "MEDIUM_REALIZED_VELOCITY"
LOW = "LOW_REALIZED_VELOCITY"
UNKNOWN = "UNKNOWN"


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def sold_velocity(
    session: Session,
    canonical_product_id: str,
    *,
    now: datetime | None = None,
    rows: list[SoldEvidence] | None = None,
) -> dict[str, object]:
    now = now or datetime.now(timezone.utc)
    if rows is None:
        rows = session.scalars(
            select(SoldEvidence).where(SoldEvidence.canonical_product_id == canonical_product_id)
        ).all()
    accepted = [
        row
        for row in rows
        if (row.extras or {}).get("accepted_for_valuation", True) is not False
        and (row.source or "") not in {"owner_recorded", "owner_sales", "ebay_owner_fulfillment"}
    ]

    def count_since(days: int) -> int:
        cutoff = now - timedelta(days=days)
        n = 0
        for row in accepted:
            sold = _aware(row.sold_date)
            if sold and sold >= cutoff:
                n += 1
        return n

    n30 = count_since(30)
    n60 = count_since(60)
    n90 = count_since(90)
    per_week = (Decimal(n90) / Decimal("12.857")) if n90 else Decimal("0")
    if n30 >= 8:
        kind = HIGH
    elif n30 >= 3 or n90 >= 8:
        kind = MEDIUM
    elif n90 >= 1:
        kind = LOW
    else:
        kind = UNKNOWN
    newest = max((_aware(r.sold_date) for r in accepted if r.sold_date), default=None)
    age = (now - newest).days if newest else None
    return {
        "sales_count_30d": n30,
        "sales_count_60d": n60,
        "sales_count_90d": n90,
        "sold_velocity_per_week": str(per_week.quantize(Decimal("0.01"))),
        "evidence_freshness_days": age,
        "kind": kind,
        "n": len(accepted),
        "note": "Velocity from accepted realised tickets. Not a sell-through rate (active inventory denominator unknown).",
    }


def liquidity_from_sold(
    velocity: dict[str, object],
    *,
    comparable_count: int,
    is_lot: bool,
) -> LiquidityResult:
    kind = str(velocity.get("kind") or UNKNOWN)
    n90 = int(velocity.get("sales_count_90d") or 0)
    n30 = int(velocity.get("sales_count_30d") or 0)
    if kind == UNKNOWN or n90 == 0:
        return LiquidityResult(
            score=Decimal("0.20"),
            expected_days_to_sale=None,
            expected_days_to_sale_low=None,
            expected_days_to_sale_high=None,
            liquidity_confidence=Decimal("0.20"),
            quick_sale_discount=Decimal("0.15"),
            slow_sale_risk=Decimal("0.80"),
            notes="UNKNOWN realised velocity. Category prior not used as a sell-through rate.",
            kind=UNKNOWN,
        )
    if kind == HIGH:
        days, low, high, score, conf = 14, 7, 21, Decimal("0.82"), Decimal("0.70")
    elif kind == MEDIUM:
        days, low, high, score, conf = 21, 10, 35, Decimal("0.62"), Decimal("0.55")
    else:
        days, low, high, score, conf = 35, 21, 55, Decimal("0.42"), Decimal("0.40")
    if is_lot:
        score -= Decimal("0.15")
        conf = min(conf, Decimal("0.35"))
    return LiquidityResult(
        score=max(score, Decimal("0")),
        expected_days_to_sale=days,
        expected_days_to_sale_low=low,
        expected_days_to_sale_high=high,
        liquidity_confidence=conf,
        quick_sale_discount=Decimal("0.10") if kind == HIGH else Decimal("0.14"),
        slow_sale_risk=money_risk(score),
        notes=(
            f"{kind} from realised tickets: 30d={n30} 90d={n90}. "
            "Not an exact sell-through rate."
        ),
        kind=kind,
    )
